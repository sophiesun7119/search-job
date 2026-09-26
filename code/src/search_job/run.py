"""Explicit local route import and bounded ATS scan command."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .core import connect
from .intake import import_seed
from .leads import (activate_tested_adapter, import_simplify_catalog,
                    resolve_simplify_profiles, verify_official_routes)
from .render import write_outputs
from .scan import scan_registered


def main() -> None:
    parser = argparse.ArgumentParser(description="Import route seeds and scan registered ATS boards")
    parser.add_argument("database", type=Path)
    parser.add_argument("--seed", type=Path, help="Portable JSON company/board route seed")
    parser.add_argument("--simplify-catalog", type=Path, help="Import the next bounded Simplify lead batch")
    parser.add_argument("--source-year", type=int, default=2026, help="Simplify source year (default 2026)")
    parser.add_argument("--resolve-profiles", action="store_true", help="Find candidate company domains from saved Simplify profiles")
    parser.add_argument("--verify-routes", action="store_true", help="Check saved leads against official company careers pages")
    parser.add_argument("--activate-adapter",
                        help="Register official routes after a live adapter test")
    parser.add_argument("--scan", action="store_true", help="Read live ATS boards")
    parser.add_argument("--new-leads-only", action="store_true", help="Scan only boards for the current unscanned source leads")
    parser.add_argument("--provider", help="Limit scan to one provider")
    parser.add_argument("--company", help="Limit scan to one saved company domain")
    parser.add_argument("--limit", type=int, help="Maximum company routes in this run")
    parser.add_argument("--lookback-days", type=int, default=3, help="Recent count window for --full-recheck (default 3)")
    parser.add_argument("--full-recheck", action="store_true", help="Reindex full listings; successful new companies become old")
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if bool(args.markdown) != bool(args.json):
        parser.error("--markdown and --json must be supplied together")
    if args.simplify_catalog and not args.limit:
        parser.error("--simplify-catalog needs a positive --limit")
    with connect(args.database) as db:
        if args.simplify_catalog:
            print(json.dumps({"lead_import": import_simplify_catalog(
                db, args.simplify_catalog, limit=args.limit, year=args.source_year)},
                ensure_ascii=False))
        if args.resolve_profiles:
            print(json.dumps({"profile_resolution": resolve_simplify_profiles(db, limit=args.limit or 100)},
                ensure_ascii=False))
        if args.verify_routes:
            print(json.dumps({"route_verification": verify_official_routes(
                db, provider_hint=args.provider, limit=args.limit or 100)}, ensure_ascii=False))
        if args.activate_adapter:
            print(json.dumps({"adapter_activation": activate_tested_adapter(db, args.activate_adapter)},
                ensure_ascii=False))
        if args.seed:
            print(json.dumps({"import": import_seed(db, args.seed)}, ensure_ascii=False))
        if args.scan:
            print(json.dumps({"scan": scan_registered(db, provider=args.provider, company_key=args.company,
                limit=args.limit, lookback_days=args.lookback_days,
                full_recheck=args.full_recheck, new_leads_only=args.new_leads_only)}, ensure_ascii=False))
        if args.markdown:
            args.markdown.parent.mkdir(parents=True, exist_ok=True)
            args.json.parent.mkdir(parents=True, exist_ok=True)
            write_outputs(db, args.markdown, args.json, datetime.now(timezone.utc))


if __name__ == "__main__":
    main()
