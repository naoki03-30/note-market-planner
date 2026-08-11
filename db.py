import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.getenv("NOTE_DB_PATH", "note_market_planner.db")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS fetch_log (
    url TEXT PRIMARY KEY,
    last_fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_meta (
    url TEXT PRIMARY KEY,
    tag TEXT NOT NULL,
    title TEXT,
    author TEXT,
    published_at TEXT,
    likes INTEGER,
    collected_at TEXT NOT NULL,
    qualifies INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    tag TEXT NOT NULL,
    total_score INTEGER NOT NULL,
    scores_json TEXT NOT NULL,
    pattern_name TEXT NOT NULL,
    abstract_knowledge TEXT NOT NULL,
    signals_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag TEXT NOT NULL,
    audience TEXT NOT NULL,
    theme TEXT NOT NULL,
    title TEXT NOT NULL,
    core_message TEXT NOT NULL,
    outline_json TEXT NOT NULL,
    pattern_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_url TEXT,
    likes INTEGER,
    sales_count INTEGER,
    revenue_yen INTEGER,
    checked_at TEXT
);

CREATE TABLE IF NOT EXISTS generated_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    first_pass TEXT NOT NULL,
    final_pass TEXT NOT NULL,
    experiences_json TEXT NOT NULL,
    market_patterns_json TEXT NOT NULL,
    target_chars INTEGER NOT NULL,
    paid_boundary TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(plan_id) REFERENCES plans(id)
);
"""

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con

def last_fetch(url):
    with connect() as con:
        row = con.execute("SELECT last_fetched_at FROM fetch_log WHERE url=?", (url,)).fetchone()
        return row["last_fetched_at"] if row else None

def mark_fetch(url):
    with connect() as con:
        con.execute("""
            INSERT INTO fetch_log(url,last_fetched_at) VALUES(?,?)
            ON CONFLICT(url) DO UPDATE SET last_fetched_at=excluded.last_fetched_at
        """, (url, now_iso()))

def upsert_article(meta):
    with connect() as con:
        con.execute("""
            INSERT INTO article_meta(url,tag,title,author,published_at,likes,collected_at,qualifies)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(url) DO UPDATE SET
              tag=excluded.tag,title=excluded.title,author=excluded.author,
              published_at=excluded.published_at,likes=excluded.likes,
              collected_at=excluded.collected_at,qualifies=excluded.qualifies
        """, (
            meta["url"], meta["tag"], meta.get("title"), meta.get("author"),
            meta.get("published_at"), meta.get("likes"), now_iso(),
            int(meta.get("qualifies", False))
        ))

def save_patterns(source_url, tag, total, scores, patterns, signals):
    ids = []
    with connect() as con:
        for p in patterns:
            cur = con.execute("""
                INSERT INTO patterns(
                    source_url,tag,total_score,scores_json,
                    pattern_name,abstract_knowledge,signals_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
            """, (
                source_url, tag, total, json.dumps(scores, ensure_ascii=False),
                p["pattern_name"], p["abstract_knowledge"],
                json.dumps(signals, ensure_ascii=False), now_iso()
            ))
            ids.append(cur.lastrowid)
    return ids

def get_patterns(tag=None, limit=200):
    with connect() as con:
        if tag:
            rows = con.execute(
                "SELECT * FROM patterns WHERE tag=? ORDER BY id DESC LIMIT ?",
                (tag, limit)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM patterns ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

def save_plan(tag, audience, plan, pattern_ids):
    with connect() as con:
        cur = con.execute("""
            INSERT INTO plans(
                tag,audience,theme,title,core_message,outline_json,
                pattern_ids_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?)
        """, (
            tag, audience, plan["theme"], plan["title"], plan["core_message"],
            json.dumps(plan["outline"], ensure_ascii=False),
            json.dumps(pattern_ids, ensure_ascii=False), now_iso()
        ))
        return cur.lastrowid

def list_plans():
    with connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM plans ORDER BY id DESC"
        ).fetchall()]

def record_result(plan_id, published_url, likes, sales_count, revenue_yen):
    with connect() as con:
        con.execute("""
            UPDATE plans SET published_url=?, likes=?, sales_count=?,
                revenue_yen=?, checked_at=? WHERE id=?
        """, (
            published_url, int(likes), int(sales_count), int(revenue_yen),
            now_iso(), int(plan_id)
        ))

def performance_by_pattern():
    with connect() as con:
        rows = [dict(r) for r in con.execute("""
            SELECT id, pattern_ids_json, likes, sales_count, revenue_yen
            FROM plans WHERE likes IS NOT NULL OR revenue_yen IS NOT NULL
        """).fetchall()]
        pats = {r["id"]: dict(r) for r in con.execute("SELECT * FROM patterns").fetchall()}
    agg = {}
    for row in rows:
        for pid in json.loads(row["pattern_ids_json"]):
            a = agg.setdefault(pid, {"uses":0, "likes":0, "sales":0, "revenue":0})
            a["uses"] += 1
            a["likes"] += row.get("likes") or 0
            a["sales"] += row.get("sales_count") or 0
            a["revenue"] += row.get("revenue_yen") or 0
    out = []
    for pid, a in agg.items():
        if pid not in pats:
            continue
        out.append({
            "pattern_id": pid,
            "pattern_name": pats[pid]["pattern_name"],
            "uses": a["uses"],
            "avg_likes": round(a["likes"]/a["uses"], 1),
            "total_sales": a["sales"],
            "total_revenue_yen": a["revenue"]
        })
    return sorted(out, key=lambda x: (x["total_revenue_yen"], x["avg_likes"]), reverse=True)

def export_all():
    with connect() as con:
        result = {}
        for table in ["article_meta","patterns","plans"]:
            result[table] = [dict(r) for r in con.execute(f"SELECT * FROM {table}").fetchall()]
        return result


def save_generated_article(plan_id, first_pass, final_pass, experiences, market_patterns, target_chars, paid_boundary):
    with connect() as con:
        cur = con.execute("""
            INSERT INTO generated_articles(
                plan_id,first_pass,final_pass,experiences_json,
                market_patterns_json,target_chars,paid_boundary,created_at
            ) VALUES(?,?,?,?,?,?,?,?)
        """, (
            int(plan_id), first_pass, final_pass,
            json.dumps(experiences, ensure_ascii=False),
            json.dumps(market_patterns, ensure_ascii=False),
            int(target_chars), paid_boundary, now_iso()
        ))
        return cur.lastrowid

def list_generated_articles(limit=50):
    with connect() as con:
        rows = con.execute("""
            SELECT g.*, p.title, p.theme
            FROM generated_articles g
            JOIN plans p ON p.id=g.plan_id
            ORDER BY g.id DESC
            LIMIT ?
        """, (int(limit),)).fetchall()
        return [dict(r) for r in rows]
