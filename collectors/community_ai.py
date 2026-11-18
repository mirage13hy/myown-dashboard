import re
import time
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors.common import is_noise_post, load_previous_posts, make_client, make_post_id, merge_posts, now_kst_str, save_json
from collectors.community_hot import _extract_clien_time, _fetch_detail_with_time

AI_KEYWORDS = (
    "ai", "gpt", "chatgpt", "챗gpt", "제미나이", "gemini", "클로드", "claude",
    "llm", "로컬", "오픈소스", "인공지능", "딥시크", "deepseek", "엔비디아",
    "에이전트", "바이브코딩", "코파일럿", "소라", "미드저니", "스테이블",
)


def _classify_ai_post(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ("게임", "만들", "자작", "제작", "배포", "프로젝트", "앱", "웹")):
        return "자작·프로젝트"
    if any(k in t for k in ("프롬프트", "활용", "방법", "팁", "가이드", "세팅", "설치", "추천")):
        return "활용법·팁"
    return "화제·뉴스"


def _has_ai_keyword(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in AI_KEYWORDS)


def _scrape_dc_mgallery(client, gall_id: str, source_name: str, limit: int = 8) -> list[dict[str, Any]]:
    url = f"https://gall.dcinside.com/mgallery/board/lists/?id={gall_id}&exception_mode=recommend"
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    for row in soup.select("tr.ub-content"):
        num_el = row.select_one("td.gall_num")
        if not num_el or not num_el.get_text(strip=True).isdigit():
            continue
        if row.select_one("td.gall_notice") or "notice" in " ".join(row.get("class", [])):
            continue
        a = row.select_one("td.gall_tit a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = urljoin(url, a.get("href", ""))
        author_el = row.select_one("td.gall_writer")
        author = author_el.get_text(strip=True) if author_el else ""
        t_el = row.select_one("td.gall_date")
        t_str = (t_el.get("title") or t_el.get_text(strip=True)) if t_el else ""
        if is_noise_post(title, author, t_str):
            continue

        rec_el = row.select_one("td.gall_recommend")
        cmt_el = row.select_one("span.reply_num")
        content, imgs, detail_t = _fetch_detail_with_time(client, href, ["div.write_div"])
        posts.append({
            "id": make_post_id(gall_id, href),
            "source": source_name,
            "category": _classify_ai_post(title),
            "title": title,
            "url": href,
            "author": author,
            "time": t_str or detail_t,
            "likes": rec_el.get_text(strip=True) if rec_el else "",
            "comments": re.sub(r"[\[\]]", "", cmt_el.get_text(strip=True)) if cmt_el else "",
            "content": content,
            "images": imgs,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.2)
    return posts


def _scrape_clien_board(client, board_path: str, source_name: str, filter_ai: bool, limit: int = 8) -> list[dict[str, Any]]:
    url = f"https://www.clien.net/service/board/{board_path}"
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    for row in soup.select("div.list_item.symph_row"):
        if "notice" in " ".join(row.get("class", [])):
            continue
        a = row.select_one("a.list_subject span.subject_fixed")
        link_el = row.select_one("a.list_subject")
        if not a or not link_el:
            continue
        title = a.get_text(strip=True)
        if filter_ai and not _has_ai_keyword(title):
            continue
        if is_noise_post(title):
            continue
        href = urljoin(url, link_el.get("href", ""))
        t_str = _extract_clien_time(row)
        like_el = row.select_one("div.list_symph span")
        cmt_el = row.select_one("span.rSymph05")
        content, imgs, detail_t = _fetch_detail_with_time(client, href, ["div.post_article"])
        posts.append({
            "id": make_post_id(board_path, href),
            "source": source_name,
            "category": _classify_ai_post(title),
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
        time.sleep(0.2)
    return posts


def _scrape_fmkorea_board(client, url: str, source_name: str, filter_ai: bool, limit: int = 8) -> list[dict[str, Any]]:
    time.sleep(1.5)
    resp = client.get(url, headers={"Referer": "https://www.fmkorea.com/"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    for row in soup.select("table.bd_lst tbody tr"):
        if "notice" in " ".join(row.get("class", [])) or row.select_one("td.notice"):
            continue
        a = row.select_one("td.title a:not(.replyNum)")
        if not a:
            continue
        title = a.get_text(strip=True)
        if not title or (filter_ai and not _has_ai_keyword(title)) or is_noise_post(title):
            continue
        href = urljoin(url, a.get("href", ""))
        t_el = row.select_one("td.time, span.regdate")
        t_str = t_el.get_text(strip=True) if t_el else ""
        content, imgs, detail_t = _fetch_detail_with_time(client, href, ["div.rd_body article", "div.xe_content"])
        posts.append({
            "id": make_post_id(source_name, href),
            "source": source_name,
            "category": _classify_ai_post(title),
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
        time.sleep(0.2)
    return posts


def _scrape_ruliweb_ai(client, limit: int = 6) -> list[dict[str, Any]]:
    url = "https://bbs.ruliweb.com/news/board/1003"
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    for row in soup.select("tr.table_body:not(.notice)"):
        a = row.select_one("a.deco")
        if not a:
            continue
        title = a.get_text(strip=True)
        if not title or not _has_ai_keyword(title) or is_noise_post(title):
            continue
        href = urljoin(url, a.get("href", ""))
        time_el = row.select_one("td.time")
        t_str = time_el.get_text(strip=True) if time_el else ""
        content, imgs, detail_t = _fetch_detail_with_time(client, href, ["div.view_content", "article.view_content"])
        posts.append({
            "id": make_post_id("ruli_ai", href),
            "source": "루리웹 IT·AI",
            "category": _classify_ai_post(title),
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


def _scrape_ppomppu_ai(client, limit: int = 6) -> list[dict[str, Any]]:
    url = "https://www.ppomppu.co.kr/hot.php"
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        if "view.php" not in a["href"]:
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 3 or not _has_ai_keyword(title) or is_noise_post(title):
            continue
        href = urljoin(url, a["href"])
        if href in seen:
            continue
        seen.add(href)
        content, imgs, detail_t = _fetch_detail_with_time(client, href, ["td.board-contents", "div.board-contents"])
        posts.append({
            "id": make_post_id("ppom_ai", href),
            "source": "뽐뿌 AI",
            "category": _classify_ai_post(title),
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


def run() -> dict[str, Any]:
    targets = [
        ("디시 특이점이온다", lambda c: _scrape_dc_mgallery(c, "thesingularity", "디시 특이점이온다", 8)),
        ("에펨코리아 AI", lambda c: _scrape_fmkorea_board(c, "https://www.fmkorea.com/ai", "에펨코리아 AI", False, 8)),
        ("에펨코리아 디지털(AI)", lambda c: _scrape_fmkorea_board(c, "https://www.fmkorea.com/?mid=digital", "에펨코리아 디지털", True, 6)),
        ("클리앙 AI당", lambda c: _scrape_clien_board(c, "cm_ai", "클리앙 AI당", False, 6)),
        ("클리앙 새소식(AI)", lambda c: _scrape_clien_board(c, "news", "클리앙 새소식", True, 6)),
        ("루리웹 IT·AI", _scrape_ruliweb_ai),
        ("뽐뿌 AI", _scrape_ppomppu_ai),
    ]

    prev_by_source = load_previous_posts("community_ai.json")
    all_posts: list[dict[str, Any]] = []
    source_status: dict[str, str] = {}

    with make_client() as client:
        for name, fn in targets:
            try:
                items = fn(client)
                all_posts.extend(items)
                source_status[name] = f"ok ({len(items)})"
            except Exception as exc:
                src_label = name.split("(")[0].strip()
                cached = prev_by_source.get(name, []) or prev_by_source.get(src_label, [])
                if cached:
                    all_posts.extend(cached)
                    source_status[name] = f"cached ({len(cached)}, {type(exc).__name__})"
                else:
                    source_status[name] = f"error: {type(exc).__name__}"

    merged_posts = merge_posts(all_posts, prev_by_source, max_total=100)
    payload = {
        "updated_at": now_kst_str(),
        "source_status": source_status,
        "posts": merged_posts,
    }
    save_json("community_ai.json", payload)
    return payload
