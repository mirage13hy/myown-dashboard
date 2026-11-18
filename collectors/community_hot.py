import re
import time
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collectors.common import (
    clean_text,
    detect_cross_topics,
    is_noise_post,
    load_previous_posts,
    make_client,
    make_post_id,
    merge_posts,
    now_kst_str,
    save_json,
)


def _extract_images(container: BeautifulSoup | None, base_url: str, limit: int = 8) -> list[str]:
    if not container:
        return []
    urls: list[str] = []
    for img in container.select("img"):
        src = img.get("data-original") or img.get("data-src") or img.get("src") or ""
        src = src.strip()
        if not src or src.startswith("data:") or "emoticon" in src or "icon" in src.lower():
            continue
        full = urljoin(base_url, src)
        if full not in urls:
            urls.append(full)
        if len(urls) >= limit:
            break
    return urls


def _extract_clien_time(row: BeautifulSoup) -> str:
    ts = row.select_one("span.timestamp")
    if not ts:
        return ""
    raw = ts.get_text(strip=True)
    m = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})", raw)
    return m.group(1) if m else raw[:16]


def _fetch_detail(client, url: str, selectors: list[str]) -> tuple[str, list[str]]:
    try:
        resp = client.get(url)
        if resp.status_code != 200:
            return "", []
        soup = BeautifulSoup(resp.text, "lxml")
        for sel in selectors:
            box = soup.select_one(sel)
            if box:
                for tag in box.select("script, style"):
                    tag.decompose()
                text = clean_text(box.get_text("\n"))
                imgs = _extract_images(box, url)
                return text, imgs
    except Exception:
        pass
    return "", []


def scrape_dcbest(client, limit: int = 10) -> list[dict[str, Any]]:
    url = "https://gall.dcinside.com/board/lists/?id=dcbest"
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
        author = (row.select_one("td.gall_writer") or {}).get_text(strip=True) if row.select_one("td.gall_writer") else ""
        t_el = row.select_one("td.gall_date")
        t_str = t_el.get("title") or t_el.get_text(strip=True) if t_el else ""
        if is_noise_post(title, author, t_str):
            continue
        rec_el = row.select_one("td.gall_recommend")
        likes = rec_el.get_text(strip=True) if rec_el else ""
        cmt_el = row.select_one("span.reply_num")
        cmts = re.sub(r"[\[\]]", "", cmt_el.get_text(strip=True)) if cmt_el else ""

        content, imgs = _fetch_detail(client, href, ["div.write_div"])
        posts.append({
            "id": make_post_id("dc", href),
            "source": "디시인사이드",
            "title": title,
            "url": href,
            "author": author,
            "time": t_str,
            "likes": likes,
            "comments": cmts,
            "content": content,
            "images": imgs,
            "is_cross_hot": False,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.2)
    return posts


def scrape_fmkorea(client, limit: int = 10) -> list[dict[str, Any]]:
    url = "https://www.fmkorea.com/best2"
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    for item in soup.select("li.li_best2_pop0, div.fm_best_widget ul li, table.bd_lst tbody tr"):
        a = item.select_one("h3.title a, td.title a, a.hotdeal_var8")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = urljoin(url, a.get("href", ""))
        if not title or ("/best" in href and href.endswith("/best2")) or is_noise_post(title):
            continue
        t_el = item.select_one("span.regdate, td.time, span.date")
        t_str = t_el.get_text(strip=True) if t_el else ""
        author_el = item.select_one("span.author, td.author")
        author = author_el.get_text(strip=True) if author_el else ""
        content, imgs = _fetch_detail(client, href, ["div.rd_body article", "div.xe_content"])
        posts.append({
            "id": make_post_id("fm", href),
            "source": "에펨코리아",
            "title": title,
            "url": href,
            "author": author,
            "time": t_str,
            "likes": "",
            "comments": "",
            "content": content,
            "images": imgs,
            "is_cross_hot": False,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.2)
    return posts


def scrape_bobaedream(client, limit: int = 10) -> list[dict[str, Any]]:
    url = "https://www.bobaedream.co.kr/list?code=best"
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    for row in soup.select("table#boardlist tbody tr"):
        a = row.select_one("td.pl14 a.bsubject")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = urljoin(url, a.get("href", ""))
        author_el = row.select_one("td.author02")
        date_el = row.select_one("td.date")
        rec_el = row.select_one("td.recomm")
        content, imgs = _fetch_detail(client, href, ["div.bodyCont", "div#print_area2"])
        posts.append({
            "id": make_post_id("bobae", href),
            "source": "보배드림",
            "title": title,
            "url": href,
            "author": author_el.get_text(strip=True) if author_el else "",
            "time": date_el.get_text(strip=True) if date_el else "",
            "likes": rec_el.get_text(strip=True) if rec_el else "",
            "comments": "",
            "content": content,
            "images": imgs,
            "is_cross_hot": False,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.2)
    return posts


def scrape_mlbpark(client, limit: int = 8) -> list[dict[str, Any]]:
    url = "https://mlbpark.donga.com/mp/b.php?b=bullpen&m=list"
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    for row in soup.select("table.tbl_type01 tbody tr"):
        if row.select_one("span.notice"):
            continue
        a = row.select_one("td.t_left a.txt")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = urljoin(url, a.get("href", ""))
        t_el = row.select_one("span.date")
        t_str = t_el.get_text(strip=True) if t_el else ""
        if is_noise_post(title, "", t_str):
            continue
        content, imgs = _fetch_detail(client, href, ["div#contentDetail", "div.ar_txt"])
        posts.append({
            "id": make_post_id("mp", href),
            "source": "MLB파크",
            "title": title,
            "url": href,
            "author": "",
            "time": t_str,
            "likes": "",
            "comments": "",
            "content": content,
            "images": imgs,
            "is_cross_hot": False,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.2)
    return posts


def scrape_todayhumor(client, limit: int = 8) -> list[dict[str, Any]]:
    url = "https://www.todayhumor.co.kr/board/list.php?table=bestofbest"
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    for row in soup.select("table.table_list tbody tr.view"):
        a = row.select_one("td.subject a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = urljoin(url, a.get("href", ""))
        author_el = row.select_one("td.name")
        date_el = row.select_one("td.date")
        ok_el = row.select_one("td.oknok")
        content, imgs = _fetch_detail(client, href, ["div.viewContent"])
        posts.append({
            "id": make_post_id("ou", href),
            "source": "오늘의유머",
            "title": title,
            "url": href,
            "author": author_el.get_text(strip=True) if author_el else "",
            "time": date_el.get_text(strip=True) if date_el else "",
            "likes": ok_el.get_text(strip=True) if ok_el else "",
            "comments": "",
            "content": content,
            "images": imgs,
            "is_cross_hot": False,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.2)
    return posts


def scrape_clien(client, limit: int = 8) -> list[dict[str, Any]]:
    url = "https://www.clien.net/service/board/park"
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
        href = urljoin(url, link_el.get("href", ""))
        t_str = _extract_clien_time(row)
        like_el = row.select_one("div.list_symph span")
        cmt_el = row.select_one("span.rSymph05")
        content, imgs = _fetch_detail(client, href, ["div.post_article"])
        posts.append({
            "id": make_post_id("clien", href),
            "source": "클리앙",
            "title": title,
            "url": href,
            "author": "",
            "time": t_str,
            "likes": like_el.get_text(strip=True) if like_el else "",
            "comments": cmt_el.get_text(strip=True) if cmt_el else "",
            "content": content,
            "images": imgs,
            "is_cross_hot": False,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.2)
    return posts


def scrape_ppomppu(client, limit: int = 8) -> list[dict[str, Any]]:
    url = "https://www.ppomppu.co.kr/hot.php"
    resp = client.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    posts = []
    seen_urls: set[str] = set()
    for a in soup.find_all("a", href=True):
        if "view.php" not in a["href"]:
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 2:
            continue
        href = urljoin(url, a["href"])
        if href in seen_urls:
            continue
        seen_urls.add(href)
        content, imgs = _fetch_detail(client, href, ["td.board-contents", "div.board-contents"])
        posts.append({
            "id": make_post_id("ppomppu", href),
            "source": "뽐뿌",
            "title": title,
            "url": href,
            "author": "",
            "time": "",
            "likes": "",
            "comments": "",
            "content": content,
            "images": imgs,
            "is_cross_hot": False,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.2)
    return posts


def run() -> dict[str, Any]:
    scrapers = [
        ("디시인사이드", scrape_dcbest),
        ("에펨코리아", scrape_fmkorea),
        ("보배드림", scrape_bobaedream),
        ("MLB파크", scrape_mlbpark),
        ("오늘의유머", scrape_todayhumor),
        ("클리앙", scrape_clien),
        ("뽐뿌", scrape_ppomppu),
    ]

    prev_by_source = load_previous_posts("community_hot.json")
    all_posts: list[dict[str, Any]] = []
    source_status: dict[str, str] = {}

    with make_client() as client:
        for name, fn in scrapers:
            try:
                items = [p for p in fn(client) if not is_noise_post(p.get("title", ""), p.get("author", ""), p.get("time", ""))]
                all_posts.extend(items)
                source_status[name] = f"ok ({len(items)})"
            except Exception as exc:
                cached = prev_by_source.get(name, [])
                if cached:
                    all_posts.extend(cached)
                    source_status[name] = f"cached ({len(cached)}, {type(exc).__name__})"
                else:
                    source_status[name] = f"error: {type(exc).__name__}"

    merged_posts = merge_posts(all_posts, prev_by_source, max_total=120)
    cross_topics = detect_cross_topics(all_posts)
    payload = {
        "updated_at": now_kst_str(),
        "source_status": source_status,
        "cross_topics": cross_topics,
        "posts": merged_posts,
    }
    save_json("community_hot.json", payload)
    return payload
