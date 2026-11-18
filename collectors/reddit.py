import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import feedparser
import httpx
from bs4 import BeautifulSoup

from collectors.common import (
    DATA_DIR,
    clean_text,
    load_previous_posts,
    make_post_id,
    merge_posts,
    now_kst_str,
    save_json,
)

KST = timezone(timedelta(hours=9))

REDDIT_HEADERS = {
    "User-Agent": "windows:myown-dashboard:v1.0 (by /u/mirage13hy)",
}

# 시사/정치 대신 일반 시민 화제 + AI/테크 중심 서브레딧
SUBREDDITS = [
    ("AskReddit", "r/AskReddit", "미국·일상 여론", 5),
    ("todayilearned", "r/todayilearned", "글로벌 화제", 5),
    ("mildlyinteresting", "r/mildlyinteresting", "글로벌 화제", 4),
    ("LocalLLaMA", "r/LocalLLaMA", "AI·테크", 6),
    ("artificial", "r/artificial", "AI·테크", 5),
    ("technology", "r/technology", "AI·테크", 5),
]

POLITICAL_NOISE = (
    "trump", "biden", "election", "senate", "congress", "democrat", "republican",
    "parliament", "minister", "vote", "ballot", "gop", "impeach",
)


def _load_translation_cache() -> dict[str, dict[str, str]]:
    cache: dict[str, dict[str, str]] = {}
    path = DATA_DIR / "reddit.json"
    if not path.exists():
        return cache
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        for p in old.get("posts", []):
            if p.get("id") and p.get("translated"):
                cache[p["id"]] = {
                    "title": p.get("title", ""),
                    "content": p.get("content", ""),
                }
    except Exception:
        pass
    return cache


def _translate_to_korean(title: str, body: str) -> tuple[str, str, bool]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return title, body, False

    from google import genai

    client = genai.Client(api_key=api_key)
    snippet = body[:2500] if body else "(본문 없음 — 링크 게시물)"
    prompt = (
        "다음 레딧(Reddit) 게시글의 제목과 본문을 자연스러운 한국어로 번역해 주세요.\n"
        "반드시 아래 JSON 형식으로만 답하세요:\n"
        '{"title_ko": "한국어 제목", "body_ko": "한국어 본문"}\n\n'
        f"원문 제목: {title}\n"
        f"원문 본문:\n{snippet}"
    )

    for model_name in ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite"):
        try:
            resp = client.models.generate_content(model=model_name, contents=prompt)
            raw = (resp.text or "").strip()
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                parsed = json.loads(m.group(0))
                t_ko = (parsed.get("title_ko") or "").strip()
                b_ko = (parsed.get("body_ko") or "").strip()
                if t_ko:
                    return t_ko, b_ko or body, True
        except Exception:
            time.sleep(1.0)
            continue

    return title, body, False


def _fetch_subreddit_arctic(client: httpx.Client, sub: str, limit: int) -> list[dict[str, Any]]:
    now_ts = int(time.time())
    after = now_ts - 86400 * 2
    before = now_ts - 3600 * 4
    url = f"https://arctic-shift.photon-reddit.com/api/posts/search?subreddit={sub}&after={after}&before={before}&limit=60"
    resp = client.get(url)
    resp.raise_for_status()
    rows = resp.json().get("data", [])
    rows = sorted(rows, key=lambda x: x.get("score", 0), reverse=True)

    items = []
    for d in rows:
        if d.get("over_18") or d.get("removed_by_category"):
            continue
        title = (d.get("title") or "").strip()
        if not title:
            continue
        if sub in ("technology", "AskReddit") and any(pk in title.lower() for pk in POLITICAL_NOISE):
            continue
        permalink = f"https://www.reddit.com{d.get('permalink', '')}"
        selftext = clean_text(d.get("selftext") or "")
        if selftext in ("[removed]", "[deleted]"):
            selftext = ""
        ext_url = d.get("url") or ""
        if not selftext and ext_url and "reddit.com" not in ext_url:
            selftext = f"원문 링크: {ext_url}"
        created_utc = d.get("created_utc")
        t_str = (
            datetime.fromtimestamp(created_utc, tz=KST).strftime("%Y-%m-%d %H:%M")
            if created_utc
            else ""
        )
        imgs = []
        if any(ext_url.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
            imgs.append(ext_url)
        items.append({
            "id": make_post_id(f"reddit_{sub}", permalink),
            "title_orig": title,
            "body_orig": selftext,
            "url": permalink,
            "author": d.get("author", ""),
            "time": t_str,
            "likes": d.get("score", ""),
            "comments": d.get("num_comments", ""),
            "images": imgs,
        })
        if len(items) >= limit:
            break
    return items


def _fetch_subreddit_json(client: httpx.Client, sub: str, limit: int) -> list[dict[str, Any]]:
    url = f"https://old.reddit.com/r/{sub}/hot.json?limit={limit + 6}"
    resp = client.get(url)
    resp.raise_for_status()
    data = resp.json()
    children = data.get("data", {}).get("children", [])
    items = []
    for ch in children:
        d = ch.get("data", {})
        if d.get("stickied") or d.get("over_18"):
            continue
        title = (d.get("title") or "").strip()
        if not title:
            continue
        if sub in ("popular", "technology") and any(pk in title.lower() for pk in POLITICAL_NOISE):
            continue
        permalink = f"https://www.reddit.com{d.get('permalink', '')}"
        selftext = clean_text(d.get("selftext") or "")
        ext_url = d.get("url_overridden_by_dest") or ""
        if not selftext and ext_url and "reddit.com" not in ext_url:
            selftext = f"원문 링크: {ext_url}"
        created_utc = d.get("created_utc")
        t_str = (
            datetime.fromtimestamp(created_utc, tz=KST).strftime("%Y-%m-%d %H:%M")
            if created_utc
            else ""
        )
        imgs = []
        thumb = d.get("url") or ""
        if any(thumb.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
            imgs.append(thumb)
        items.append({
            "id": make_post_id(f"reddit_{sub}", permalink),
            "title_orig": title,
            "body_orig": selftext,
            "url": permalink,
            "author": d.get("author", ""),
            "time": t_str,
            "likes": d.get("score", ""),
            "comments": d.get("num_comments", ""),
            "images": imgs,
        })
        if len(items) >= limit:
            break
    return items


def _fetch_subreddit_rss(client: httpx.Client, sub: str, limit: int) -> list[dict[str, Any]]:
    url = f"https://old.reddit.com/r/{sub}/.rss"
    resp = client.get(url)
    resp.raise_for_status()
    feed = feedparser.parse(resp.text)
    items = []
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        if not title:
            continue
        if sub in ("popular", "technology") and any(pk in title.lower() for pk in POLITICAL_NOISE):
            continue
        link = entry.get("link", "")
        raw_html = entry.get("summary", "") or (entry.get("content", [{}])[0].get("value", "") if entry.get("content") else "")
        body = clean_text(BeautifulSoup(raw_html, "lxml").get_text("\n")) if raw_html else ""
        published = entry.get("published", "")[:16].replace("T", " ")
        items.append({
            "id": make_post_id(f"reddit_{sub}", link),
            "title_orig": title,
            "body_orig": body,
            "url": link,
            "author": entry.get("author", ""),
            "time": published,
            "likes": "",
            "comments": "",
            "images": [],
        })
        if len(items) >= limit:
            break
    return items


def run() -> dict[str, Any]:
    trans_cache = _load_translation_cache()
    prev_by_source = load_previous_posts("reddit.json")
    all_posts: list[dict[str, Any]] = []
    source_status: dict[str, str] = {}

    with httpx.Client(headers=REDDIT_HEADERS, timeout=12.0, follow_redirects=True) as client:
        for sub, label, category, limit in SUBREDDITS:
            raw_items: list[dict[str, Any]] = []
            try:
                raw_items = _fetch_subreddit_arctic(client, sub, limit)
                mode = "arctic"
            except Exception:
                try:
                    raw_items = _fetch_subreddit_json(client, sub, limit)
                    mode = "json"
                except Exception as exc:
                    cached = prev_by_source.get(label, [])
                    if cached:
                        all_posts.extend(cached)
                        source_status[label] = f"cached ({len(cached)}, {type(exc).__name__})"
                    else:
                        source_status[label] = f"error: {type(exc).__name__}"
                    continue

            built = []
            for item in raw_items:
                pid = item["id"]
                if pid in trans_cache:
                    t_ko = trans_cache[pid]["title"]
                    b_ko = trans_cache[pid]["content"]
                    translated = True
                else:
                    t_ko, b_ko, translated = _translate_to_korean(item["title_orig"], item["body_orig"])
                    if translated:
                        time.sleep(0.5)

                full_content = (
                    f"{b_ko}\n\n---\n[원문 제목] {item['title_orig']}"
                    if b_ko
                    else f"[원문 제목] {item['title_orig']}"
                )
                built.append({
                    "id": pid,
                    "source": label,
                    "category": category,
                    "title": t_ko,
                    "url": item["url"],
                    "author": item["author"],
                    "time": item["time"],
                    "likes": item["likes"],
                    "comments": item["comments"],
                    "content": full_content,
                    "images": item["images"],
                    "translated": translated,
                })
            all_posts.extend(built)
            source_status[label] = f"ok ({len(built)}, {mode})"
            time.sleep(0.8)

    merged = merge_posts(all_posts, prev_by_source, max_total=120)
    payload = {
        "updated_at": now_kst_str(),
        "source_status": source_status,
        "posts": merged,
    }
    save_json("reddit.json", payload)
    return payload
