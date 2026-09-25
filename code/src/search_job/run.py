"""Explicit local route import and bounded ATS scan command."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .core import connect
from .intake import import_seed
from .render import write_outputs
from .scan import scan_registered


def main() -> None:
    parser = argparse.ArgumentParser(description="Import route seeds and scan registered ATS boards")
    parser.add_argument("database", type=Path)
    parser.add_argument("--seed", type=Path, help="Portable JSON company/board route seed")
    parser.add_argument("--scan", action="store_true", help="Read live ATS boards")
    parser.add_argument("--provider", help="Limit scan to one provider")
    parser.add_argument("--limit", type=int, help="Maximum company routes in this run")
    parser.add_argument("--lookback-days", type=int, default=3, help="Recent count window; all listed jobs still enter DB")
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if bool(args.markdown) != bool(args.json):
        parser.error("--markdown and --json must be supplied together")
    with connect(args.database) as db:
        if args.seed:
            print(json.dumps({"import": import_seed(db, args.seed)}, ensure_ascii=False))
        if args.scan:
            print(json.dumps({"scan": scan_registered(db, provider=args.provider,
                limit=args.limit, lookback_days=args.lookback_days)}, ensure_ascii=False))
        if args.markdown:
            args.markdown.parent.mkdir(parents=True, exist_ok=True)
            args.json.parent.mkdir(parents=True, exist_ok=True)
            write_outputs(db, args.markdown, args.json, datetime.now(timezone.utc))


if __name__ == "__main__":
    main()
