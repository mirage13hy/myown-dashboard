import json
import os
import re
import time
from typing import Any
from urllib.parse import quote

import feedparser
import yfinance as yf
from youtube_transcript_api import YouTubeTranscriptApi

from collectors.common import DATA_DIR, make_client, make_post_id, now_kst_str, save_json

YOUTUBE_CHANNELS = [
    ("슈카월드", "https://www.youtube.com/@syukaworld/videos", 4),
    ("김지윤의 지식play", "https://www.youtube.com/@Kjy_Play/videos", 4),
]

MARKET_TICKERS = [
    ("코스피", "^KS11"),
    ("코스닥", "^KQ11"),
    ("S&P 500", "^GSPC"),
    ("나스닥", "^IXIC"),
    ("원/달러 환율", "KRW=X"),
    ("WTI 유가", "CL=F"),
]


def _fetch_market_news(limit: int = 10) -> list[str]:
    query = quote("코스피 미국증시 나스닥 환율 유가 시황")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        feed = feedparser.parse(rss_url)
        return [e.get("title", "").strip() for e in feed.entries[:limit] if e.get("title")]
    except Exception:
        return []


def _summarize_market_with_gemini(market_lines: list[str], headlines: list[str]) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or not market_lines:
        return ""
    try:
        from google import genai

        prompt = (
            "당신은 경제·증시 브리핑 애널리스트입니다.\n"
            "아래의 주요 지수 등락 데이터와 최신 경제 뉴스 헤드라인을 바탕으로,\n"
            "오늘 코스피·미국 증시·환율·유가 흐름과 **상승/하락의 핵심 원인**(미국 증시 영향, 유가, 금리, 환율, 지정학/전쟁 등)을 "
            "한국어로 4~5줄 이내로 명확하고 간결하게 브리핑해 주세요. (주말/휴장일이면 직전 거래일 마감 기준으로 설명)\n\n"
            "[지수 현황]\n" + "\n".join(market_lines) + "\n\n"
            "[최신 경제 뉴스 헤드라인]\n" + "\n".join(f"- {h}" for h in headlines)
        )
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
        )
        return (resp.text or "").strip()
    except Exception:
        return ""


def _fetch_markets() -> tuple[list[dict[str, Any]], str]:
    results = []
    summary_lines = []

    for name, symbol in MARKET_TICKERS:
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if len(hist) < 2:
                continue
            prev_close = float(hist["Close"].iloc[-2])
            last_close = float(hist["Close"].iloc[-1])
            chg_pct = round(((last_close - prev_close) / prev_close) * 100, 2)
            price_str = f"{last_close:,.2f}"
            results.append({"name": name, "price": price_str, "change_pct": chg_pct})
            sign = "+" if chg_pct > 0 else ""
            summary_lines.append(f"• {name}: {price_str} ({sign}{chg_pct}%)")
        except Exception:
            continue

    headlines = _fetch_market_news(10)
    ai_brief = _summarize_market_with_gemini(summary_lines, headlines)
    if ai_brief:
        brief = ai_brief
    else:
        news_block = "\n".join(f"- {h}" for h in headlines[:5])
        brief = (
            "※ GEMINI_API_KEY가 설정되면 지수+뉴스 기반 AI 원인 분석 브리핑이 표시됩니다.\n\n"
            + ("\n".join(summary_lines) if summary_lines else "")
            + (f"\n\n[최신 시황 헤드라인]\n{news_block}" if news_block else "")
        ).strip()

    return results, brief


def _summarize_video_with_gemini(channel_name: str, title: str, video_url: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or not video_url:
        return ""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    prompt = (
        f"다음은 유튜브 채널 '{channel_name}' 영상입니다.\n"
        "영상을 보지 않아도 핵심을 바로 파악할 수 있도록 아래 형식으로 한국어 요약을 작성해 주세요:\n"
        "1. 한 줄 핵심 결론\n"
        "2. 주요 논점 및 배경 (불릿 3~5개, 핵심 수치/사건 포함)\n\n"
        f"제목: {title}"
    )
    for attempt in range(2):
        try:
            resp = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=[
                    types.Part.from_uri(file_uri=video_url, mime_type="video/mp4"),
                    prompt,
                ],
            )
            return (resp.text or "").strip()
        except Exception:
            if attempt == 0:
                time.sleep(3)
    return ""


def _fetch_transcript(video_id: str) -> str:
    try:
        ytt = YouTubeTranscriptApi()
        fetched = ytt.fetch(video_id, languages=["ko", "en"])
        return " ".join(snippet.text for snippet in fetched)
    except Exception:
        return ""


def _walk_video_renderers(obj: Any, out: list[dict[str, str]], limit: int) -> None:
    if len(out) >= limit:
        return
    if isinstance(obj, dict):
        if "videoRenderer" in obj and isinstance(obj["videoRenderer"], dict):
            vr = obj["videoRenderer"]
            vid = vr.get("videoId", "")
            runs = vr.get("title", {}).get("runs", [])
            title = runs[0].get("text", "") if runs else vr.get("title", {}).get("simpleText", "")
            pub = vr.get("publishedTimeText", {}).get("simpleText", "")
            if vid and title and not any(e["video_id"] == vid for e in out):
                out.append({
                    "video_id": vid,
                    "title": title,
                    "link": f"https://www.youtube.com/watch?v={vid}",
                    "published": pub,
                })
                return
        if "lockupViewModel" in obj and isinstance(obj["lockupViewModel"], dict):
            lv = obj["lockupViewModel"]
            vid = lv.get("contentId", "")
            meta = lv.get("metadata", {}).get("lockupMetadataViewModel", {})
            title = meta.get("title", {}).get("content", "")
            rows = meta.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
            pub = ""
            if len(rows) > 1:
                parts = rows[1].get("metadataParts", [])
                if parts:
                    pub = parts[-1].get("text", {}).get("content", "")
            if vid and title and not any(e["video_id"] == vid for e in out):
                out.append({
                    "video_id": vid,
                    "title": title,
                    "link": f"https://www.youtube.com/watch?v={vid}",
                    "published": pub,
                })
                return
        for val in obj.values():
            _walk_video_renderers(val, out, limit)
    elif isinstance(obj, list):
        for item in obj:
            _walk_video_renderers(item, out, limit)


def _fetch_channel_entries(channel_url: str, limit: int = 4) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    try:
        with make_client() as client:
            resp = client.get(channel_url)
            if resp.status_code != 200:
                return entries
            idx = resp.text.find("ytInitialData")
            if idx == -1:
                return entries
            json_start = resp.text.find("{", idx)
            if json_start == -1:
                return entries
            data, _ = json.JSONDecoder().raw_decode(resp.text, json_start)
            _walk_video_renderers(data, entries, limit)
    except Exception:
        pass
    return entries


def _load_cached_summaries() -> dict[str, str]:
    cache: dict[str, str] = {}
    path = DATA_DIR / "economy_briefing.json"
    if not path.exists():
        return cache
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        for v in old.get("videos", []):
            if v.get("category") == "AI 요약" and v.get("id") and v.get("content"):
                cache[v["id"]] = v["content"]
    except Exception:
        pass
    return cache


def _fetch_all_videos() -> list[dict[str, Any]]:
    cached = _load_cached_summaries()
    videos = []
    for channel_name, channel_url, limit in YOUTUBE_CHANNELS:
        for entry in _fetch_channel_entries(channel_url, limit):
            video_id = entry["video_id"]
            title = entry["title"]
            link = entry["link"]
            published = entry["published"]
            pid = make_post_id(channel_name, link or video_id)

            summary = cached.get(pid, "")
            transcript = ""
            if not summary and link:
                summary = _summarize_video_with_gemini(channel_name, title, link)
                if not summary and video_id:
                    transcript = _fetch_transcript(video_id)
                if summary:
                    time.sleep(1.0)

            content = summary or (
                "[AI 요약을 위해 GEMINI_API_KEY 설정이 필요합니다 — 아래는 자막 일부입니다]\n\n"
                + transcript[:2500]
                + ("..." if len(transcript) > 2500 else "")
                if transcript
                else "자막이 아직 제공되지 않았거나 가져올 수 없습니다. 원본 영상 링크를 확인해 주세요."
            )

            videos.append({
                "id": pid,
                "source": channel_name,
                "category": "AI 요약" if summary else "자막 원문",
                "title": title,
                "url": link,
                "author": channel_name,
                "time": published,
                "content": content,
                "images": [f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"] if video_id else [],
            })
    return videos


def run() -> dict[str, Any]:
    markets, market_brief = _fetch_markets()
    videos = _fetch_all_videos()
    payload = {
        "updated_at": now_kst_str(),
        "markets": markets,
        "market_brief": market_brief,
        "videos": videos,
    }
    save_json("economy_briefing.json", payload)
    return payload
