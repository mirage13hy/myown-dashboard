import time
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors.common import (
    is_noise_post,
    load_previous_posts,
    make_client,
    make_post_id,
    merge_posts,
    now_kst_str,
    save_json,
)
from collectors.community_hot import _fetch_detail


def _classify_game_post(title: str, default_cat: str) -> str:
    t = title.lower()
    if any(k in t for k in ("듀얼센스", "psvr", "포탈", "주변기기", "컨트롤러", "헤드셋", "모니터", "ssd", "그래픽카드", "예약판매", "예판", "특가", "할인", "세일", "무료")):
        if any(k in t for k in ("할인", "세일", "특가", "무료", "예판", "예약판매", "최저가")):
            return "할인·예판"
        return "주변기기·하드웨어"
    if any(k in t for k in ("ps5", "ps4", "플스", "플레이스테이션", "psn", "소니")):
        return "PlayStation"
    if any(k in t for k in ("스팀", "steam", "pc", "에픽", "gog")):
        return "PC·스팀"
    return default_cat


def _scrape_ruliweb(client, url: str, source_name: str, default_cat: str, limit: int = 10) -> list[dict[str, Any]]:
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    for row in soup.select("tr.table_body:not(.notice)"):
        a = row.select_one("a.deco")
        if not a:
            continue
        title = a.get_text(strip=True)
        if not title or is_noise_post(title):
            continue
        href = urljoin(url, a.get("href", ""))
        writer_el = row.select_one("td.writer")
        time_el = row.select_one("td.time")
        rec_el = row.select_one("td.recomd")
        author = writer_el.get_text(strip=True) if writer_el else ""
        t_str = time_el.get_text(strip=True) if time_el else ""
        likes = rec_el.get_text(strip=True) if rec_el else ""

        content, imgs = _fetch_detail(client, href, ["div.view_content", "article.view_content"])
        posts.append({
            "id": make_post_id("ruli", href),
            "source": source_name,
            "category": _classify_game_post(title, default_cat),
            "title": title,
            "url": href,
            "author": author,
            "time": t_str,
            "likes": likes,
            "comments": "",
            "content": content,
            "images": imgs,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.15)
    return posts


def run() -> dict[str, Any]:
    targets = [
        ("루리웹 예판·핫딜", "https://bbs.ruliweb.com/market/board/1020", "할인·예판"),
        ("루리웹 콘솔뉴스", "https://bbs.ruliweb.com/news/board/1001", "PlayStation"),
        ("루리웹 PC·스팀", "https://bbs.ruliweb.com/news/board/1003", "PC·스팀"),
    ]

    prev_by_source = load_previous_posts("games.json")
    all_posts: list[dict[str, Any]] = []
    source_status: dict[str, str] = {}

    with make_client() as client:
        for name, url, default_cat in targets:
            try:
                items = _scrape_ruliweb(client, url, name, default_cat, limit=10)
                all_posts.extend(items)
                source_status[name] = f"ok ({len(items)})"
            except Exception as exc:
                cached = prev_by_source.get(name, [])
                if cached:
                    all_posts.extend(cached)
                    source_status[name] = f"cached ({len(cached)}, {type(exc).__name__})"
                else:
                    source_status[name] = f"error: {type(exc).__name__}"

    merged = merge_posts(all_posts, prev_by_source, max_total=120)
    payload = {
        "updated_at": now_kst_str(),
        "source_status": source_status,
        "posts": merged,
    }
    save_json("games.json", payload)
    return payload
