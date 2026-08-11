import json
import os
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup

from db import last_fetch, mark_fetch, upsert_article

# noteの公開Webページを低頻度で参照する。
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
    "Mobile/15E148 Safari/604.1"
)
INTERVAL = float(os.getenv("REQUEST_INTERVAL_SECONDS", "2.5"))
COOLDOWN_HOURS = float(os.getenv("SAME_URL_COOLDOWN_HOURS", "6"))

ARTICLE_RE = re.compile(
    r"https?://(?:[A-Za-z0-9-]+\.)?note\.com/[^/\s\"'<>]+/n/n[A-Za-z0-9_-]+"
)
RELATIVE_ARTICLE_RE = re.compile(
    r'(?:"|\'|\\")(/[^/\s"\'<>\\]+/n/n[A-Za-z0-9_-]+)'
)


def _is_article_url(url: str) -> bool:
    return bool(ARTICLE_RE.match(url.split("?")[0].split("#")[0]))


def can_fetch(url: str) -> bool:
    """
    6時間制限は個別記事URLに適用。
    タグ一覧ページは一覧情報そのものが更新されるため再取得可能にする。
    """
    if not _is_article_url(url):
        return True

    last = last_fetch(url)
    if not last:
        return True

    try:
        dt = datetime.fromisoformat(last)
        return datetime.now(timezone.utc) - dt >= timedelta(hours=COOLDOWN_HOURS)
    except Exception:
        return True


def get(url: str) -> str | None:
    if not can_fetch(url):
        return None

    time.sleep(INTERVAL)
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.6,en;q=0.5",
        "Cache-Control": "no-cache",
    }

    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=httpx.Timeout(25.0, connect=10.0),
        http2=True,
    ) as client:
        r = client.get(url)
        r.raise_for_status()

    # 個別記事だけfetch_logに残す。
    if _is_article_url(url):
        mark_fetch(url)

    return r.text


def tag_url(tag: str) -> str:
    return f"https://note.com/hashtag/{quote(tag, safe='')}?f=new"


def _normalize_article_url(raw: str) -> str | None:
    if not raw:
        return None

    s = unescape(raw)
    s = s.replace("\\/", "/")
    s = s.replace("\\u002F", "/")
    s = s.replace("\\u003A", ":")
    s = s.strip().strip('"').strip("'")

    if s.startswith("/"):
        s = urljoin("https://note.com", s)

    # custom note subdomain / note.com 本体どちらも許容
    m = ARTICLE_RE.search(s)
    if not m:
        return None

    return m.group(0).split("?")[0].split("#")[0]


def _walk_json(obj):
    """埋め込みJSONを再帰走査して文字列を拾う。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk_json(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_json(v)


def _urls_from_embedded_json(soup: BeautifulSoup) -> list[str]:
    urls = []

    for script in soup.find_all("script"):
        txt = script.string or script.get_text()
        if not txt:
            continue

        stripped = txt.strip()
        candidates = []

        # application/json / __NEXT_DATA__ など
        if (
            script.get("type") in ("application/json", "application/ld+json")
            or script.get("id") == "__NEXT_DATA__"
            or stripped.startswith("{")
            or stripped.startswith("[")
        ):
            try:
                candidates.append(json.loads(stripped))
            except Exception:
                pass

        for data in candidates:
            for _, value in _walk_json(data):
                if isinstance(value, str):
                    u = _normalize_article_url(value)
                    if u and u not in urls:
                        urls.append(u)

    return urls


def discover_article_urls(tag: str, max_articles: int = 60) -> list[str]:
    """
    noteタグページの記事URLを複数方式で抽出する。
    1) DOMのa[href]
    2) 埋め込みJSON (__NEXT_DATA__ 等)
    3) 生HTML内の絶対URL
    4) 生HTML内の相対URL
    """
    html = get(tag_url(tag))
    if html is None:
        return []

    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    def add(raw):
        u = _normalize_article_url(raw)
        if u and u not in urls:
            urls.append(u)

    # 1. 通常リンク
    for a in soup.find_all("a", href=True):
        add(a.get("href"))
        if len(urls) >= max_articles:
            return urls[:max_articles]

    # 2. 埋め込みJSON
    for u in _urls_from_embedded_json(soup):
        add(u)
        if len(urls) >= max_articles:
            return urls[:max_articles]

    # 3. 生HTMLの絶対URL（JSON内で \/ エスケープされたものも戻す）
    raw = unescape(html).replace("\\/", "/")
    raw = raw.replace("\\u002F", "/").replace("\\u003A", ":")
    for m in ARTICLE_RE.finditer(raw):
        add(m.group(0))
        if len(urls) >= max_articles:
            return urls[:max_articles]

    # 4. 相対URL
    for m in RELATIVE_ARTICLE_RE.finditer(raw):
        add(m.group(1))
        if len(urls) >= max_articles:
            return urls[:max_articles]

    return urls[:max_articles]


def _json_candidates(soup: BeautifulSoup):
    for script in soup.find_all("script"):
        txt = script.string or script.get_text()
        if not txt:
            continue
        if (
            script.get("type") in ("application/json", "application/ld+json")
            or script.get("id") == "__NEXT_DATA__"
            or txt.lstrip().startswith(("{", "["))
        ):
            try:
                data = json.loads(txt.strip())
                yield data
            except Exception:
                continue


def _first_recursive(obj, key_names):
    key_names = {x.lower() for x in key_names}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in key_names and v not in (None, ""):
                return v
        for v in obj.values():
            found = _first_recursive(v, key_names)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _first_recursive(v, key_names)
            if found not in (None, ""):
                return found
    return None


def extract_article(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    author = ""
    published = None
    likes = None

    # まず構造化JSONから取得
    for data in _json_candidates(soup):
        if not title:
            v = _first_recursive(data, {"headline", "title", "name"})
            if isinstance(v, str):
                title = v

        if not published:
            v = _first_recursive(
                data,
                {"datePublished", "publishAt", "publishedAt", "publish_at"}
            )
            if isinstance(v, str):
                published = v

        if likes is None:
            v = _first_recursive(
                data,
                {"likeCount", "likesCount", "like_count", "likes_count"}
            )
            if isinstance(v, (int, float)):
                likes = int(v)
            elif isinstance(v, str) and v.replace(",", "").isdigit():
                likes = int(v.replace(",", ""))

        if not author:
            v = _first_recursive(
                data,
                {"nickname", "displayName", "userName", "authorName"}
            )
            if isinstance(v, str):
                author = v

    # meta fallback
    if not title:
        meta = (
            soup.find("meta", property="og:title")
            or soup.find("meta", attrs={"name": "twitter:title"})
        )
        if meta:
            title = meta.get("content") or ""

    if not published:
        meta = (
            soup.find("meta", property="article:published_time")
            or soup.find("time", attrs={"datetime": True})
        )
        if meta:
            published = meta.get("content") or meta.get("datetime")

    # 生HTML fallback for likes
    if likes is None:
        raw = html.replace("\\/", "/")
        patterns = [
            r'"likeCount"\s*:\s*(\d+)',
            r'"likesCount"\s*:\s*(\d+)',
            r'"like_count"\s*:\s*(\d+)',
            r'"likes_count"\s*:\s*(\d+)',
            r'"likeCount&quot;\s*:\s*(\d+)',
        ]
        for pattern in patterns:
            m = re.search(pattern, raw)
            if m:
                likes = int(m.group(1))
                break

    if likes is None:
        text = soup.get_text(" ", strip=True)
        for pattern in [
            r"スキ\s*([0-9,]+)",
            r"([0-9,]+)\s*スキ",
        ]:
            m = re.search(pattern, text)
            if m:
                likes = int(m.group(1).replace(",", ""))
                break

    # 本文: article優先。DBには保存しない。
    article = soup.find("article")

    if article:
        body = article.get_text("\n", strip=True)
    else:
        # noteはmain配下に本文があるケースがある
        main = soup.find("main")
        body = main.get_text("\n", strip=True) if main else ""

    # ヘッダー等しか取れない場合に、JSON内本文候補も探す
    if len(body) < 300:
        for data in _json_candidates(soup):
            v = _first_recursive(
                data,
                {"body", "bodyText", "body_text", "content", "noteBody"}
            )
            if isinstance(v, str) and len(v) > len(body):
                # HTML本文ならタグを落とす
                body = BeautifulSoup(v, "html.parser").get_text("\n", strip=True)
                if len(body) >= 300:
                    break

    return {
        "url": url,
        "title": title[:500],
        "author": author[:200],
        "published_at": published,
        "likes": likes,
        "body": body[:50000],
    }


def is_recent(published_at: str | None, days: int = 30) -> bool:
    if not published_at:
        # 日付取得不能を即除外すると全滅するため暫定的に残す。
        return True

    try:
        s = str(published_at).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= datetime.now(timezone.utc) - timedelta(days=days)
    except Exception:
        return True


def collect(tag: str, days: int = 30, max_articles: int = 60):
    urls = discover_article_urls(tag, max_articles=max_articles)

    transient = []
    skipped_cooldown = 0
    fetch_errors = 0

    for url in urls:
        try:
            html = get(url)
            if html is None:
                skipped_cooldown += 1
                continue

            article = extract_article(html, url)

            if is_recent(article.get("published_at"), days):
                transient.append(article)

        except Exception:
            # 1記事の失敗で全体分析を止めない
            fetch_errors += 1
            continue

    like_values = [
        a["likes"] for a in transient
        if isinstance(a.get("likes"), int)
    ]
    median = statistics.median(like_values) if like_values else 0
    threshold = max(30, median)

    qualified = []

    for a in transient:
        qualifies = (
            isinstance(a.get("likes"), int)
            and a["likes"] >= threshold
        )

        upsert_article({
            "url": a["url"],
            "tag": tag,
            "title": a.get("title"),
            "author": a.get("author"),
            "published_at": a.get("published_at"),
            "likes": a.get("likes"),
            "qualifies": qualifies,
        })

        if qualifies:
            qualified.append(a)

    return {
        "tag": tag,
        "discovered_urls": len(urls),
        "found": len(transient),
        "likes_count": len(like_values),
        "median_likes": median,
        "threshold": threshold,
        "qualified": qualified,
        "skipped_cooldown": skipped_cooldown,
        "fetch_errors": fetch_errors,
    }
