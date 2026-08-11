import json
import os
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import quote, urljoin

import feedparser
import httpx
from bs4 import BeautifulSoup

from db import last_fetch, mark_fetch, upsert_article

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
    "Mobile/15E148 Safari/604.1"
)
INTERVAL = float(os.getenv("REQUEST_INTERVAL_SECONDS", "1.5"))
COOLDOWN_HOURS = float(os.getenv("SAME_URL_COOLDOWN_HOURS", "6"))

ARTICLE_RE = re.compile(
    r"https?://(?:[A-Za-z0-9-]+\.)?note\.com/[^/\s\"'<>]+/n/n[A-Za-z0-9_-]+"
)

def _clean_url(raw):
    if not raw:
        return None
    s = unescape(str(raw)).replace("\\/", "/").replace("\\u002F", "/").replace("\\u003A", ":")
    if s.startswith("/"):
        s = urljoin("https://note.com", s)
    m = ARTICLE_RE.search(s)
    return m.group(0).split("?")[0].split("#")[0] if m else None

def _is_article(url):
    return bool(url and ARTICLE_RE.match(url))

def can_fetch(url):
    if not _is_article(url):
        return True
    last = last_fetch(url)
    if not last:
        return True
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(last) >= timedelta(hours=COOLDOWN_HOURS)
    except Exception:
        return True

def _client():
    return httpx.Client(
        headers={
            "User-Agent": UA,
            "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
        follow_redirects=True,
        timeout=httpx.Timeout(20.0, connect=8.0),
    )

def get(url, article_log=True):
    if article_log and _is_article(url) and not can_fetch(url):
        return None
    time.sleep(INTERVAL)
    with _client() as c:
        r = c.get(url)
        r.raise_for_status()
    if article_log and _is_article(url):
        mark_fetch(url)
    return r.text

def rss_urls(tag):
    encoded = quote(tag, safe="")
    return [
        f"https://note.com/hashtag/{encoded}/rss",
        f"https://note.com/hashtag/{encoded}?f=new&output=rss",
    ]

def tag_url(tag):
    return f"https://note.com/hashtag/{quote(tag, safe='')}?f=new"

def discover_from_rss(tag, max_articles=60):
    diagnostics = []
    for url in rss_urls(tag):
        try:
            text = get(url, article_log=False)
            feed = feedparser.loads(text)
            urls = []
            for entry in getattr(feed, "entries", []):
                for candidate in [
                    getattr(entry, "link", None),
                    getattr(entry, "id", None),
                ]:
                    u = _clean_url(candidate)
                    if u and u not in urls:
                        urls.append(u)
                for link in getattr(entry, "links", []) or []:
                    if isinstance(link, dict):
                        u = _clean_url(link.get("href"))
                        if u and u not in urls:
                            urls.append(u)
                if len(urls) >= max_articles:
                    break

            diagnostics.append({
                "method": "rss",
                "url": url,
                "http_ok": True,
                "feed_entries": len(getattr(feed, "entries", [])),
                "urls": len(urls),
                "bozo": bool(getattr(feed, "bozo", False)),
            })
            if urls:
                return urls[:max_articles], diagnostics
        except Exception as e:
            diagnostics.append({
                "method":"rss","url":url,"http_ok":False,
                "feed_entries":0,"urls":0,"error":str(e)[:160]
            })
    return [], diagnostics

def discover_from_html(tag, max_articles=60):
    url = tag_url(tag)
    try:
        html = get(url, article_log=False)
    except Exception as e:
        return [], [{"method":"html","url":url,"http_ok":False,"urls":0,"error":str(e)[:160]}]

    soup = BeautifulSoup(html, "html.parser")
    urls = []

    def add(x):
        u = _clean_url(x)
        if u and u not in urls:
            urls.append(u)

    for a in soup.find_all("a", href=True):
        add(a["href"])
        if len(urls) >= max_articles:
            break

    raw = unescape(html).replace("\\/", "/").replace("\\u002F", "/").replace("\\u003A", ":")
    if len(urls) < max_articles:
        for m in ARTICLE_RE.finditer(raw):
            add(m.group(0))
            if len(urls) >= max_articles:
                break

    diag = [{
        "method":"html","url":url,"http_ok":True,"html_chars":len(html),
        "anchor_count":len(soup.find_all("a")),"urls":len(urls)
    }]
    return urls[:max_articles], diag

def discover_article_urls(tag, max_articles=60):
    # 1. RSS優先
    urls, diag = discover_from_rss(tag, max_articles)
    if urls:
        return urls, "RSS", diag

    # 2. HTML fallback
    urls2, diag2 = discover_from_html(tag, max_articles)
    diag.extend(diag2)
    if urls2:
        return urls2, "HTML", diag

    return [], "NONE", diag

def _walk(obj):
    if isinstance(obj, dict):
        for k,v in obj.items():
            yield k,v
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)

def _find_value(data, names):
    names = {n.lower() for n in names}
    for k,v in _walk(data):
        if str(k).lower() in names and v not in (None, ""):
            return v
    return None

def _json_blocks(soup):
    for s in soup.find_all("script"):
        txt = s.string or s.get_text()
        if not txt:
            continue
        if s.get("type") in ("application/json","application/ld+json") or s.get("id") == "__NEXT_DATA__" or txt.lstrip().startswith(("{","[")):
            try:
                yield json.loads(txt.strip())
            except Exception:
                pass

def extract_article(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    author = ""
    published = None
    likes = None

    for data in _json_blocks(soup):
        if not title:
            v = _find_value(data, {"headline","title"})
            if isinstance(v, str):
                title = v
        if not published:
            v = _find_value(data, {"datePublished","publishAt","publishedAt","publish_at"})
            if isinstance(v, str):
                published = v
        if likes is None:
            v = _find_value(data, {"likeCount","likesCount","like_count","likes_count"})
            if isinstance(v, (int,float)):
                likes = int(v)
            elif isinstance(v, str) and v.replace(",","").isdigit():
                likes = int(v.replace(",",""))
        if not author:
            v = _find_value(data, {"nickname","displayName","authorName"})
            if isinstance(v, str):
                author = v

    if not title:
        m = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name":"twitter:title"})
        if m:
            title = m.get("content") or ""

    if not published:
        m = soup.find("meta", property="article:published_time") or soup.find("time", attrs={"datetime":True})
        if m:
            published = m.get("content") or m.get("datetime")

    if likes is None:
        raw = html.replace("\\/", "/")
        for p in [
            r'"likeCount"\s*:\s*(\d+)',
            r'"likesCount"\s*:\s*(\d+)',
            r'"like_count"\s*:\s*(\d+)',
            r'"likes_count"\s*:\s*(\d+)',
        ]:
            m = re.search(p, raw)
            if m:
                likes = int(m.group(1))
                break

    if likes is None:
        text = soup.get_text(" ", strip=True)
        for p in [r"スキ\s*([0-9,]+)", r"([0-9,]+)\s*スキ"]:
            m = re.search(p, text)
            if m:
                likes = int(m.group(1).replace(",",""))
                break

    article = soup.find("article") or soup.find("main")
    body = article.get_text("\n", strip=True) if article else ""

    return {
        "url":url,
        "title":title[:500],
        "author":author[:200],
        "published_at":published,
        "likes":likes,
        "body":body[:50000],
    }

def is_recent(published_at, days=30):
    if not published_at:
        return True
    try:
        dt = datetime.fromisoformat(str(published_at).replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= datetime.now(timezone.utc)-timedelta(days=days)
    except Exception:
        return True

def connection_test(tag):
    urls, method, diagnostics = discover_article_urls(tag, max_articles=5)
    result = {
        "method": method,
        "urls": len(urls),
        "likes_ok": 0,
        "article_ok": 0,
        "sample": [],
        "diagnostics": diagnostics,
    }
    for url in urls[:3]:
        try:
            html = get(url)
            if html is None:
                continue
            a = extract_article(html, url)
            result["article_ok"] += 1
            if isinstance(a.get("likes"), int):
                result["likes_ok"] += 1
            result["sample"].append({
                "title":a.get("title","")[:80],
                "likes":a.get("likes"),
                "url":url
            })
        except Exception as e:
            result["sample"].append({"url":url,"error":str(e)[:120]})
    return result

def collect(tag, days=30, max_articles=60):
    urls, method, diagnostics = discover_article_urls(tag, max_articles=max_articles)

    transient = []
    skipped = 0
    errors = 0

    for url in urls:
        try:
            html = get(url)
            if html is None:
                skipped += 1
                continue
            a = extract_article(html, url)
            if is_recent(a.get("published_at"), days):
                transient.append(a)
        except Exception:
            errors += 1

    like_values = [a["likes"] for a in transient if isinstance(a.get("likes"), int)]
    median = statistics.median(like_values) if like_values else 0
    threshold = max(30, median)

    qualified = []
    for a in transient:
        q = isinstance(a.get("likes"), int) and a["likes"] >= threshold
        upsert_article({
            "url":a["url"],"tag":tag,"title":a.get("title"),
            "author":a.get("author"),"published_at":a.get("published_at"),
            "likes":a.get("likes"),"qualifies":q
        })
        if q:
            qualified.append(a)

    return {
        "tag":tag,
        "method":method,
        "discovered_urls":len(urls),
        "found":len(transient),
        "likes_count":len(like_values),
        "median_likes":median,
        "threshold":threshold,
        "qualified":qualified,
        "skipped_cooldown":skipped,
        "fetch_errors":errors,
        "diagnostics":diagnostics,
    }
