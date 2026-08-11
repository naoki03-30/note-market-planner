import json
import os
import statistics
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from db import upsert_article

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
    "Mobile/15E148 Safari/604.1"
)

INTERVAL = float(os.getenv("REQUEST_INTERVAL_SECONDS", "1.2"))


def _client():
    return httpx.Client(
        headers={
            "User-Agent": UA,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
            "Cache-Control": "no-cache",
        },
        follow_redirects=True,
        timeout=httpx.Timeout(20.0, connect=8.0),
    )


def _get_json(url):
    time.sleep(INTERVAL)
    with _client() as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def _hashtag_api_url(tag, page=1):
    encoded = quote(tag, safe="")
    return (
        f"https://note.com/api/v3/hashtags/{encoded}/notes"
        f"?order=new&page={page}&paid_only=false"
    )


def _find_notes(payload):
    """
    note側のレスポンス形が
      {notes:[...]}
    または
      {data:{notes:[...]}}
    のどちらでも扱う。
    """
    if isinstance(payload, dict):
        if isinstance(payload.get("notes"), list):
            return payload["notes"], payload
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("notes"), list):
            return data["notes"], data
    return [], {}


def _to_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        if s.isdigit():
            return int(s)
    return None


def _pick(d, *names):
    if not isinstance(d, dict):
        return None
    for name in names:
        if name in d and d[name] not in (None, ""):
            return d[name]
    return None


def _body_to_text(body):
    if not isinstance(body, str):
        return ""
    # APIのbodyがHTMLでもプレーンテキストでも対応
    if "<" in body and ">" in body:
        return BeautifulSoup(body, "html.parser").get_text("\n", strip=True)
    return body.strip()


def _note_to_article(note):
    """
    ハッシュタグAPIの1記事をアプリ内部形式へ変換。
    スキ数は like_count / likeCount だけを採用する。
    年・価格・日付等の数字は絶対にスキ数として使わない。
    """
    if not isinstance(note, dict):
        return None

    key = _pick(note, "key", "note_key", "noteKey")
    title = _pick(note, "name", "title", "headline") or ""
    published = _pick(note, "publish_at", "publishAt", "published_at", "publishedAt")
    likes = _to_int(_pick(note, "like_count", "likeCount"))

    user = note.get("user") if isinstance(note.get("user"), dict) else {}
    urlname = _pick(user, "urlname", "url_name", "username")
    author = _pick(user, "nickname", "name", "display_name") or ""

    # URL候補
    url = _pick(note, "note_url", "url", "share_url")
    if not url and key and urlname:
        url = f"https://note.com/{urlname}/n/{key}"
    elif not url and key:
        # creator名が取れない場合も識別用URLを持たせる
        url = f"https://note.com/n/{key}"

    body = _body_to_text(_pick(note, "body", "description") or "")

    if not key and not url:
        return None

    return {
        "url": url or "",
        "key": key or "",
        "title": str(title)[:500],
        "author": str(author)[:200],
        "published_at": published,
        "likes": likes,
        "body": body[:50000],
    }


def _is_recent(published_at, days=30):
    if not published_at:
        # 投稿日取得不能時は除外せず、診断可能な状態を維持
        return True
    try:
        dt = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= datetime.now(timezone.utc) - timedelta(days=days)
    except Exception:
        return True


def _fetch_hashtag_articles(tag, max_articles=60):
    """
    50件/ページを前提に必要ページだけ取得。
    note内部APIが変更された場合は diagnostics に残す。
    """
    articles = []
    diagnostics = []
    page = 1

    while len(articles) < max_articles:
        url = _hashtag_api_url(tag, page)

        try:
            payload = _get_json(url)
            notes, meta = _find_notes(payload)

            page_articles = []
            for note in notes:
                a = _note_to_article(note)
                if a:
                    page_articles.append(a)

            diagnostics.append({
                "method": "hashtag_api",
                "page": page,
                "http_ok": True,
                "notes": len(notes),
                "articles": len(page_articles),
            })

            articles.extend(page_articles)

            # 終端判定
            is_last = meta.get("is_last_page")
            next_page = meta.get("next_page")

            if not notes:
                break
            if is_last is True:
                break
            if next_page in (None, False, 0, "") and len(notes) < 50:
                break

            # next_page が整数ならそれを使い、それ以外は+1
            if isinstance(next_page, int) and next_page > page:
                page = next_page
            else:
                page += 1

            # 暴走防止
            if page > 20:
                break

        except Exception as e:
            diagnostics.append({
                "method": "hashtag_api",
                "page": page,
                "http_ok": False,
                "notes": 0,
                "articles": 0,
                "error": str(e)[:180],
            })
            break

    return articles[:max_articles], diagnostics


def connection_test(tag):
    """
    接続テスト:
    HTMLページにはアクセスせず、ハッシュタグAPIの最初の5件だけ確認。
    """
    articles, diagnostics = _fetch_hashtag_articles(tag, max_articles=5)
    sample = articles[:3]

    return {
        "method": "HASHTAG_API" if articles else "NONE",
        "urls": len(articles),
        "article_ok": len(sample),
        "likes_ok": sum(isinstance(a.get("likes"), int) for a in sample),
        "sample": [
            {
                "title": a.get("title", "")[:80],
                "likes": a.get("likes"),
                "url": a.get("url"),
            }
            for a in sample
        ],
        "diagnostics": diagnostics,
    }


def collect(tag, days=30, max_articles=60):
    """
    ハッシュタグ記事一覧APIから取得 → 期間絞込 → スキ中央値計算 → 選別。
    like_count以外の数字をスキとして解釈しない。
    """
    articles, diagnostics = _fetch_hashtag_articles(
        tag,
        max_articles=max_articles
    )

    recent = [
        a for a in articles
        if _is_recent(a.get("published_at"), days)
    ]

    like_values = [
        a["likes"]
        for a in recent
        if isinstance(a.get("likes"), int)
    ]

    median = statistics.median(like_values) if like_values else 0

    # 分析対象:
    # 1) 30スキ以上の絶対評価
    # 2) タグ内上位20%の相対評価
    # のどちらかを満たす記事。最大15件。
    ranked = sorted(
        [a for a in recent if isinstance(a.get("likes"), int)],
        key=lambda x: x["likes"],
        reverse=True
    )

    top_n = 0
    if ranked:
        top_n = max(1, int(len(ranked) * 0.20 + 0.9999))  # ceil
    relative_cutoff = ranked[top_n - 1]["likes"] if top_n else 0

    selected_urls = set()
    selected = []

    for a in ranked:
        absolute_ok = a["likes"] >= 30
        relative_ok = a["likes"] >= relative_cutoff if top_n else False

        if absolute_ok or relative_ok:
            key = a.get("url") or a.get("key")
            if key and key not in selected_urls:
                selected_urls.add(key)
                selected.append(a)

    # 詳細分析しすぎないよう最大15件
    qualified = selected[:15]

    qualified_keys = {
        a.get("url") or a.get("key")
        for a in qualified
    }

    for a in recent:
        key = a.get("url") or a.get("key")
        qualifies = key in qualified_keys

        # DBには本文を保存しない
        upsert_article({
            "url": key,
            "tag": tag,
            "title": a.get("title"),
            "author": a.get("author"),
            "published_at": a.get("published_at"),
            "likes": a.get("likes"),
            "qualifies": qualifies,
        })

    return {
        "tag": tag,
        "method": "HASHTAG_API" if articles else "NONE",
        "discovered_urls": len(articles),
        "found": len(recent),
        "likes_count": len(like_values),
        "median_likes": median,
        "threshold": 30,
        "relative_cutoff": relative_cutoff,
        "top_percent": 20,
        "qualified": qualified,
        "skipped_cooldown": 0,
        "fetch_errors": sum(
            1 for d in diagnostics if not d.get("http_ok")
        ),
        "diagnostics": diagnostics,
    }
