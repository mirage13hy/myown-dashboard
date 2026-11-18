import argparse
import json
from dotenv import load_dotenv

from collectors import community_ai, community_hot, deals, economy_briefing


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="MyOwn 대시보드 데이터 수집기")
    parser.add_argument(
        "--only",
        choices=["hot", "ai", "deals", "economy", "all"],
        default="all",
        help="실행할 수집 모듈 선택",
    )
    args = parser.parse_args()

    summary = {}
    if args.only in ("hot", "all"):
        res = community_hot.run()
        summary["community_hot"] = res.get("source_status", {})

    if args.only in ("ai", "all"):
        res = community_ai.run()
        summary["community_ai"] = res.get("source_status", {})

    if args.only in ("deals", "all"):
        res = deals.run()
        summary["deals"] = res.get("source_status", {})

    if args.only in ("economy", "all"):
        res = economy_briefing.run()
        summary["economy_briefing"] = {
            "markets": len(res.get("markets", [])),
            "videos": len(res.get("videos", [])),
        }

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
