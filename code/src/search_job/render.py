"""Deterministic Markdown and JSON projections of Search Job's SQLite index."""
from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from .core import CATEGORY_ORDER, parse_time
from .location import is_us_location

SCHEMA_VERSION = 1
INTRO_TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "README-intro.md"


def _cell(value: str) -> str:
    return html.escape(value, quote=False).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")


def _url(value: str) -> str:
    return html.escape(value, quote=True).replace("(", "%28").replace(")", "%29")


def _rows(db: sqlite3.Connection, *, us_only: bool = False,
          recent_as_of: datetime | None = None) -> list[dict]:
    result = []
    for row in db.execute("""SELECT o.*, c.name AS company_name, c.official_url
                               FROM openings o JOIN companies c ON c.company_key=o.company_key"""):
        item = dict(row)
        if recent_as_of is not None:
            published = parse_time(item["published_at"])
            if (item["open_state"] != "open" or item["missing_complete_scans"] != 0 or
                    published is None or not recent_as_of - timedelta(days=3) <= published <= recent_as_of):
                continue
            if item["board_key"] is None or not db.execute("""SELECT 1 FROM company_boards cb
              WHERE cb.company_key=? AND cb.board_key=? AND cb.status='verified'""",
              (item["company_key"], item["board_key"])).fetchone():
                continue
            latest = db.execute("""SELECT outcome FROM scan_runs WHERE board_key=?
              ORDER BY started_at DESC LIMIT 1""", (item["board_key"],)).fetchone()
            if latest is None or latest[0] != "complete":
                continue
        item["variants"] = [dict(v) for v in db.execute(
            "SELECT location, apply_url FROM opening_variants WHERE opening_key=? ORDER BY location,apply_url",
            (row["opening_key"],))]
        if us_only:
            item["variants"] = [v for v in item["variants"] if is_us_location(v["location"])]
            if not item["variants"]:
                continue
        item["tags"] = [dict(t) for t in db.execute(
            "SELECT tag,rule_version,evidence FROM opening_tags WHERE opening_key=? ORDER BY tag",
            (row["opening_key"],))]
        result.append(item)
    return result


def age(row: dict, as_of: datetime) -> tuple[int, bool, bool]:
    discovered = not bool(row["published_at"])
    value = row["first_seen_at"] if discovered else row["published_at"]
    timestamp = parse_time(value)
    if timestamp is None:
        raise ValueError("An opening needs a reference time")
    day_only = row["source_date_precision"] in {"date", "day"} and not discovered
    elapsed = (as_of.date() - timestamp.date()).days if day_only else int((as_of - timestamp).total_seconds() // 86400)
    return max(elapsed, 0), discovered, day_only


def _sort(rows: list[dict], as_of: datetime) -> list[dict]:
    return sorted(rows, key=lambda row: (
        -(parse_time(row["published_at"] or row["first_seen_at"]).timestamp()),
        row["opening_key"]))


def _table(rows: list[dict], as_of: datetime, *, inactive: bool = False) -> str:
    lines = ["| Company | Role | Location | Application | Age |",
             "| --- | --- | --- | --- | --- |"]
    for row in _sort(rows, as_of):
        days, discovered, day_only = age(row, as_of)
        marker = " 🔎" if discovered else (" †" if day_only else "")
        locations = sorted({v["location"] for v in row["variants"] if v["location"]})
        location = ", ".join(_cell(x) for x in locations) if locations else "—"
        if inactive:
            application = "Closed"
        else:
            links = list(dict.fromkeys(v["apply_url"] for v in row["variants"]))
            application = "<br>".join(f"[Apply]({_url(link)})" for link in links) if links else "—"
        lines.append(f"| [{_cell(row['company_name'])}]({_url(row['official_url'])}) | "
                     f"{_cell(row['title'])} | {location} | {application} | {days}d{marker} |")
    return "\n".join(lines)


def render_markdown(db: sqlite3.Connection, as_of: datetime, *, historical_preview: bool = False) -> str:
    rows = _rows(db, us_only=not historical_preview,
                 recent_as_of=None if historical_preview else as_of)
    companies_total = db.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    companies_with_rows = len({row["company_key"] for row in rows})
    categories = {key: [row for row in rows if any(tag["tag"] == key for tag in row["tags"])]
                  for key, _ in CATEGORY_ORDER}
    intro = INTRO_TEMPLATE.read_text()
    if intro.count("{{SNAPSHOT_STATUS}}\n\n") != 1:
        raise ValueError("README intro template needs exactly one snapshot status slot")
    if historical_preview:
        status = ("> **Historical preview — open status not verified.** These saved postings came from an earlier cache. Their links and availability have not been checked in this run. This page demonstrates the proposed layout; it is not a current openings feed.\n"
                  f"> Saved scope: {companies_total} known companies; {companies_with_rows} have {len(rows)} cached ATS postings. Companies without saved postings are not evidence of no openings. Locations were not stored in the old cache and appear as —.")
    else:
        status = ""
    coverage = f"**{companies_total}** {'company' if companies_total == 1 else 'companies'}"
    intro = intro.replace("{{COMPANY_COVERAGE}}", coverage)
    lines = intro.replace("{{SNAPSHOT_STATUS}}\n\n", status + "\n\n" if status else "").rstrip().splitlines() + [""]
    lines += ["<details>", "<summary>How this list is selected</summary>", ""]
    if not historical_preview:
        lines += ["Only currently open postings seen in the latest complete board scan, with an ATS publication timestamp within the past 72 hours and a confirmed US location, are shown here. Older, closed, non-US, and uncertain postings remain in the database and full JSON export.", ""]
    age_explanation = ("Age is shown in days. 🔎 means age since **first discovery**, not ATS publication. "
                       if historical_preview else "Age is shown in days from the ATS publication date. ")
    listing_kind = "saved job" if historical_preview else "opening"
    listing_count = f"{len(rows)} {listing_kind}{'' if len(rows) == 1 else 's'}"
    lines += [age_explanation + "† means the ATS supplied a date without an exact time. `0d` is within 24 hours only for exact timestamps; for date-only sources it means the same calendar date.",
              "", "</details>", "", "<a id=\"categories\"></a>",
              f"## Browse {listing_count} by category", ""]
    for key, label in CATEGORY_ORDER:
        active = sum(row["open_state"] == "open" for row in categories[key])
        unknown = sum(row["open_state"] == "unknown" for row in categories[key])
        inactive = sum(row["open_state"] == "inactive" for row in categories[key])
        if active + unknown + inactive:
            count = active + unknown + inactive
            lines.append(f"- [{label}](#{key}) ({count})")
    lines.append("")
    for key, label in CATEGORY_ORDER:
        group = categories[key]
        if not group:
            continue
        lines += [f'<a id="{key}"></a>', f"## {label}", "", "[Back to top](#search-job)", ""]
        current = [row for row in group if row["open_state"] == "open"]
        unknown = [row for row in group if row["open_state"] == "unknown"]
        inactive = [row for row in group if row["open_state"] == "inactive"]
        if current:
            lines += [_table(current, as_of), ""]
        if unknown:
            if key == "other" and historical_preview:
                lines += [f"<details><summary>Saved, unclassified postings ({len(unknown)})</summary>", "",
                          _table(unknown, as_of), "", "</details>", ""]
            else:
                lines += ["**Saved postings — current availability unverified**", "", _table(unknown, as_of), ""]
        if inactive:
            lines += [f"<details><summary>Inactive roles ({len(inactive)})</summary>", "",
                      _table(inactive, as_of, inactive=True), "", "</details>", ""]
    if not rows:
        lines += ["No openings have been indexed yet.", ""]
    return "\n".join(lines)


def render_json(db: sqlite3.Connection, as_of: datetime) -> str:
    rows = _rows(db)
    payload = {"schema_version": SCHEMA_VERSION, "generated_at": as_of.isoformat(),
               "openings": []}
    for row in sorted(rows, key=lambda item: item["opening_key"]):
        payload["openings"].append({key: row[key] for key in (
            "opening_key", "company_key", "company_name", "official_url", "board_key", "provider",
            "provider_job_id", "canonical_url", "title", "open_state", "source_date_field",
            "source_date_value", "source_date_precision", "published_at", "updated_at",
            "first_seen_at", "last_seen_at", "status_evidence", "variants", "tags")})
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_outputs(db: sqlite3.Connection, markdown_path: Path, json_path: Path, as_of: datetime,
                  *, historical_preview: bool = False) -> None:
    markdown_path.write_text(render_markdown(db, as_of, historical_preview=historical_preview))
    json_path.write_text(render_json(db, as_of))
