import hashlib
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

KST = timezone(timedelta(hours=9))
DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

STOPWORDS = {
    "jpg", "jpeg", "png", "gif", "webp", "mp4", "avi", "mov",
    "속보", "단독", "레전드", "근황", "논란", "진짜", "결국", "요즘", "오늘",
    "이유", "사람", "한국", "미국", "일본", "중국", "유머", "이슈", "관련",
    "영상", "사진", "후기", "질문", "추천", "정보", "공유", "정리", "요약",
    "하는", "있는", "없는", "되는", "했다", "한다", "이다", "에서", "으로",
    "먹는", "보는", "가는", "오는", "역대급", "실시간", "대박", "충격", "현재",
    "싱갤", "펌", "스압", "주의", "만화", "짤", "링크", "뉴스", "기사",
}

NOISE_TITLE_PATTERNS = (
    "[공지]", "공지]", "공지사항", "이용 안내", "이용안내", "게시판 규정",
    "갤러리 이용", "운영 안내", "필독", "신고 게시판", "신문고",
)

NOISE_AUTHORS = {"운영자", "관리자", "디시운영자", "마갤매니저", "admin"}


def now_kst() -> datetime:
    return datetime.now(KST)


def now_kst_str() -> str:
    return now_kst().strftime("%Y-%m-%d %H:%M")


def make_post_id(source: str, url: str) -> str:
    digest = hashlib.sha1(f"{source}:{url}".encode("utf-8")).hexdigest()[:12]
    return f"{source}_{digest}"


def make_client(timeout: float = 12.0) -> httpx.Client:
    return httpx.Client(
        headers=DEFAULT_HEADERS,
        timeout=timeout,
        follow_redirects=True,
    )


def save_json(filename: str, payload: dict[str, Any]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / filename
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Netlify Blobs 무배포 갱신 (토큰이 설정된 경우 자동 업로드)
    token = (os.getenv("INGEST_TOKEN") or os.getenv("DASHBOARD_PASSWORD") or "").strip()
    site_url = os.getenv("NETLIFY_SITE_URL", "https://myown-dashboard.netlify.app").rstrip("/")
    if token and site_url:
        name = Path(filename).stem
        try:
            with httpx.Client(timeout=15.0) as client:
                client.post(
                    f"{site_url}/.netlify/functions/data?name={name}",
                    headers={"x-ingest-token": token},
                    json=payload,
                )
        except Exception:
            pass

    return out


def load_previous_posts(filename: str) -> dict[str, list[dict[str, Any]]]:
    """수집 실패 시 직전 성공 데이터를 소스별로 보존하기 위해 기존 JSON을 읽습니다."""
    path = DATA_DIR / filename
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not path.exists():
        return grouped
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        for p in old.get("posts", []):
            src = p.get("source")
            if src:
                grouped[src].append(p)
    except Exception:
        pass
    return grouped


def merge_posts(
    new_posts: list[dict[str, Any]],
    prev_by_source: dict[str, list[dict[str, Any]]],
    max_total: int = 120,
) -> list[dict[str, Any]]:
    """새로 수집한 글을 앞에 두고 기존 글을 누적 유지(중복 제거, 최대 max_total개)합니다."""
    seen_urls: set[str] = set()
    merged: list[dict[str, Any]] = []

    for p in new_posts:
        url = p.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            merged.append(p)

    for prev_list in prev_by_source.values():
        for p in prev_list:
            url = p.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                p["is_cross_hot"] = False
                merged.append(p)
                if len(merged) >= max_total:
                    return merged
    return merged[:max_total]


def clean_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def is_noise_post(title: str, author: str = "", time_str: str = "", max_age_days: int = 30) -> bool:
    """공지글, 운영자 글, 너무 오래된 고정글을 걸러냅니다."""
    t_lower = title.lower().strip()
    if not t_lower:
        return True
    if any(pat in title for pat in NOISE_TITLE_PATTERNS):
        return True
    if author.strip() in NOISE_AUTHORS:
        return True

    # YYYY-MM-DD 또는 YY/MM/DD 형태 날짜가 오래된 경우 필터링
    m_full = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", time_str)
    if m_full:
        try:
            dt = datetime(int(m_full.group(1)), int(m_full.group(2)), int(m_full.group(3)), tzinfo=KST)
            if (now_kst() - dt).days > max_age_days:
                return True
        except ValueError:
            pass
    return False


def _tokenize_title(title: str) -> set[str]:
    stripped = re.sub(r"\.(jpg|jpeg|png|gif|webp|mp4)\b", " ", title, flags=re.I)
    stripped = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", stripped)
    tokens = re.findall(r"[가-힣A-Za-z0-9]{2,}", stripped.lower())
    return {t for t in tokens if t not in STOPWORDS and not t.isdigit()}


def _detect_cross_topics_ai(posts: list[dict[str, Any]], max_topics: int = 5) -> list[dict[str, Any]] | None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or len(posts) < 4:
        return None
    try:
        from google import genai

        items_text = "\n".join(
            f"{p['id']} | {p['source']} | {p['title']}" for p in posts
        )
        prompt = (
            "다음은 여러 한국 커뮤니티의 최신 인기글 목록입니다 (형식: ID | 출처 | 제목).\n"
            "서로 다른 2개 이상의 커뮤니티에서 **실제로 같은 사건, 인물, 뉴스, 사회 이슈**를 다루고 있는 글들만 묶어 주세요.\n"
            "단순히 'jpg', '먹는', '역대급', '레전드' 같은 일반 단어나 파일 확장자가 겹치는 것은 절대 묶지 마세요.\n"
            f"최대 {max_topics}개 그룹만 JSON 배열로 반환하세요. 없으면 빈 배열 []을 반환하세요.\n"
            'JSON 형식: [{"topic": "핵심 이슈명(짧게)", "post_ids": ["id1", "id2"]}]\n\n'
            f"{items_text}"
        )
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
        )
        raw = (resp.text or "").strip()
        m = re.search(r"\[.*\]", raw, re.S)
        if not m:
            return None
        groups = json.loads(m.group(0))
        post_map = {p["id"]: p for p in posts}
        clusters = []
        for g in groups:
            pids = [pid for pid in g.get("post_ids", []) if pid in post_map]
            picked = [post_map[pid] for pid in pids]
            sources = list(dict.fromkeys(p["source"] for p in picked))
            if len(sources) < 2:
                continue
            for p in picked:
                p["is_cross_hot"] = True
            clusters.append({
                "topic": g.get("topic", "공동 화제"),
                "sources": sources,
                "posts": [{"id": p["id"], "source": p["source"], "title": p["title"]} for p in picked],
            })
        return clusters[:max_topics]
    except Exception:
        return None


def detect_cross_topics(posts: list[dict[str, Any]], max_topics: int = 5) -> list[dict[str, Any]]:
    """여러 커뮤니티에서 동시에 언급되는 실제 공동 화제 이슈를 탐지합니다."""
    ai_clusters = _detect_cross_topics_ai(posts, max_topics=max_topics)
    if ai_clusters is not None:
        return ai_clusters

    # AI 키가 없을 때의 폴백: 2개 이상의 핵심 키워드가 동시에 겹치는 글만 매칭
    post_tokens = {p["id"]: _tokenize_title(p.get("title", "")) for p in posts}
    clusters: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for i, p1 in enumerate(posts):
        if p1["id"] in used_ids or len(post_tokens[p1["id"]]) < 2:
            continue
        group = [p1]
        common_words: set[str] = set()
        for p2 in posts[i + 1 :]:
            if p2["id"] in used_ids or p2["source"] == p1["source"]:
                continue
            overlap = post_tokens[p1["id"]] & post_tokens[p2["id"]]
            if len(overlap) >= 2:
                group.append(p2)
                common_words |= overlap

        sources = list(dict.fromkeys(p["source"] for p in group))
        if len(sources) >= 2:
            for p in group:
                p["is_cross_hot"] = True
                used_ids.add(p["id"])
            topic_label = " · ".join(sorted(common_words)[:2])
            clusters.append({
                "topic": topic_label,
                "sources": sources,
                "posts": [{"id": p["id"], "source": p["source"], "title": p["title"]} for p in group],
            })
            if len(clusters) >= max_topics:
                break

    return clusters
