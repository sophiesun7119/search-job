"""Bounded live scan of registered company boards."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from .collectors import collect
from .core import opening_key, parse_time, record_scan, upsert_opening


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _brand_match(job: dict, brand: str | None) -> bool:
    if not brand:
        return True
    return any(value == brand or value.startswith(brand + " -") for value in job.get("brands", []))


def scan_registered(db: sqlite3.Connection, *, provider: str | None = None,
                    company_key: str | None = None, limit: int | None = None,
                    lookback_days: int = 3, full_recheck: bool = False,
                    new_leads_only: bool = False) -> dict:
    if lookback_days < 0 or limit is not None and limit < 1:
        raise ValueError("Invalid scan limit")
    rows = db.execute("""SELECT cb.company_key, cb.brand_filter, cb.evidence_url,
      c.scan_cohort,
      b.board_key,b.provider,b.board_token FROM company_boards cb
      JOIN companies c ON c.company_key=cb.company_key
      JOIN boards b ON b.board_key=cb.board_key
      WHERE cb.status!='pending_identity' AND (? IS NULL OR b.provider=?)
        AND (? IS NULL OR cb.company_key=?)
        AND (?=0 OR EXISTS (SELECT 1 FROM source_leads l
             WHERE l.company_key=cb.company_key AND l.stage='scan_pending'))
      ORDER BY b.provider,cb.company_key""", (provider, provider, company_key, company_key,
                                              int(new_leads_only))).fetchall()
    if limit:
        rows = rows[:limit]
    report = {"candidates": db.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
              "routes": len(rows), "scanned_boards": 0, "seen": 0, "new": 0,
              "recent": 0, "processed": 0, "partial_boards": 0, "failures": [],
              "source_count_gaps": [],
              "lookback_days": lookback_days, "full_recheck": full_recheck,
              "promoted_old": 0}
    now = datetime.now(timezone.utc)
    for route in rows:
        board, company, provider_name = route["board_key"], route["company_key"], route["provider"]
        cutoff = now - (timedelta(days=lookback_days) if full_recheck else
                        timedelta(hours=72 if route["scan_cohort"] == "new" else 24))
        started = utc_now()
        try:
            jobs = collect(provider_name, route["board_token"], company)
            if not isinstance(jobs, list):
                raise ValueError("Collector did not return a complete list")
            observed = set()
            new_count = recent_count = 0
            processed_count = 0
            current_variants: dict[str, set[tuple[str, str]]] = {}
            with db:
                for job in jobs:
                    if not _brand_match(job, route["brand_filter"]):
                        continue
                    key = opening_key(provider_name, board, job["id"], job["url"])
                    if key in observed and not job.get("location"):
                        raise ValueError("Duplicate posting ID with missing location")
                    existed = db.execute("SELECT 1 FROM openings WHERE opening_key=?", (key,)).fetchone()
                    publication = job.get("published")
                    precision = "day" if publication and len(publication) == 10 else "timestamp" if publication else None
                    if publication:
                        parse_time(publication)  # Invalid source dates must not mark a scan complete.
                    updated = job.get("updated")
                    if updated:
                        parse_time(updated)
                    reference = parse_time(publication)
                    is_recent = reference is not None and reference >= cutoff
                    refresh_visible = (bool(existed) and reference is not None and
                                       reference >= now - timedelta(days=3))
                    recent_count += is_recent and key not in observed
                    observed.add(key)
                    if not (full_recheck or is_recent or refresh_visible or
                            (reference is None and not existed)):
                        continue
                    stamp = utc_now()
                    upsert_opening(db, company_key=company, provider=provider_name, board_key=board,
                                   provider_job_id=job["id"], canonical_apply_url=job["url"],
                                   title=job["title"], first_seen_at=stamp, last_seen_at=stamp,
                                   open_state="open", source_date_field=job.get("date_field"),
                                   source_date_value=publication, source_date_precision=precision,
                                   published_at=publication, updated_at=updated,
                                   status_evidence="complete-board-scan",
                                   variants=[(job.get("location") or "", job["url"])])
                    current_variants.setdefault(key, set()).add((job.get("location") or "", job["url"]))
                    new_count += not bool(existed)
                    processed_count += 1
                # A fresh listing replaces stale location/link variants for observed jobs.
                for key, variants in current_variants.items():
                    db.execute("DELETE FROM opening_variants WHERE opening_key=?", (key,))
                    db.executemany("INSERT INTO opening_variants(opening_key,location,apply_url) VALUES (?,?,?)",
                                   [(key, location, url) for location, url in sorted(variants)])
                complete = getattr(jobs, "complete", True)
                record_scan(db, board, uuid.uuid4().hex, started, utc_now(),
                            "complete" if complete else "partial", observed)
                if complete:
                    db.execute("UPDATE boards SET route_status='active' WHERE board_key=?", (board,))
                    db.execute("""UPDATE company_boards SET status='verified',checked_at=?
                      WHERE company_key=? AND board_key=?""", (utc_now(), company, board))
                    if route["scan_cohort"] == "new":
                        db.execute("UPDATE companies SET scan_cohort='old',validated_at=? WHERE company_key=?",
                                   (utc_now(), company))
                        report["promoted_old"] += 1
                    db.execute("""UPDATE source_leads SET stage='scanned',last_error=NULL,checked_at=?,
                      review_state='resolved',review_updated_at=?
                      WHERE company_key=? AND stage='scan_pending'""", (utc_now(), utc_now(), company))
            report["scanned_boards"] += int(complete)
            report["partial_boards"] += int(not complete)
            report["seen"] += len(observed)
            report["new"] += new_count
            report["recent"] += recent_count
            report["processed"] += processed_count
            if getattr(jobs, "source_count_gap", 0):
                report["source_count_gaps"].append({"board": board,
                    "gap": jobs.source_count_gap,
                    "reason": "Oracle public listing count exceeds the matching visible IDs in two sorts"})
        except Exception as error:
            with db:
                record_scan(db, board, uuid.uuid4().hex, started, utc_now(), "failed", set())
                db.execute("""UPDATE source_leads SET last_error=?,checked_at=?,
                  review_state='ai_pending',review_updated_at=?
                  WHERE company_key=? AND stage='scan_pending'""",
                  (f"{type(error).__name__}: {error}"[:300], utc_now(), utc_now(), company))
            report["failures"].append({"company": company, "board": board,
                                       "error": f"{type(error).__name__}: {error}"})
    report["adapter_pending"] = db.execute("SELECT COUNT(*) FROM companies WHERE company_key NOT IN (SELECT company_key FROM company_boards)").fetchone()[0]
    report["identity_review"] = db.execute("SELECT COUNT(*) FROM company_boards WHERE status='pending_identity'").fetchone()[0]
    report["confirmed_routes"] = db.execute("SELECT COUNT(*) FROM company_boards WHERE status='verified'").fetchone()[0]
    return report
