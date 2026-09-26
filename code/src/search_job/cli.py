"""Minimal stage-one database and renderer commands."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from .core import connect, parse_time, refresh_all_tags
from .render import write_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Search Job stage-one DB and README renderer")
    parser.add_argument("database", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--as-of", help="ISO timestamp for repeatable output")
    parser.add_argument("--historical-preview", action="store_true")
    parser.add_argument("--retag", action="store_true", help="Recompute title tags locally without an ATS scan")
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    with connect(args.database) as db:
        if args.retag:
            print(f"Retagged {refresh_all_tags(db)} saved openings")
        if args.markdown or args.json:
            if not args.markdown or not args.json:
                parser.error("--markdown and --json must be supplied together")
            as_of = parse_time(args.as_of) if args.as_of else datetime.now(timezone.utc)
            write_outputs(db, args.markdown, args.json, as_of,
                          historical_preview=args.historical_preview)


if __name__ == "__main__":
    main()
