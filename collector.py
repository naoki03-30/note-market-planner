import json
import os
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup

from db import last_fetch, mark_fetch, upsert_article

UA = "Mozilla/5.0 (compatible; NoteMarketPlanner/1.0; personal-research)"
INTERVAL = float(os.getenv("REQUEST_INTERVAL_SECONDS", "2.5"))
COOLDOWN_HOURS = float(os.getenv("SAME_URL_COOLDOWN_HOURS", "6"))

def can_fetch(url):
    last = last_fetch(url)
    if not last:
        return True
    dt = datetime.fromisoformat(last)
    return datetime.now(timezone.utc) - dt >= timedelta(hours=COOLDOWN_HOURS)

def get(url):
    if not can_fetch(url):
        return None
    time.sleep(INTERVAL)
    with httpx.Client(
        headers={"User-Agent": UA},
        follow_redirects=True,
        timeout=20.0
    ) as client:
        r = client.get(url)
        r.raise_for_status()
    mark_fetch(url)
    return r.text

def tag_url(tag):
    return f"https://note.com/hashtag/{quote(tag)}?f=new"

def discover_article_urls(tag, max_articles=60):
    html = get(tag_url(tag))
    if html is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        full = urljoin("https://note.com", a["href"]).split("?")[0].split("#")[0]
        if re.match(r"^https://(?:[^.]+\.)?note\.com/[^/]+/n/n[a-zA-Z0-9_-]+$", full):
            if full not in urls:
                urls.append(full)
        if len(urls) >= max_articles:
            break
    return urls

def _jsonld(soup):
    for script in soup.find_all("script", attrs={"type":"application/ld+json"}):
        try:
            x = json.loads(script.get_text(strip=True))
            if isinstance(x, dict):
                yield x
            elif isinstance(x, list):
                for i in x:
                    if isinstance(i, dict):
                        yield i
        except Exception:
            pass

def extract_article(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title = author = published = None
    for d in _jsonld(soup):
        if d.get("@type") in ("Article","BlogPosting","NewsArticle"):
            title = d.get("headline") or title
            published = d.get("datePublished") or published
            au = d.get("author")
            if isinstance(au, dict):
                author = au.get("name") or author

    if not title:
        m = soup.find("meta", property="og:title")
        title = m.get("content") if m else None

    likes = None
    for pattern in [
        r'"likeCount"\s*:\s*(\d+)',
        r'"likesCount"\s*:\s*(\d+)',
        r'"like_count"\s*:\s*(\d+)',
        r'"like_count":(\d+)'
    ]:
        m = re.search(pattern, html)
        if m:
            likes = int(m.group(1))
            break

    if likes is None:
        txt = soup.get_text(" ", strip=True)
        for pattern in [r"スキ\s*([0-9,]+)", r"([0-9,]+)\s*スキ"]:
            m = re.search(pattern, txt)
            if m:
                likes = int(m.group(1).replace(",",""))
                break

    article = soup.find("article") or soup.find("main")
    body = article.get_text("\n", strip=True) if article else ""

    return {
        "url": url,
        "title": title or "",
        "author": author or "",
        "published_at": published,
        "likes": likes,
        # 本文は分析時にのみメモリ上で使い、DBには保存しない。
        "body": body[:50000]
    }

def is_recent(dt, days=30):
    if not dt:
        return True
    try:
        x = datetime.fromisoformat(dt.replace("Z","+00:00"))
        if x.tzinfo is None:
            x = x.replace(tzinfo=timezone.utc)
        return x >= datetime.now(timezone.utc)-timedelta(days=days)
    except Exception:
        return True

def collect(tag, days=30, max_articles=60):
    transient = []
    for url in discover_article_urls(tag, max_articles):
        html = get(url)
        if html is None:
            continue
        a = extract_article(html, url)
        if is_recent(a.get("published_at"), days):
            transient.append(a)

    likes = [a["likes"] for a in transient if isinstance(a.get("likes"), int)]
    median = statistics.median(likes) if likes else 0
    threshold = max(30, median)

    qualified = []
    for a in transient:
        q = isinstance(a.get("likes"), int) and a["likes"] >= threshold
        upsert_article({
            "url": a["url"], "tag": tag, "title": a["title"],
            "author": a["author"], "published_at": a["published_at"],
            "likes": a["likes"], "qualifies": q
        })
        if q:
            qualified.append(a)

    return {
        "tag": tag,
        "found": len(transient),
        "likes_count": len(likes),
        "median_likes": median,
        "threshold": threshold,
        "qualified": qualified
    }
