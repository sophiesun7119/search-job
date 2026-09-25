"""Deterministic Markdown and JSON projections of Search Job's SQLite index."""
from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from .core import CATEGORY_ORDER, parse_time

SCHEMA_VERSION = 1
INTRO_TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "README-intro.md"


def _cell(value: str) -> str:
    return html.escape(value, quote=False).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")


def _url(value: str) -> str:
    return html.escape(value, quote=True).replace("(", "%28").replace(")", "%29")


def _rows(db: sqlite3.Connection) -> list[dict]:
    result = []
    for row in db.execute("""SELECT o.*, c.name AS company_name, c.official_url
                               FROM openings o JOIN companies c ON c.company_key=o.company_key"""):
        item = dict(row)
        item["variants"] = [dict(v) for v in db.execute(
            "SELECT location, apply_url FROM opening_variants WHERE opening_key=? ORDER BY location,apply_url",
            (row["opening_key"],))]
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
    rows = _rows(db)
    companies_total = db.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    companies_with_rows = len({row["company_key"] for row in rows})
    categories = {key: [row for row in rows if any(tag["tag"] == key for tag in row["tags"])]
                  for key, _ in CATEGORY_ORDER}
    intro = INTRO_TEMPLATE.read_text()
    if intro.count("{{SNAPSHOT_STATUS}}\n\n") != 1:
        raise ValueError("README intro template needs exactly one snapshot status slot")
    if historical_preview:
        status = ("> **Historical preview — open status not verified.** These saved postings came from an earlier private experiment. Their links and availability have not been checked in this run. This page demonstrates the proposed layout; it is not a current openings feed.\n"
                  f"> Saved scope: {companies_total} known companies; {companies_with_rows} have {len(rows)} cached ATS postings. Companies without saved postings are not evidence of no openings. Locations were not stored in the old cache and appear as —.")
    else:
        status = ""
    lines = intro.replace("{{SNAPSHOT_STATUS}}\n\n", status + "\n\n" if status else "").rstrip().splitlines() + [""]
    lines += [f"Generated: {as_of.isoformat()}.", "",
              "Age is shown in days. 🔎 means age since **first discovery**, not ATS publication. † means the ATS supplied a date without an exact time. `0d` is within 24 hours only for exact timestamps; for date-only sources it means the same calendar date.",
              "", "## Categories", ""]
    for key, label in CATEGORY_ORDER:
        active = sum(row["open_state"] == "open" for row in categories[key])
        unknown = sum(row["open_state"] == "unknown" for row in categories[key])
        inactive = sum(row["open_state"] == "inactive" for row in categories[key])
        if active + unknown + inactive:
            counts = (f"{unknown} saved / unverified" if historical_preview
                      else f"{active} open, {unknown} unverified, {inactive} inactive")
            lines.append(f"- [{label}](#{key}): {counts}")
    lines.append("")
    for key, label in CATEGORY_ORDER:
        group = categories[key]
        if not group:
            continue
        lines += [f'<a id="{key}"></a>', f"## {label}", ""]
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
