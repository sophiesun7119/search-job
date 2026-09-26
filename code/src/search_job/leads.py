"""Import a bounded, resumable Simplify lead batch without trusting its ATS links."""
from __future__ import annotations

import re
import sqlite3
import html
import json
import ssl
import urllib.request
import urllib.error
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
    if host == "boards-api.greenhouse.io" and len(path) >= 4 and path[:2] == ["v1", "boards"] and path[3] == "jobs":
        return "greenhouse", path[2]
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
    if host == "app.careerpuck.com" and len(path) >= 2 and path[0] == "job-board":
        return "careerpuck", path[1]
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
        rows = source.execute("""SELECT c.id,c.name,c.best_apply_url,c.best_year,c.canonical_domain,
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
            source_domain = (row["canonical_domain"] or "").strip().lower()
            source_company_url = (f"https://{source_domain}/" if source_domain and
                                  re.fullmatch(r"[a-z0-9.-]+", source_domain) else None)
            providers[provider] += 1
            db.execute("""INSERT INTO source_leads
              (lead_key,source_name,source_id,name,source_year,source_url,profile_url,
               source_company_url,official_url,sample_apply_url,sample_title,sample_location,
               provider_hint,board_hint,stage)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (f"simplify:{row['id']}", "simplify", str(row["id"]), row["name"],
               row["best_year"], row["source_url"], row["profile_url"],
               source_company_url, source_company_url, row["best_apply_url"],
               row["title"], row["location"],
               provider, board, "route_pending"))
    return {"selected": len(selected), "year": year,
            "source_ids": [row["id"] for row in selected],
            "provider_hints": dict(sorted(providers.items()))}


def _probe_sample(url: str) -> tuple[str | None, int | None, str | None]:
    if urlsplit(url).scheme != "https":
        return None, None, "Sample Apply URL is not HTTPS"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    context = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=15, context=context) as response:
            response.read(1)
            return response.url, response.status, None
    except urllib.error.HTTPError as exc:
        return exc.url, exc.code, f"HTTP {exc.code}"
    except Exception as exc:
        return None, None, f"{type(exc).__name__}: {exc}"[:300]


def probe_saved_samples(db: sqlite3.Connection, *, limit: int = 100, workers: int = 8) -> dict:
    """Check saved third-party Apply URLs; never promote a route from this alone."""
    if limit < 1 or not 1 <= workers <= 16:
        raise ValueError("Invalid sample probe batch")
    rows = db.execute("""SELECT lead_key,sample_apply_url,stage,route_evidence_url FROM source_leads
      WHERE stage!='scanned' AND sample_apply_url IS NOT NULL
      ORDER BY CAST(source_id AS INTEGER) LIMIT ?""", (limit,)).fetchall()
    outcomes = []
    originals = {row["lead_key"]: row for row in rows}
    original_urls = {key: row["sample_apply_url"] for key, row in originals.items()}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_probe_sample, row["sample_apply_url"]): row["lead_key"] for row in rows}
        for future in as_completed(futures):
            outcomes.append((futures[future], *future.result()))
    stamp = datetime.now(timezone.utc).isoformat()
    with db:
        for key, final_url, status, error in outcomes:
            original_provider, original_board = recognize_apply_url(original_urls[key])
            final_provider, final_board = recognize_apply_url(final_url) if final_url else ("unknown", None)
            provider, board = ((final_provider, final_board) if final_provider != "unknown" and final_board
                               else (original_provider, original_board))
            can_update_hint = originals[key]["stage"] == "route_pending" and not originals[key]["route_evidence_url"]
            db.execute("""UPDATE source_leads SET sample_probe_url=?,sample_probe_status=?,
              sample_probe_error=?,sample_probe_at=?,
              provider_hint=CASE WHEN ? THEN COALESCE(?,provider_hint) ELSE provider_hint END,
              board_hint=CASE WHEN ? THEN COALESCE(?,board_hint) ELSE board_hint END
              WHERE lead_key=?""",
              (final_url, status, error, stamp, can_update_hint,
               provider if provider != "unknown" else None, can_update_hint, board, key))
    return {"checked": len(outcomes), "http_statuses": dict(sorted(Counter(
        str(status) if status is not None else "network_error"
        for _, _, status, _ in outcomes).items())),
        "redirected": sum(bool(final_url and final_url != original_urls[key])
            for key, final_url, _, _ in outcomes),
        "recognized_ats": sum((recognize_apply_url(final_url)[0] != "unknown" if final_url else False)
            or recognize_apply_url(original_urls[key])[0] != "unknown"
            for key, final_url, _, _ in outcomes)}


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
    rows = db.execute("""SELECT lead_key,profile_url,review_state FROM source_leads
      WHERE source_name='simplify' AND stage='route_pending' AND official_url IS NULL
      ORDER BY CAST(source_id AS INTEGER) LIMIT ?""", (limit,)).fetchall()
    outcomes = []
    prior_states = {row["lead_key"]: row["review_state"] for row in rows}
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
            candidate = f"https://{domain}/" if domain else None
            db.execute("""UPDATE source_leads SET official_url=?,profile_company_url=COALESCE(profile_company_url,?),
              last_error=?,checked_at=?,review_state=?,review_updated_at=? WHERE lead_key=?""",
              (candidate, candidate, error, stamp,
               ("script_pending" if candidate else
                prior_states[key] if prior_states[key] in {"ai_in_progress", "needs_user"} else "ai_pending"),
               stamp, key))
    return {"attempted": len(outcomes), "domains_found": sum(domain is not None for _, domain, _ in outcomes),
            "unresolved": [{"lead": key, "error": error} for key, domain, error in sorted(outcomes)
                           if domain is None]}


def preserve_profile_company_links(db: sqlite3.Connection, *, limit: int = 100,
                                   workers: int = 8) -> dict:
    """Preserve the website from each original Simplify profile, without changing current route decisions."""
    if limit < 1 or not 1 <= workers <= 16:
        raise ValueError("Invalid profile link batch")
    rows = db.execute("""SELECT lead_key,profile_url FROM source_leads
      WHERE source_name='simplify' AND profile_url IS NOT NULL AND profile_company_url IS NULL
      ORDER BY CAST(source_id AS INTEGER) LIMIT ?""", (limit,)).fetchall()
    outcomes = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_profile_domain, row["profile_url"]): row["lead_key"] for row in rows}
        for future in as_completed(futures):
            try:
                domain = future.result()
            except Exception:
                domain = None
            outcomes.append((futures[future], domain))
    with db:
        for key, domain in outcomes:
            if domain:
                db.execute("UPDATE source_leads SET profile_company_url=? WHERE lead_key=?",
                           (f"https://{domain}/", key))
    return {"attempted": len(outcomes), "preserved": sum(bool(domain) for _, domain in outcomes),
            "unavailable": [key for key, domain in sorted(outcomes) if not domain]}


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
                           lead_key: str | None = None,
                           limit: int = 100, workers: int = 8) -> dict:
    """Follow official company pages and save only evidence-backed board routes."""
    if limit < 1 or not 1 <= workers <= 16:
        raise ValueError("Invalid route verification batch")
    rows = [dict(row) for row in db.execute("""SELECT * FROM source_leads
      WHERE official_url IS NOT NULL AND stage='route_pending'
        AND (? IS NULL OR provider_hint=?) AND (? IS NULL OR lead_key=?)
      ORDER BY CAST(source_id AS INTEGER) LIMIT ?""",
      (provider_hint, provider_hint, lead_key, lead_key, limit))]
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
              route_evidence_url=?,route_resolution_method=CASE WHEN ? IS NOT NULL THEN 'script_official_page' ELSE route_resolution_method END,
              official_board_url=?,last_error=?,checked_at=?,review_state=?,review_updated_at=? WHERE lead_key=?""",
              (stage, company_key, provider, board, result.get("evidence_page"),
               result.get("evidence_page"), result.get("board_url"),
               result.get("error"), stamp,
               ("resolved" if stage == "scan_pending" else "ai_pending" if stage == "adapter_pending" else
                lead["review_state"] if lead["review_state"] in {"ai_in_progress", "needs_user"}
                else "ai_pending"), stamp, lead["lead_key"]))
    counts = Counter(result["stage"] for _, result in results)
    return {"checked": len(results), "stages": dict(sorted(counts.items())),
            "unresolved": [{"lead": lead["lead_key"], "stage": result["stage"],
                             "error": result.get("error")} for lead, result in results
                            if result["stage"] in {"route_pending", "board_pending"}]}


def route_resolution_report(db: sqlite3.Connection) -> dict:
    """Separate sample clues from script, AI, and user-confirmed official routes."""
    rows = db.execute("SELECT * FROM source_leads WHERE source_name='simplify'").fetchall()
    methods = Counter(row["route_resolution_method"] or "unattributed_prior" for row in rows
                      if row["route_evidence_url"])
    sample_matches = Counter()
    for row in rows:
        if not row["route_evidence_url"]:
            continue
        sample_provider, sample_board = recognize_apply_url(row["sample_apply_url"] or "")
        sample_matches["exact_board" if (sample_provider, sample_board) ==
                       (row["provider_hint"], row["board_hint"]) else
                       "different_or_unknown"] += 1
    return {"official_routes_by_method": dict(sorted(methods.items())),
            "sample_hint_vs_official": dict(sorted(sample_matches.items())),
            "review_states": dict(sorted(Counter(row["review_state"] for row in rows
                if row["stage"] != "scanned").items())),
            "unresolved_by_stage": dict(sorted(Counter(row["stage"] for row in rows
                if row["stage"] not in {"scanned", "scan_pending"}).items()))}


def mark_ai_review(db: sqlite3.Connection, lead_key: str, *, outcome: str, note: str) -> dict:
    """Record an actual AI attempt; only a failed attempt can request user review."""
    states = {"investigating": "ai_in_progress", "needs-user": "needs_user"}
    if outcome not in states or not note.strip():
        raise ValueError("AI review needs an outcome and a concrete evidence/blocker note")
    lead = db.execute("SELECT stage FROM source_leads WHERE lead_key=?", (lead_key,)).fetchone()
    if not lead or lead["stage"] not in {"route_pending", "board_pending", "adapter_pending"}:
        raise ValueError("Only unresolved leads can enter AI review")
    stamp = datetime.now(timezone.utc).isoformat()
    with db:
        db.execute("""UPDATE source_leads SET review_state=?,ai_review_note=?,ai_reviewed_at=?,
          review_updated_at=? WHERE lead_key=?""",
          (states[outcome], note.strip()[:1000], stamp, stamp, lead_key))
    return {"lead": lead_key, "review_state": states[outcome]}


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
              last_error=NULL,checked_at=?,review_state='resolved',review_updated_at=? WHERE lead_key=?""",
              (company_key, stamp, stamp, lead["lead_key"]))
    return {"provider": provider, "activated_routes": len(rows)}


def confirm_official_route(db: sqlite3.Connection, lead_key: str, *,
                           evidence_url: str, board_url: str,
                           confirmation_source: str = "ai") -> dict:
    """Record an AI or user-reviewed official page/link when automated page reads fail.

    The caller must have inspected the official page and verified that it links
    to this exact ATS board. This function enforces URL/domain and provider
    shape, but cannot replace that source inspection.
    """
    lead = db.execute("SELECT * FROM source_leads WHERE lead_key=?", (lead_key,)).fetchone()
    if confirmation_source not in {"ai", "user"}:
        raise ValueError("Confirmation source must be ai or user")
    if lead is None or lead["stage"] not in {"route_pending", "board_pending"}:
        raise ValueError("Lead is absent or not awaiting route evidence")
    official_host = (urlsplit(lead["official_url"] or "").hostname or "").lower().removeprefix("www.")
    evidence = urlsplit(evidence_url)
    evidence_host = (evidence.hostname or "").lower().removeprefix("www.")
    if (not official_host or evidence.scheme != "https" or
            not (evidence_host == official_host or evidence_host.endswith("." + official_host))):
        raise ValueError("Evidence page must be on the candidate official company domain")
    provider, board = recognize_apply_url(board_url)
    if urlsplit(board_url).scheme != "https" or provider == "unknown" or not board:
        raise ValueError("Board URL must identify a supported or planned ATS route")
    stage = "scan_pending" if provider in ACTIVE_COLLECTORS else "adapter_pending"
    company_key = official_host if stage == "scan_pending" else None
    stamp = datetime.now(timezone.utc).isoformat()
    with db:
        if company_key:
            upsert_company(db, company_key, lead["name"], lead["official_url"],
                           f"simplify:{lead['source_year']}")
            board_key = f"{provider}:{board}"
            upsert_board(db, board_key, provider, board, board_url)
            db.execute("""INSERT INTO company_boards(company_key,board_key,evidence_url,status)
              VALUES (?,?,?,'pending_recheck') ON CONFLICT(company_key,board_key) DO NOTHING""",
              (company_key, board_key, evidence_url))
        db.execute("""UPDATE source_leads SET stage=?,company_key=?,provider_hint=?,board_hint=?,
          route_evidence_url=?,route_resolution_method=?,official_board_url=?,last_error=NULL,
          checked_at=?,review_state=?,review_updated_at=? WHERE lead_key=?""",
          (stage, company_key, provider, board, evidence_url,
           f"{confirmation_source}_official_page", board_url, stamp,
           "resolved" if stage == "scan_pending" else "ai_pending", stamp, lead_key))
    return {"lead": lead_key, "provider": provider, "board": board, "stage": stage,
            "route_resolution_method": f"{confirmation_source}_official_page"}
