"""Bounded, script-only Simplify intake. Never writes job openings."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from .collectors import ACTIVE_COLLECTORS, _read, collect
from .core import connect, upsert_board, upsert_company
from .leads import (_official_route, _probe_sample, _profile_domain,
                    import_simplify_catalog, recognize_apply_url)


def _board_probe(provider: str, token: str) -> int:
    """Check one public listing response, without scanning or saving postings."""
    safe = quote(token, safe="")
    if provider == "greenhouse":
        data = _read(f"https://boards-api.greenhouse.io/v1/boards/{safe}/jobs?content=false")
        listing = data.get("jobs") if isinstance(data, dict) else None
    elif provider == "ashby":
        data = _read(f"https://api.ashbyhq.com/posting-api/job-board/{safe}")
        listing = data.get("jobs") if isinstance(data, dict) else None
    elif provider == "smartrecruiters":
        data = _read(f"https://api.smartrecruiters.com/v1/companies/{safe}/postings?limit=1&offset=0")
        listing = data.get("content") if isinstance(data, dict) else None
    elif provider == "lever":
        listing = _read(f"https://api.lever.co/v0/postings/{safe}?mode=json&limit=1&skip=0")
    elif provider == "workday":
        host, tenant, site = token.split("|")
        transport = host.replace("_", "-")
        data = _read(f"https://{transport}/wday/cxs/{quote(tenant)}/{quote(site)}/jobs",
                     {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                     host_header=host if host != transport else None)
        listing = data.get("jobPostings") if isinstance(data, dict) else None
    elif provider == "oracle":
        host, site = token.split("|")
        data = _read(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
                     f"?onlyData=true&finder=findReqs;siteNumber={quote(site)},limit=200,offset=0"
                     "&expand=requisitionList.secondaryLocations")
        roots = data.get("items") if isinstance(data, dict) else None
        listing = roots[0].get("requisitionList") if isinstance(roots, list) and len(roots) == 1 else None
    elif provider == "workable":
        data = _read(f"https://www.workable.com/api/accounts/{safe}?details=true")
        listing = data.get("jobs") if isinstance(data, dict) else None
    elif provider in {"icims", "bamboohr", "rippling"}:
        return len(collect(provider, token))
    else:
        raise ValueError(f"Fast board probe is not implemented for {provider}")
    if not isinstance(listing, list):
        raise ValueError(f"{provider} did not return a job-list field")
    return len(listing)


def _check(lead: dict) -> dict:
    url = lead["sample_apply_url"] or ""
    provider, board = recognize_apply_url(url)
    sample_probe = None
    if provider == "unknown" or not board:
        final_url, status, error = _probe_sample(url)
        sample_probe = (final_url, status, error)
        redirected_provider, redirected_board = recognize_apply_url(final_url or "")
        if redirected_provider != "unknown" and (redirected_board or provider == "unknown"):
            provider, board = redirected_provider, redirected_board
    result = {"provider": provider, "board": board, "sample_probe": sample_probe}
    if provider == "unknown":
        return result | {"outcome": "ats_unknown", "detail": "Sample URL and redirect did not yield an ATS board"}
    if provider not in ACTIVE_COLLECTORS:
        return result | {"outcome": "adapter_missing", "detail": "Sample ATS hint has no active adapter; official attribution is unconfirmed"}
    official = lead["official_url"]
    if not official and lead["profile_url"]:
        try:
            domain = _profile_domain(lead["profile_url"])
            official = f"https://{domain}/" if domain else None
        except Exception as exc:
            return result | {"outcome": "official_domain_missing", "detail": f"{type(exc).__name__}: {exc}"[:300]}
    if not official:
        return result | {"outcome": "official_domain_missing", "detail": "No official company URL in Simplify profile"}
    result["official_url"] = official
    route = _official_route(lead | {"official_url": official, "provider_hint": provider, "board_hint": board})
    if route["stage"] == "adapter_pending":
        return result | {"outcome": "official_adapter_missing", "detail": "Official careers page confirms ATS without active adapter", "route": route}
    if route["stage"] != "scan_pending":
        return result | {"outcome": "official_route_missing", "detail": route.get("error") or "Official route unavailable"}
    result["route"] = route
    try:
        result["listing_count"] = _board_probe(route["provider"], route["board"])
    except Exception as exc:
        return result | {"outcome": "board_probe_failed", "detail": f"{type(exc).__name__}: {exc}"[:300]}
    return result | {"outcome": "board_verified", "detail": "Official route and first listing response verified; full job scan pending"}


def run(db, catalog: Path, *, limit: int = 100, workers: int = 12) -> dict:
    if not 1 <= limit <= 100 or not 1 <= workers <= 16:
        raise ValueError("Batch must contain 1–100 leads and use 1–16 workers")
    pending = db.execute("""SELECT batch_id FROM fast_intake_queue WHERE finished_at IS NULL
      ORDER BY queued_at DESC LIMIT 1""").fetchone()
    if pending:
        batch_id = pending[0]
        imported = [row[0] for row in db.execute("""SELECT lead_key FROM fast_intake_queue
          WHERE batch_id=? AND finished_at IS NULL ORDER BY lead_key""", (batch_id,))]
    else:
        # Prefer current-year source evidence; fill only the remainder from 2025.
        imported = []
        for year in (2026, 2025):
            if len(imported) == limit:
                break
            batch = import_simplify_catalog(db, catalog, limit=limit - len(imported), year=year)
            imported.extend(f"simplify:{source_id}" for source_id in batch["source_ids"])
        batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stamp = datetime.now(timezone.utc).isoformat()
        with db:
            db.executemany("""INSERT INTO fast_intake_queue(lead_key,batch_id,queued_at)
              VALUES (?,?,?)""", [(key, batch_id, stamp) for key in imported])
    leads = [dict(db.execute("SELECT * FROM source_leads WHERE lead_key=?", (key,)).fetchone()) for key in imported]
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_check, lead): lead for lead in leads}
        for future in as_completed(futures):
            lead = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"outcome": "official_route_missing", "detail": f"{type(exc).__name__}: {exc}"[:300],
                          "provider": lead["provider_hint"], "board": lead["board_hint"]}
            results.append((lead, result))
    stamp = datetime.now(timezone.utc).isoformat()
    with db:
        for lead, result in results:
            outcome = result["outcome"]
            route = result.get("route") or {}
            official = result.get("official_url")
            company_key = None
            if outcome == "board_verified":
                company_key = (urlsplit(official).hostname or "").lower().removeprefix("www.")
                upsert_company(db, company_key, lead["name"], official, f"simplify:{lead['source_year']}")
                board_key = f"{route['provider']}:{route['board']}"
                upsert_board(db, board_key, route["provider"], route["board"], route["board_url"])
                db.execute("""INSERT INTO company_boards(company_key,board_key,evidence_url,checked_at,status)
                  VALUES (?,?,?,?,'pending_recheck') ON CONFLICT(company_key,board_key) DO NOTHING""",
                  (company_key, board_key, route["evidence_page"], stamp))
            stage = ("scan_pending" if outcome == "board_verified" else
                     "adapter_pending" if outcome == "official_adapter_missing" else
                     "board_pending" if outcome == "board_probe_failed" else "route_pending")
            probe = result.get("sample_probe") or (None, None, None)
            db.execute("""UPDATE source_leads SET stage=?,company_key=?,official_url=COALESCE(?,official_url),
              profile_company_url=COALESCE(?,profile_company_url),provider_hint=?,board_hint=?,
              route_evidence_url=?,route_resolution_method=CASE WHEN ? IS NOT NULL THEN 'script_official_page' ELSE NULL END,
              official_board_url=?,sample_probe_url=COALESCE(?,sample_probe_url),
              sample_probe_status=COALESCE(?,sample_probe_status),sample_probe_error=COALESCE(?,sample_probe_error),
              last_error=?,checked_at=?,review_state=?,review_updated_at=? WHERE lead_key=?""",
              (stage, company_key, official, official, route.get("provider") or result.get("provider"),
               route.get("board") or result.get("board"), route.get("evidence_page"),
               route.get("evidence_page"), route.get("board_url"), *probe,
               None if outcome == "board_verified" else result["detail"], stamp,
               "resolved" if outcome == "board_verified" else "script_pending", stamp, lead["lead_key"]))
            db.execute("""INSERT OR REPLACE INTO fast_intake_checks
              (lead_key,batch_id,outcome,detail,provider,board_token,listing_count,checked_at)
              VALUES (?,?,?,?,?,?,?,?)""",
              (lead["lead_key"], batch_id, outcome, result["detail"],
               route.get("provider") or result.get("provider"), route.get("board") or result.get("board"),
               result.get("listing_count"), stamp))
            db.execute("UPDATE fast_intake_queue SET finished_at=? WHERE lead_key=?",
                       (stamp, lead["lead_key"]))
    return {"batch_id": batch_id, "selected": len(imported),
            "outcomes": dict(sorted(Counter(result["outcome"] for _, result in results).items())),
            "provider_hints": dict(sorted(Counter(result.get("provider") or "unknown" for _, result in results).items())),
            "companies_added": sum(result["outcome"] == "board_verified" for _, result in results),
            "no_job_scan": True}


def retry_board_probes(db, *, workers: int = 8) -> dict:
    """Retry only this batch's official routes after improving a probe."""
    batch_id = db.execute("SELECT MAX(batch_id) FROM fast_intake_checks").fetchone()[0]
    rows = [dict(row) for row in db.execute("""SELECT s.*,f.provider,f.board_token
      FROM fast_intake_checks f JOIN source_leads s ON s.lead_key=f.lead_key
      WHERE f.batch_id=? AND f.outcome='board_probe_failed'""", (batch_id,))]
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_board_probe, row["provider"], row["board_token"]): row for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                results.append((row, future.result(), None))
            except Exception as exc:
                results.append((row, None, f"{type(exc).__name__}: {exc}"[:300]))
    stamp = datetime.now(timezone.utc).isoformat()
    with db:
        for lead, count, error in results:
            if error is None:
                company_key = (urlsplit(lead["official_url"]).hostname or "").lower().removeprefix("www.")
                upsert_company(db, company_key, lead["name"], lead["official_url"], f"simplify:{lead['source_year']}")
                board_key = f"{lead['provider']}:{lead['board_token']}"
                upsert_board(db, board_key, lead["provider"], lead["board_token"], lead["official_board_url"])
                db.execute("""INSERT INTO company_boards(company_key,board_key,evidence_url,checked_at,status)
                  VALUES (?,?,?,?,'pending_recheck') ON CONFLICT(company_key,board_key) DO NOTHING""",
                  (company_key, board_key, lead["route_evidence_url"], stamp))
                db.execute("""UPDATE source_leads SET stage='scan_pending',company_key=?,last_error=NULL,
                  checked_at=?,review_state='resolved',review_updated_at=? WHERE lead_key=?""",
                  (company_key, stamp, stamp, lead["lead_key"]))
            else:
                db.execute("UPDATE source_leads SET last_error=?,checked_at=? WHERE lead_key=?",
                           (error, stamp, lead["lead_key"]))
            db.execute("""UPDATE fast_intake_checks SET outcome=?,detail=?,listing_count=?,checked_at=?
              WHERE lead_key=?""", ("board_verified" if error is None else "board_probe_failed",
              "Official route and first listing response verified; full job scan pending" if error is None else error,
              count, stamp, lead["lead_key"]))
    return {"batch_id": batch_id, "retried": len(rows), "newly_verified": sum(error is None for _, _, error in results)}


def retry_unknown_ats(db, *, workers: int = 8) -> dict:
    """Recheck only unrecognized sample URLs after a recognition-rule fix."""
    batch_id = db.execute("SELECT MAX(batch_id) FROM fast_intake_checks").fetchone()[0]
    leads = [dict(row) for row in db.execute("""SELECT s.* FROM fast_intake_checks f
      JOIN source_leads s ON s.lead_key=f.lead_key
      WHERE f.batch_id=? AND f.outcome='ats_unknown'""", (batch_id,))]
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_check, lead): lead for lead in leads}
        for future in as_completed(futures):
            lead = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"outcome": "official_route_missing", "detail": f"{type(exc).__name__}: {exc}"[:300],
                          "provider": lead["provider_hint"], "board": lead["board_hint"]}
            results.append((lead, result))
    stamp = datetime.now(timezone.utc).isoformat()
    with db:
        for lead, result in results:
            route = result.get("route") or {}
            outcome = result["outcome"]
            company_key = None
            if outcome == "board_verified":
                company_key = (urlsplit(result["official_url"]).hostname or "").lower().removeprefix("www.")
                upsert_company(db, company_key, lead["name"], result["official_url"], f"simplify:{lead['source_year']}")
                board_key = f"{route['provider']}:{route['board']}"
                upsert_board(db, board_key, route["provider"], route["board"], route["board_url"])
                db.execute("""INSERT INTO company_boards(company_key,board_key,evidence_url,checked_at,status)
                  VALUES (?,?,?,?,'pending_recheck') ON CONFLICT(company_key,board_key) DO NOTHING""",
                  (company_key, board_key, route["evidence_page"], stamp))
            stage = ("scan_pending" if outcome == "board_verified" else
                     "adapter_pending" if outcome == "official_adapter_missing" else
                     "board_pending" if outcome == "board_probe_failed" else "route_pending")
            probe = result.get("sample_probe") or (None, None, None)
            db.execute("""UPDATE source_leads SET stage=?,company_key=?,official_url=COALESCE(?,official_url),
              profile_company_url=COALESCE(?,profile_company_url),provider_hint=?,board_hint=?,
              route_evidence_url=?,route_resolution_method=CASE WHEN ? IS NOT NULL THEN 'script_official_page' ELSE NULL END,
              official_board_url=?,sample_probe_url=COALESCE(?,sample_probe_url),
              sample_probe_status=COALESCE(?,sample_probe_status),sample_probe_error=COALESCE(?,sample_probe_error),
              last_error=?,checked_at=?,review_state=?,review_updated_at=? WHERE lead_key=?""",
              (stage, company_key, result.get("official_url"), result.get("official_url"),
               route.get("provider") or result.get("provider"), route.get("board") or result.get("board"),
               route.get("evidence_page"), route.get("evidence_page"), route.get("board_url"), *probe,
               None if outcome == "board_verified" else result["detail"], stamp,
               "resolved" if outcome == "board_verified" else "script_pending", stamp, lead["lead_key"]))
            db.execute("""UPDATE fast_intake_checks SET outcome=?,detail=?,provider=?,board_token=?,
              listing_count=?,checked_at=? WHERE lead_key=?""",
              (outcome, result["detail"], route.get("provider") or result.get("provider"),
               route.get("board") or result.get("board"), result.get("listing_count"), stamp, lead["lead_key"]))
    return {"batch_id": batch_id, "retried": len(leads),
            "outcomes": dict(Counter(result["outcome"] for _, result in results))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--retry-board-probes", action="store_true")
    parser.add_argument("--retry-unknown-ats", action="store_true")
    args = parser.parse_args()
    with connect(args.database) as db:
        result = (retry_board_probes(db, workers=args.workers) if args.retry_board_probes else
                  retry_unknown_ats(db, workers=args.workers) if args.retry_unknown_ats else
                  run(db, args.catalog, limit=args.limit, workers=args.workers))
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
