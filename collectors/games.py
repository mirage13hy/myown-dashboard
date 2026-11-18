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
from collectors.community_hot import _extract_clien_time, _fetch_detail_with_time

GAME_DEAL_KEYWORDS = (
    "게임", "스팀", "steam", "닌텐도", "스위치", "플스", "ps5", "ps4", "psn",
    "엑스박스", "xbox", "컨트롤러", "게임패드", "듀얼센스", "에픽게임즈", "에픽 모바일",
    "gog", "로블록스", "psvr", "플레이스테이션",
)


def _is_game_deal(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in GAME_DEAL_KEYWORDS)


def _classify_game_post(title: str, default_cat: str) -> str:
    t = title.lower()
    if any(k in t for k in ("듀얼센스", "psvr", "포탈", "주변기기", "컨트롤러", "게임패드", "헤드셋", "모니터", "ssd", "그래픽카드", "예약판매", "예판", "특가", "할인", "세일", "무료")):
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

        content, imgs, detail_t = _fetch_detail_with_time(client, href, ["div.view_content", "article.view_content"])
        posts.append({
            "id": make_post_id("ruli", href),
            "source": source_name,
            "category": _classify_game_post(title, default_cat),
            "title": title,
            "url": href,
            "author": author,
            "time": t_str or detail_t,
            "likes": likes,
            "comments": "",
            "content": content,
            "images": imgs,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.15)
    return posts


def _scrape_fm_game_deals(client, limit: int = 10) -> list[dict[str, Any]]:
    url = "https://www.fmkorea.com/?mid=hotdeal"
    time.sleep(1.0)
    resp = client.get(url, headers={"Referer": "https://www.fmkorea.com/"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    for item in soup.select("li.li_best2_pop0, div.fm_best_widget ul li, table.bd_lst tbody tr"):
        if "notice" in " ".join(item.get("class", [])):
            continue
        a = item.select_one("h3.title a, td.title a:not(.replyNum), a.hotdeal_var8")
        if not a:
            continue
        title = a.get_text(strip=True)
        if not title or is_noise_post(title) or not _is_game_deal(title):
            continue
        href = urljoin(url, a.get("href", ""))
        t_el = item.select_one("span.regdate, td.time")
        t_str = t_el.get_text(strip=True) if t_el else ""
        content, imgs, detail_t = _fetch_detail_with_time(client, href, ["div.rd_body article", "div.xe_content"])
        posts.append({
            "id": make_post_id("fm_game", href),
            "source": "에펨코리아 핫딜",
            "category": "할인·예판",
            "title": title,
            "url": href,
            "author": "",
            "time": t_str or detail_t,
            "likes": "",
            "comments": "",
            "content": content,
            "images": imgs,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.15)
    return posts


def _scrape_ppomppu_game_deals(client, limit: int = 10) -> list[dict[str, Any]]:
    url = "https://www.ppomppu.co.kr/zboard/zboard.php?id=ppomppu"
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href_raw = a["href"]
        if "view.php" not in href_raw or "id=ppomppu" not in href_raw:
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 3 or is_noise_post(title) or not _is_game_deal(title):
            continue
        href = urljoin(url, href_raw)
        if href in seen:
            continue
        seen.add(href)
        content, imgs, detail_t = _fetch_detail_with_time(client, href, ["td.board-contents", "div.board-contents"])
        posts.append({
            "id": make_post_id("ppom_game", href),
            "source": "뽐뿌 핫딜",
            "category": "할인·예판",
            "title": title,
            "url": href,
            "author": "",
            "time": detail_t,
            "likes": "",
            "comments": "",
            "content": content,
            "images": imgs,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.15)
    return posts


def _scrape_clien_game_deals(client, limit: int = 10) -> list[dict[str, Any]]:
    url = "https://www.clien.net/service/board/jirum"
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    for row in soup.select("div.list_item.symph_row"):
        if "notice" in " ".join(row.get("class", [])):
            continue
        a = row.select_one("a.list_subject span.subject_fixed, span.list_subject a")
        link_el = row.select_one("a.list_subject") or a
        if not a or not link_el:
            continue
        title = a.get_text(strip=True)
        if not title or is_noise_post(title) or not _is_game_deal(title):
            continue
        href = urljoin(url, link_el.get("href", ""))
        t_str = _extract_clien_time(row)
        like_el = row.select_one("div.list_symph span")
        cmt_el = row.select_one("span.rSymph05")
        content, imgs, detail_t = _fetch_detail_with_time(client, href, ["div.post_article"])
        posts.append({
            "id": make_post_id("clien_game", href),
            "source": "클리앙 알뜰구매",
            "category": "할인·예판",
            "title": title,
            "url": href,
            "author": "",
            "time": t_str or detail_t,
            "likes": like_el.get_text(strip=True) if like_el else "",
            "comments": cmt_el.get_text(strip=True) if cmt_el else "",
            "content": content,
            "images": imgs,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.15)
    return posts


def run() -> dict[str, Any]:
    targets = [
        ("루리웹 예판·핫딜", lambda c: _scrape_ruliweb(c, "https://bbs.ruliweb.com/market/board/1020", "루리웹 예판·핫딜", "할인·예판", 10)),
        ("루리웹 콘솔뉴스", lambda c: _scrape_ruliweb(c, "https://bbs.ruliweb.com/news/board/1001", "루리웹 콘솔뉴스", "PlayStation", 10)),
        ("루리웹 PC·스팀", lambda c: _scrape_ruliweb(c, "https://bbs.ruliweb.com/news/board/1003", "루리웹 PC·스팀", "PC·스팀", 10)),
        ("에펨코리아 핫딜", _scrape_fm_game_deals),
        ("뽐뿌 핫딜", _scrape_ppomppu_game_deals),
        ("클리앙 알뜰구매", _scrape_clien_game_deals),
    ]

    prev_by_source = load_previous_posts("games.json")
    all_posts: list[dict[str, Any]] = []
    source_status: dict[str, str] = {}

    with make_client() as client:
        for name, fn in targets:
            try:
                items = fn(client)
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
