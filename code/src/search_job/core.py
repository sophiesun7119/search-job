"""Stable opening identity, deterministic title tags, and SQLite writes."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SCHEMA = Path(__file__).with_name("schema.sql")
RULE_VERSION = "title-v1"

CATEGORY_ORDER = (
    ("sde", "Software Engineering — Senior and unspecified"),
    ("sde-entry", "Software Engineering — Junior and New Grad"),
    ("sde-staff", "Software Engineering — Staff and Principal"),
    ("frontend", "Frontend"),
    ("mobile", "Mobile"),
    ("qa-test", "QA and Test"),
    ("analyst", "Analyst"),
    ("scientist", "Scientist and Researcher"),
    ("other", "Other and unclassified"),
)


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA.read_text())
    return db


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password:
        raise ValueError("Official URLs must use HTTPS and have a host")
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                       if not key.lower().startswith("utm_") and key.lower() not in {"ref", "source"}])
    return urlunsplit(("https", parts.netloc.lower(), parts.path.rstrip("/") or "/", query, ""))


def opening_key(provider: str, board_key: str | None, provider_job_id: str | None, url: str) -> str:
    if provider_job_id and board_key:
        source = f"id\x00{provider}\x00{board_key}\x00{provider_job_id}"
    else:
        source = f"url\x00{canonical_url(url)}"
    return hashlib.sha256(source.encode()).hexdigest()[:24]


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_min(a: str | None, b: str | None) -> str | None:
    values = [parse_time(x) for x in (a, b) if x]
    return min(values).isoformat() if values else None


def iso_max(a: str | None, b: str | None) -> str | None:
    values = [parse_time(x) for x in (a, b) if x]
    return max(values).isoformat() if values else None


def classify(title: str) -> tuple[str, str]:
    t = title.casefold()
    if re.search(r"\b(manager|director|head of|vice president|vp|chief|architect|sales|support|presales|account executive|consultant|recruiter)\b", t):
        return "other", "non-development-role"
    if re.search(r"\b(front[ -]?end|frontend|ui engineer|web designer)\b", t):
        return "frontend", "specialist:frontend"
    if re.search(r"\b(ios|android|mobile|react native)\b", t) and re.search(r"\b(engineer|developer|programmer)\b", t):
        return "mobile", "specialist:mobile"
    if re.search(r"\b(qa|quality assurance|test(?:ing|er)?|sdet)\b", t):
        return "qa-test", "specialist:qa-test"
    if re.search(r"\banalysts?\b", t):
        return "analyst", "specialist:analyst"
    if re.search(r"\b(scientists?|researchers?)\b", t):
        return "scientist", "specialist:scientist"
    sde = re.search(r"\b(software engineer(?:ing)?|software developer|sde|swe|developer|programmer|back[ -]?end(?: engineer)?|full[ -]?stack(?: engineer)?|fullstack(?: engineer)?|cloud engineer|platform engineer|infrastructure engineer|systems engineer|sre|site reliability engineer|devops|data engineer|machine learning engineer|ml engineer|ai engineer)\b", t)
    if not sde:
        return "other", "no-title-rule"
    if re.search(r"\b(staff|principal|distinguished)\b", t):
        return "sde-staff", "level:staff-principal"
    if re.search(r"\b(junior|jr\.?|new[ -]?grad|entry[ -]?level|intern(?:ship)?|graduate)\b", t):
        return "sde-entry", "level:entry"
    return "sde", "title:sde"


def classify_level(title: str) -> tuple[str, str]:
    t = title.casefold()
    for pattern, tag in (
        (r"\b(principal|distinguished)\b", "level:principal"),
        (r"\bstaff\b", "level:staff"),
        (r"\b(senior|sr\.?|lead)\b", "level:senior"),
        (r"\b(junior|jr\.?|new[ -]?grad|entry[ -]?level|intern(?:ship)?|graduate)\b", "level:entry"),
    ):
        if re.search(pattern, t):
            return tag, "title:explicit-level"
    return "level:unspecified", "title:no-explicit-level"


def upsert_company(db: sqlite3.Connection, company_key: str, name: str, official_url: str, source: str) -> None:
    db.execute("""INSERT INTO companies VALUES (?,?,?,?)
       ON CONFLICT(company_key) DO UPDATE SET name=excluded.name, official_url=excluded.official_url""",
       (company_key, name, canonical_url(official_url), source))


def upsert_board(db: sqlite3.Connection, board_key: str, provider: str, token: str, url: str | None, status: str = "pending_recheck") -> None:
    db.execute("""INSERT INTO boards(board_key,provider,board_token,board_url,route_status)
       VALUES (?,?,?,?,?) ON CONFLICT(board_key) DO NOTHING""",
       (board_key, provider, token, canonical_url(url) if url else None, status))


def upsert_opening(db: sqlite3.Connection, *, company_key: str, provider: str, board_key: str | None,
                   provider_job_id: str | None, canonical_apply_url: str, title: str,
                   first_seen_at: str, last_seen_at: str, open_state: str = "unknown",
                   source_date_field: str | None = None, source_date_value: str | None = None,
                   source_date_precision: str | None = None, published_at: str | None = None,
                   updated_at: str | None = None, status_evidence: str | None = None,
                   variants: list[tuple[str, str]] | None = None) -> str:
    url = canonical_url(canonical_apply_url)
    key = opening_key(provider, board_key, provider_job_id, url)
    old = db.execute("SELECT * FROM openings WHERE opening_key=?", (key,)).fetchone()
    if old:
        first_seen_at = iso_min(old["first_seen_at"], first_seen_at)
        last_seen_at = iso_max(old["last_seen_at"], last_seen_at)
        earlier_publication = old["published_at"] and (
            not published_at or parse_time(old["published_at"]) <= parse_time(published_at))
        published_at = iso_min(old["published_at"], published_at)
        updated_at = iso_max(old["updated_at"], updated_at)
        if earlier_publication:
            source_date_field = old["source_date_field"]
            source_date_value = old["source_date_value"]
            source_date_precision = old["source_date_precision"]
        if open_state == "unknown":
            open_state = old["open_state"]
        status_evidence = status_evidence or old["status_evidence"]
    db.execute("""INSERT INTO openings(opening_key,company_key,board_key,provider,provider_job_id,
      canonical_url,title,open_state,source_date_field,source_date_value,source_date_precision,
      published_at,updated_at,first_seen_at,last_seen_at,status_evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(opening_key) DO UPDATE SET
        title=excluded.title, open_state=excluded.open_state,
        source_date_field=excluded.source_date_field, source_date_value=excluded.source_date_value,
        source_date_precision=excluded.source_date_precision, published_at=excluded.published_at,
        updated_at=excluded.updated_at, first_seen_at=excluded.first_seen_at,
        last_seen_at=excluded.last_seen_at, status_evidence=excluded.status_evidence""",
      (key, company_key, board_key, provider, provider_job_id, url, title, open_state,
       source_date_field, source_date_value, source_date_precision, published_at, updated_at,
       first_seen_at, last_seen_at, status_evidence))
    for location, apply_url in variants or [("", url)]:
        db.execute("INSERT OR IGNORE INTO opening_variants VALUES (?,?,?)",
                   (key, location, canonical_url(apply_url)))
    category, evidence = classify(title)
    db.execute("DELETE FROM opening_tags WHERE opening_key=? AND (tag IN ('sde','sde-entry','sde-staff','frontend','mobile','qa-test','analyst','scientist','other') OR tag LIKE 'level:%')", (key,))
    db.execute("INSERT INTO opening_tags VALUES (?,?,?,?)", (key, category, RULE_VERSION, evidence))
    level, level_evidence = classify_level(title)
    db.execute("INSERT INTO opening_tags VALUES (?,?,?,?)", (key, level, RULE_VERSION, level_evidence))
    return key


def record_scan(db: sqlite3.Connection, board_key: str, scan_key: str, started_at: str,
                finished_at: str, outcome: str, observed_keys: set[str],
                close_after_complete_misses: int = 2) -> None:
    """Update absence only after a complete scan; partial/failed reads are inert."""
    if outcome not in {"complete", "partial", "failed"}:
        raise ValueError("Unknown scan outcome")
    db.execute("INSERT INTO scan_runs VALUES (?,?,?,?,?,NULL)",
               (scan_key, board_key, started_at, finished_at, outcome))
    if outcome != "complete":
        return
    db.execute("UPDATE boards SET last_complete_scan_at=? WHERE board_key=?", (finished_at, board_key))
    for row in db.execute("SELECT opening_key,missing_complete_scans FROM openings WHERE board_key=?", (board_key,)):
        if row["opening_key"] in observed_keys:
            db.execute("""UPDATE openings SET missing_complete_scans=0,last_seen_at=?,
                          open_state='open',status_evidence='complete-board-scan' WHERE opening_key=?""",
                       (finished_at, row["opening_key"]))
        else:
            misses = row["missing_complete_scans"] + 1
            state = "inactive" if misses >= close_after_complete_misses else None
            db.execute("""UPDATE openings SET missing_complete_scans=?,
                          open_state=COALESCE(?,open_state),
                          status_evidence=CASE WHEN ? IS NOT NULL THEN 'absent-from-complete-scans' ELSE status_evidence END
                          WHERE opening_key=?""", (misses, state, state, row["opening_key"]))
