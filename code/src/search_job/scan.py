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
                    limit: int | None = None, lookback_days: int = 3) -> dict:
    if lookback_days < 0 or limit is not None and limit < 1:
        raise ValueError("Invalid scan limit")
    rows = db.execute("""SELECT cb.company_key, cb.brand_filter, cb.evidence_url,
      b.board_key,b.provider,b.board_token FROM company_boards cb
      JOIN boards b ON b.board_key=cb.board_key
      WHERE cb.status!='pending_identity' AND (? IS NULL OR b.provider=?)
      ORDER BY b.provider,cb.company_key""", (provider, provider)).fetchall()
    if limit:
        rows = rows[:limit]
    report = {"candidates": db.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
              "routes": len(rows), "scanned_boards": 0, "seen": 0, "new": 0,
              "recent": 0, "partial_boards": 0, "failures": [], "lookback_days": lookback_days}
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)
    for route in rows:
        board, company, provider_name = route["board_key"], route["company_key"], route["provider"]
        started = utc_now()
        try:
            jobs = collect(provider_name, route["board_token"], company)
            if not isinstance(jobs, list):
                raise ValueError("Collector did not return a complete list")
            observed = set()
            new_count = recent_count = 0
            with db:
                for job in jobs:
                    if not _brand_match(job, route["brand_filter"]):
                        continue
                    key = opening_key(provider_name, board, job["id"], job["url"])
                    existed = db.execute("SELECT 1 FROM openings WHERE opening_key=?", (key,)).fetchone()
                    publication = job.get("published")
                    precision = "day" if publication and len(publication) == 10 else "timestamp" if publication else None
                    if publication:
                        parse_time(publication)  # Invalid source dates must not mark a scan complete.
                    updated = job.get("updated")
                    if updated:
                        parse_time(updated)
                    stamp = utc_now()
                    upsert_opening(db, company_key=company, provider=provider_name, board_key=board,
                                   provider_job_id=job["id"], canonical_apply_url=job["url"],
                                   title=job["title"], first_seen_at=stamp, last_seen_at=stamp,
                                   open_state="open", source_date_field=job.get("date_field"),
                                   source_date_value=publication, source_date_precision=precision,
                                   published_at=publication, updated_at=updated,
                                   status_evidence="complete-board-scan",
                                   variants=[(job.get("location") or "", job["url"])])
                    observed.add(key)
                    new_count += not bool(existed)
                    reference = parse_time(publication) if publication else now
                    recent_count += reference >= cutoff
                complete = getattr(jobs, "complete", True)
                record_scan(db, board, uuid.uuid4().hex, started, utc_now(),
                            "complete" if complete else "partial", observed)
                if complete:
                    db.execute("UPDATE boards SET route_status='active' WHERE board_key=?", (board,))
                    db.execute("""UPDATE company_boards SET status='verified',checked_at=?
                      WHERE company_key=? AND board_key=?""", (utc_now(), company, board))
            report["scanned_boards"] += int(complete)
            report["partial_boards"] += int(not complete)
            report["seen"] += len(observed)
            report["new"] += new_count
            report["recent"] += recent_count
        except Exception as error:
            with db:
                record_scan(db, board, uuid.uuid4().hex, started, utc_now(), "failed", set())
            report["failures"].append({"company": company, "board": board,
                                       "error": f"{type(error).__name__}: {error}"})
    report["adapter_pending"] = db.execute("SELECT COUNT(*) FROM companies WHERE company_key NOT IN (SELECT company_key FROM company_boards)").fetchone()[0]
    report["identity_review"] = db.execute("SELECT COUNT(*) FROM company_boards WHERE status='pending_identity'").fetchone()[0]
    report["confirmed_routes"] = db.execute("SELECT COUNT(*) FROM company_boards WHERE status='verified'").fetchone()[0]
    return report
