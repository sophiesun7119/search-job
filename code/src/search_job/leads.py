"""Import a bounded, resumable Simplify lead batch without trusting its ATS links."""
from __future__ import annotations

import re
import sqlite3
import html
import json
import ssl
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from .core import upsert_board, upsert_company
from .collectors import ACTIVE_COLLECTORS

try:
    import certifi
except ImportError:
    certifi = None


def recognize_apply_url(url: str) -> tuple[str, str | None]:
    """Return a provider and candidate board token, never a verified route."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = [unquote(part) for part in parts.path.split("/") if part]
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        return "greenhouse", path[0] if path else None
    if host == "jobs.ashbyhq.com":
        return "ashby", path[0] if path else None
    if host == "api.ashbyhq.com" and path[:2] == ["posting-api", "job-board"]:
        return "ashby", path[2] if len(path) > 2 else None
    if host == "jobs.smartrecruiters.com":
        return "smartrecruiters", path[0] if path else None
    if host == "jobs.gem.com":
        return "gem", path[0] if path else None
    if host == "ats.rippling.com":
        return "rippling", path[0] if path else None
    if host == "vizi.vizirecruiter.com":
        return "vizirecruiter", path[0] if path else None
    if host == "jobs.lever.co":
        return "lever", path[0] if path else None
    if re.fullmatch(r"[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com", host):
        paths = path[1:] if path and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", path[0]) else path
        return "workday", f"{host}|{host.split('.')[0]}|{paths[0]}" if paths else None
    if re.fullmatch(r"wd\d+\.myworkdaysite\.com", host):
        return "workday", f"{host}|{path[1]}|{path[2]}" if len(path) > 2 and path[0] == "recruiting" else None
    if host == "apply.workable.com":
        return "workable", path[0] if path else None
    if host.endswith(".applytojob.com"):
        return "jazzhr", host
    if host.endswith(".icims.com"):
        return "icims", host
    if host.endswith(".oraclecloud.com") or host.endswith(".fa.oraclecloud.com"):
        if "sites" in path and path.index("sites") + 1 < len(path):
            return "oracle", f"{host}|{path[path.index('sites') + 1]}"
        return "oracle", None
    if host.endswith(".pinpointhq.com"):
        return "pinpoint", host
    if host.endswith(".eightfold.ai"):
        return "eightfold", host
    return "unknown", None


def import_simplify_catalog(db: sqlite3.Connection, catalog_path: Path, *,
                            limit: int, year: int = 2026) -> dict:
    """Select the next unimported company leads in source-id order.

    Only public source evidence is copied. A third-party Apply URL supplies a
    provider hint but cannot by itself create a verified company or board.
    """
    if limit < 1 or year < 2000:
        raise ValueError("Invalid Simplify batch selection")
    source = sqlite3.connect(f"file:{catalog_path.resolve()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    known_names = {row[0].casefold() for row in db.execute("SELECT name FROM companies")}
    known_ids = {row[0] for row in db.execute("SELECT source_id FROM source_leads WHERE source_name='simplify'")}
    selected = []
    try:
        rows = source.execute("""SELECT c.id,c.name,c.best_apply_url,c.best_year,
          (SELECT o.profile_url FROM observations o WHERE o.company_id=c.id
           AND o.source_year=c.best_year AND o.apply_url=c.best_apply_url
           ORDER BY o.id LIMIT 1) AS profile_url,
          (SELECT o.source_url FROM observations o WHERE o.company_id=c.id
           AND o.source_year=c.best_year AND o.apply_url=c.best_apply_url
           ORDER BY o.id LIMIT 1) AS source_url,
          (SELECT o.title FROM observations o WHERE o.company_id=c.id
           AND o.source_year=c.best_year AND o.apply_url=c.best_apply_url
           ORDER BY o.id LIMIT 1) AS title,
          (SELECT o.location FROM observations o WHERE o.company_id=c.id
           AND o.source_year=c.best_year AND o.apply_url=c.best_apply_url
           ORDER BY o.id LIMIT 1) AS location
          FROM companies c WHERE c.status='pending' AND c.best_year=?
            AND c.best_apply_url IS NOT NULL ORDER BY c.id""", (year,))
        for row in rows:
            if str(row["id"]) in known_ids or row["name"].casefold() in known_names:
                continue
            selected.append(row)
            if len(selected) == limit:
                break
    finally:
        source.close()
    providers = Counter()
    with db:
        for row in selected:
            provider, board = recognize_apply_url(row["best_apply_url"])
            providers[provider] += 1
            db.execute("""INSERT INTO source_leads
              (lead_key,source_name,source_id,name,source_year,source_url,profile_url,
               sample_apply_url,sample_title,sample_location,provider_hint,board_hint,stage)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (f"simplify:{row['id']}", "simplify", str(row["id"]), row["name"],
               row["best_year"], row["source_url"], row["profile_url"],
               row["best_apply_url"], row["title"], row["location"],
               provider, board, "route_pending"))
    return {"selected": len(selected), "year": year,
            "source_ids": [row["id"] for row in selected],
            "provider_hints": dict(sorted(providers.items()))}


def official_domain_from_profile(body: str) -> str | None:
    """Extract a company-site candidate from public Simplify JSON-LD."""
    excluded = ("simplify.jobs", "linkedin.com", "facebook.com", "instagram.com",
                "twitter.com", "x.com", "youtube.com", "crunchbase.com")
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                          body, re.I | re.S):
        try:
            data = json.loads(html.unescape(raw))
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            links = item.get("sameAs") or []
            if isinstance(links, str):
                links = [links]
            for link in links:
                parts = urlsplit(link)
                host = (parts.hostname or "").lower().removeprefix("www.")
                if parts.scheme == "https" and host and not any(
                        host == item or host.endswith("." + item) for item in excluded):
                    return host
    return None


def _profile_domain(url: str) -> str | None:
    if urlsplit(url).hostname not in {"simplify.jobs", "www.simplify.jobs"}:
        raise ValueError("Expected a Simplify company profile URL")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    context = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=20, context=context) as response:
        body = response.read(2_000_000).decode("utf-8", "ignore")
    return official_domain_from_profile(body)


def resolve_simplify_profiles(db: sqlite3.Connection, *, limit: int = 100,
                              workers: int = 8) -> dict:
    """Save candidate official domains; route ownership still needs verification."""
    if limit < 1 or not 1 <= workers <= 16:
        raise ValueError("Invalid profile resolution batch")
    rows = db.execute("""SELECT lead_key,profile_url FROM source_leads
      WHERE source_name='simplify' AND stage='route_pending' AND official_url IS NULL
      ORDER BY CAST(source_id AS INTEGER) LIMIT ?""", (limit,)).fetchall()
    outcomes = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_profile_domain, row["profile_url"]): row["lead_key"] for row in rows}
        for future in as_completed(futures):
            key = futures[future]
            try:
                domain = future.result()
                error = None if domain else "Simplify profile has no official domain"
            except Exception as exc:
                domain = None
                error = f"{type(exc).__name__}: {exc}"[:300]
            outcomes.append((key, domain, error))
    stamp = datetime.now(timezone.utc).isoformat()
    with db:
        for key, domain, error in outcomes:
            db.execute("""UPDATE source_leads SET official_url=?,last_error=?,checked_at=?
              WHERE lead_key=?""", (f"https://{domain}/" if domain else None, error, stamp, key))
    return {"attempted": len(outcomes), "domains_found": sum(domain is not None for _, domain, _ in outcomes),
            "unresolved": [{"lead": key, "error": error} for key, domain, error in sorted(outcomes)
                           if domain is None]}


class _PageLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"a", "iframe", "form"}:
            values = dict(attrs)
            url = values.get("href") or values.get("src") or values.get("action")
            if url:
                self.urls.append(url)


def _site_page(url: str) -> tuple[str, list[str]]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    context = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=15, context=context) as response:
        final_url = response.url
        body = response.read(1_500_000).decode("utf-8", "ignore")
    parser = _PageLinks()
    parser.feed(body)
    # Some company sites embed job links in JSON rather than anchors.
    raw_urls = parser.urls + re.findall(r'https?://[^\s"\'<>\\]+', body.replace("\\/", "/"))
    ashby_variable = re.search(r"(?:const|let)\s+ashbyCompany\s*=\s*['\"]([A-Za-z0-9_-]+)['\"]", body)
    if ashby_variable and "api.ashbyhq.com/posting-api/job-board/${ashbyCompany}" in body:
        raw_urls.append("https://api.ashbyhq.com/posting-api/job-board/" + ashby_variable.group(1))
    links = []
    for value in raw_urls:
        try:
            if len(value) <= 500:
                links.append(urljoin(final_url, html.unescape(value)))
        except ValueError:
            continue
    return final_url, links


def _official_route(lead: dict) -> dict:
    official = lead["official_url"]
    host = (urlsplit(official).hostname or "").lower()
    base_domain = ".".join(host.split(".")[-2:])
    visited: set[str] = set()
    todo = [official]
    routes: dict[tuple[str, str], tuple[str, str]] = {}
    errors = []
    while todo and len(visited) < 5:
        page = todo.pop(0)
        if page in visited:
            continue
        visited.add(page)
        try:
            final_url, links = _site_page(page)
        except Exception as exc:
            errors.append(f"{page}: {type(exc).__name__}: {exc}"[:180])
            continue
        for link in [final_url, *links]:
            try:
                parts = urlsplit(link)
            except ValueError:
                continue
            if parts.scheme != "https" or not parts.hostname:
                continue
            provider, board = recognize_apply_url(link)
            if provider != "unknown" and board:
                routes.setdefault((provider, board), (final_url, link))
            elif (parts.hostname == host or parts.hostname.endswith("." + base_domain) or
                  parts.hostname == base_domain):
                if re.search(r"career|/jobs?(?:/|$)|opportunit|join-us|work-with-us", parts.path, re.I):
                    if link not in visited and link not in todo and len(todo) < 8:
                        todo.append(link)
        if len(visited) == 1 and not todo:
            todo.append(urljoin(official, "/careers"))
    hint = (lead["provider_hint"], lead["board_hint"])
    selected = routes.get(hint)
    if selected:
        provider, board = hint
    elif len(routes) == 1:
        (provider, board), selected = next(iter(routes.items()))
    else:
        return {"stage": "board_pending" if routes else "route_pending",
                "error": ("Multiple official ATS routes need attribution" if routes else
                          "; ".join(errors[:2]) or "No ATS route found on official careers pages"),
                "route_count": len(routes)}
    return {"stage": "adapter_pending" if provider not in ACTIVE_COLLECTORS else "scan_pending",
            "provider": provider, "board": board,
        "evidence_page": selected[0], "board_url": selected[1]}


def verify_official_routes(db: sqlite3.Connection, *, provider_hint: str | None = None,
                           limit: int = 100, workers: int = 8) -> dict:
    """Follow official company pages and save only evidence-backed board routes."""
    if limit < 1 or not 1 <= workers <= 16:
        raise ValueError("Invalid route verification batch")
    rows = [dict(row) for row in db.execute("""SELECT * FROM source_leads
      WHERE official_url IS NOT NULL AND stage='route_pending'
        AND (? IS NULL OR provider_hint=?)
      ORDER BY CAST(source_id AS INTEGER) LIMIT ?""", (provider_hint, provider_hint, limit))]
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_official_route, lead): lead for lead in rows}
        for future in as_completed(futures):
            lead = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"stage": "route_pending", "error": f"{type(exc).__name__}: {exc}"[:300]}
            results.append((lead, result))
    stamp = datetime.now(timezone.utc).isoformat()
    with db:
        for lead, result in results:
            stage = result["stage"]
            provider, board = result.get("provider"), result.get("board")
            company_key = None
            if stage == "scan_pending":
                company_key = (urlsplit(lead["official_url"]).hostname or "").lower().removeprefix("www.")
                upsert_company(db, company_key, lead["name"], lead["official_url"],
                               f"simplify:{lead['source_year']}")
                board_key = f"{provider}:{board}"
                upsert_board(db, board_key, provider, board, result["board_url"])
                db.execute("""INSERT INTO company_boards(company_key,board_key,evidence_url,status)
                  VALUES (?,?,?,'pending_recheck')
                  ON CONFLICT(company_key,board_key) DO NOTHING""",
                  (company_key, board_key, result["evidence_page"]))
            db.execute("""UPDATE source_leads SET stage=?,company_key=?,
              provider_hint=COALESCE(?,provider_hint),board_hint=COALESCE(?,board_hint),
              route_evidence_url=?,official_board_url=?,last_error=?,checked_at=? WHERE lead_key=?""",
              (stage, company_key, provider, board, result.get("evidence_page"),
               result.get("board_url"),
               result.get("error"), stamp, lead["lead_key"]))
    counts = Counter(result["stage"] for _, result in results)
    return {"checked": len(results), "stages": dict(sorted(counts.items())),
            "unresolved": [{"lead": lead["lead_key"], "stage": result["stage"],
                             "error": result.get("error")} for lead, result in results
                            if result["stage"] in {"route_pending", "board_pending"}]}


def activate_tested_adapter(db: sqlite3.Connection, provider: str) -> dict:
    """Register official routes only after their provider collector has passed a live test."""
    if provider not in ACTIVE_COLLECTORS:
        raise ValueError("Adapter has not been approved for lead activation")
    rows = db.execute("""SELECT * FROM source_leads WHERE stage='adapter_pending'
      AND provider_hint=? AND board_hint IS NOT NULL AND route_evidence_url IS NOT NULL""",
      (provider,)).fetchall()
    stamp = datetime.now(timezone.utc).isoformat()
    with db:
        for lead in rows:
            company_key = (urlsplit(lead["official_url"]).hostname or "").lower().removeprefix("www.")
            upsert_company(db, company_key, lead["name"], lead["official_url"],
                           f"simplify:{lead['source_year']}")
            board_key = f"{provider}:{lead['board_hint']}"
            board_url = lead["official_board_url"] or (
                f"https://{lead['board_hint']}/apply" if provider == "jazzhr"
                else lead["sample_apply_url"])
            upsert_board(db, board_key, provider, lead["board_hint"], board_url)
            db.execute("""INSERT INTO company_boards(company_key,board_key,evidence_url,status)
              VALUES (?,?,?,'pending_recheck') ON CONFLICT(company_key,board_key) DO NOTHING""",
              (company_key, board_key, lead["route_evidence_url"]))
            db.execute("""UPDATE source_leads SET stage='scan_pending',company_key=?,
              last_error=NULL,checked_at=? WHERE lead_key=?""", (company_key, stamp, lead["lead_key"]))
    return {"provider": provider, "activated_routes": len(rows)}
