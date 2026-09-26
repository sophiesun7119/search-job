"""Explicit local route import and bounded ATS scan command."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .core import connect
from .intake import import_seed
from .leads import (activate_tested_adapter, confirm_official_route, import_simplify_catalog,
                    mark_ai_review, preserve_profile_company_links, probe_saved_samples,
                    resolve_simplify_profiles, route_resolution_report, verify_official_routes)
from .review_dashboard import write_review_dashboard
from .render import write_outputs
from .scan import scan_registered


def main() -> None:
    parser = argparse.ArgumentParser(description="Import route seeds and scan registered ATS boards")
    parser.add_argument("database", type=Path)
    parser.add_argument("--seed", type=Path, help="Portable JSON company/board route seed")
    parser.add_argument("--simplify-catalog", type=Path, help="Import the next bounded Simplify lead batch")
    parser.add_argument("--source-year", type=int, default=2026, help="Simplify source year (default 2026)")
    parser.add_argument("--resolve-profiles", action="store_true", help="Find candidate company domains from saved Simplify profiles")
    parser.add_argument("--probe-samples", action="store_true", help="Check saved Apply URLs without treating them as official routes")
    parser.add_argument("--triage-leads", action="store_true", help="Probe sample links first, then resolve company sites and verify official ATS routes")
    parser.add_argument("--route-report", action="store_true", help="Count script, AI, and user-verified routes")
    parser.add_argument("--preserve-profile-links", action="store_true",
                        help="Save company websites found in original Simplify profiles without changing routes")
    parser.add_argument("--ai-review-lead", help="Record an actual AI investigation of one unresolved lead")
    parser.add_argument("--ai-review-outcome", choices=("investigating", "needs-user"))
    parser.add_argument("--review-note", help="Evidence and blocker for --ai-review-lead")
    parser.add_argument("--review-dashboard", type=Path,
                        help="Local dashboard output path (default: DATABASE parent/review-dashboard.html)")
    parser.add_argument("--verify-routes", action="store_true", help="Check saved leads against official company careers pages")
    parser.add_argument("--lead-key", help="Limit route verification to one saved lead key")
    parser.add_argument("--activate-adapter",
                        help="Register official routes after a live adapter test")
    parser.add_argument("--confirm-route", help="Agent-reviewed lead key after an official page fetch fails")
    parser.add_argument("--evidence-url", help="Official company page inspected for --confirm-route")
    parser.add_argument("--board-url", help="Exact ATS board link found on that page")
    parser.add_argument("--confirmation-source", choices=("ai", "user"), default="ai",
                        help="Who inspected the official evidence for --confirm-route (default AI)")
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
    if args.confirm_route and (not args.evidence_url or not args.board_url):
        parser.error("--confirm-route needs --evidence-url and --board-url")
    if args.ai_review_lead and (not args.ai_review_outcome or not args.review_note):
        parser.error("--ai-review-lead needs --ai-review-outcome and --review-note")
    with connect(args.database) as db:
        if args.simplify_catalog:
            print(json.dumps({"lead_import": import_simplify_catalog(
                db, args.simplify_catalog, limit=args.limit, year=args.source_year)},
                ensure_ascii=False))
        if args.triage_leads:
            batch_limit = args.limit or 100
            print(json.dumps({"sample_probe": probe_saved_samples(db, limit=batch_limit)}, ensure_ascii=False))
            print(json.dumps({"profile_resolution": resolve_simplify_profiles(db, limit=batch_limit)}, ensure_ascii=False))
            print(json.dumps({"route_verification": verify_official_routes(
                db, provider_hint=args.provider, lead_key=args.lead_key, limit=batch_limit)}, ensure_ascii=False))
            print(json.dumps({"route_report": route_resolution_report(db)}, ensure_ascii=False))
        if args.resolve_profiles and not args.triage_leads:
            print(json.dumps({"profile_resolution": resolve_simplify_profiles(db, limit=args.limit or 100)},
                ensure_ascii=False))
        if args.preserve_profile_links:
            print(json.dumps({"profile_company_links": preserve_profile_company_links(
                db, limit=args.limit or 100)}, ensure_ascii=False))
        if args.probe_samples and not args.triage_leads:
            print(json.dumps({"sample_probe": probe_saved_samples(db, limit=args.limit or 100)},
                ensure_ascii=False))
        if args.verify_routes and not args.triage_leads:
            print(json.dumps({"route_verification": verify_official_routes(
                db, provider_hint=args.provider, lead_key=args.lead_key,
                limit=args.limit or 100)}, ensure_ascii=False))
        if args.activate_adapter:
            print(json.dumps({"adapter_activation": activate_tested_adapter(db, args.activate_adapter)},
                ensure_ascii=False))
        if args.confirm_route:
            print(json.dumps({"route_confirmation": confirm_official_route(
                db, args.confirm_route, evidence_url=args.evidence_url,
                board_url=args.board_url, confirmation_source=args.confirmation_source)}, ensure_ascii=False))
        if args.ai_review_lead:
            print(json.dumps({"ai_review": mark_ai_review(db, args.ai_review_lead,
                outcome=args.ai_review_outcome, note=args.review_note)}, ensure_ascii=False))
        if args.route_report and not args.triage_leads:
            print(json.dumps({"route_report": route_resolution_report(db)}, ensure_ascii=False))
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
        print(json.dumps({"review_dashboard": write_review_dashboard(
            db, args.review_dashboard or args.database.parent / "review-dashboard.html")},
            ensure_ascii=False))


if __name__ == "__main__":
    main()
