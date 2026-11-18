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
from collectors.community_hot import _extract_clien_time, _fetch_detail

DEAL_CATEGORIES = [
    ("AI·구독", ("ai", "gpt", "제미나이", "gemini", "클로드", "퍼플렉시티", "유튜브", "스포티파이", "넷플릭스", "디즈니", "티빙", "웨이브", "구독", "멤버십", "프리미엄")),
    ("게임·콘솔", ("게임", "스팀", "steam", "닌텐도", "스위치", "플스", "ps5", "ps4", "엑스박스", "xbox", "컨트롤러", "게임패드", "듀얼센스", "에픽", "로블록스")),
    ("디지털·가전", ("노트북", "모니터", "ssd", "그래픽카드", "rtx", "키보드", "마우스", "아이패드", "갤럭시", "애플", "워치", "에어팟", "이어폰", "헤드셋", "충전기", "가전", "청소기", "tv", "태블릿", "pc", "램", "메모리")),
    ("상품권·이용권", ("상품권", "금액권", "기프트카드", "컬쳐랜드", "해피머니", "네이버페이", "빕스", "vips", "애슐리", "아웃백", "뷔페", "에버랜드", "롯데월드", "놀이동산", "자유이용권", "파리바게트", "파리바게뜨", "배스킨", "스타벅스")),
    ("항공·여행", ("항공", "항공권", "비행기", "호텔", "리조트", "숙박", "여행", "제주", "도쿄", "오사카", "후쿠오카", "방콕", "다낭", "유럽", "면세", "에어부산", "진에어", "티웨이")),
]

FOOD_EXCLUDE_KEYWORDS = (
    "아메리카노", "라떼", "커피", "음료", "닭가슴살", "라면", "사발면", "볶음면",
    "만두", "김치", "삼겹살", "돼지", "소고기", "오징어", "단감", "사과", "귤",
    "생수", "우유", "과자", "초콜릿", "치킨", "피자", "햄버거", "국밥", "찌개",
    "도시락", "밀키트", "햇반", "참치", "스팸", "kg", "ml", "개입", "팩",
)


def _classify_deal(title: str) -> str | None:
    t = title.lower()
    # 음식·음료 단품/묶음 제외 (단, 외식/뷔페/상품권/금액권/이용권이 명시된 경우는 예외)
    is_voucher = any(v in t for v in ("상품권", "금액권", "기프트카드", "자유이용권", "이용권", "컬쳐랜드", "해피머니"))
    if not is_voucher and any(fk in t for fk in FOOD_EXCLUDE_KEYWORDS):
        return None

    for label, keywords in DEAL_CATEGORIES:
        if any(k in t for k in keywords):
            return label
    return None


def _scrape_fmkorea_hotdeal(client, limit: int = 25) -> list[dict[str, Any]]:
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
        if not title or is_noise_post(title):
            continue
        cat = _classify_deal(title)
        if not cat:
            continue
        href = urljoin(url, a.get("href", ""))
        t_el = item.select_one("span.regdate, td.time")
        t_str = t_el.get_text(strip=True) if t_el else ""
        content, imgs = _fetch_detail(client, href, ["div.rd_body article", "div.xe_content"])
        posts.append({
            "id": make_post_id("fm_deal", href),
            "source": "에펨코리아 핫딜",
            "category": cat,
            "title": title,
            "url": href,
            "author": "",
            "time": t_str,
            "likes": "",
            "comments": "",
            "content": content,
            "images": imgs,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.15)
    return posts


def _scrape_ppomppu_board(client, limit: int = 25) -> list[dict[str, Any]]:
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
        if not title or len(title) < 3 or is_noise_post(title):
            continue
        cat = _classify_deal(title)
        if not cat:
            continue
        href = urljoin(url, href_raw)
        if href in seen:
            continue
        seen.add(href)
        content, imgs = _fetch_detail(client, href, ["td.board-contents", "div.board-contents"])
        posts.append({
            "id": make_post_id("ppom_deal", href),
            "source": "뽐뿌",
            "category": cat,
            "title": title,
            "url": href,
            "author": "",
            "time": "",
            "likes": "",
            "comments": "",
            "content": content,
            "images": imgs,
        })
        if len(posts) >= limit:
            break
        time.sleep(0.15)
    return posts


def _scrape_clien_jirum(client, limit: int = 25) -> list[dict[str, Any]]:
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
        if not title or is_noise_post(title):
            continue
        cat = _classify_deal(title)
        if not cat:
            continue
        href = urljoin(url, link_el.get("href", ""))
        t_str = _extract_clien_time(row)
        like_el = row.select_one("div.list_symph span")
        cmt_el = row.select_one("span.rSymph05")
        content, imgs = _fetch_detail(client, href, ["div.post_article"])
        posts.append({
            "id": make_post_id("clien_deal", href),
            "source": "클리앙 알뜰구매",
            "category": cat,
            "title": title,
            "url": href,
            "author": "",
            "time": t_str,
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
        ("에펨코리아 핫딜", _scrape_fmkorea_hotdeal),
        ("뽐뿌", _scrape_ppomppu_board),
        ("클리앙 알뜰구매", _scrape_clien_jirum),
    ]

    prev_by_source = load_previous_posts("deals.json")
    # 기존 저장 데이터 중 '기타' 또는 음식글은 제거
    allowed_cats = {label for label, _ in DEAL_CATEGORIES}
    for src in list(prev_by_source.keys()):
        prev_by_source[src] = [
            p for p in prev_by_source[src]
            if p.get("category") in allowed_cats and _classify_deal(p.get("title", "")) is not None
        ]

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
    save_json("deals.json", payload)
    return payload
