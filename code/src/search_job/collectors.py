"""Public ATS listing readers, adapted from the earlier local collectors.

All listing pages are read before a board is called complete. No personal title,
location, or date filter runs here. Provider dates are not silently inferred from
updated timestamps.
"""
from __future__ import annotations

import json
import re
import ssl
import html
import urllib.request
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

try:
    import certifi
except ImportError:  # system trust store remains usable
    certifi = None

ACTIVE_COLLECTORS = frozenset({"greenhouse", "ashby", "smartrecruiters", "gem",
                               "rippling", "vizirecruiter", "eightfold", "lever",
                               "workday", "workable", "jazzhr"})
PLANNED_COLLECTORS = frozenset({"oracle", "icims", "careerpuck"})


class JobList(list):
    def __init__(self, jobs: list[dict], *, complete: bool = True):
        super().__init__(jobs)
        self.complete = complete


def _read(url: str, payload: dict | None = None) -> dict | list | str:
    headers = {"User-Agent": "SearchJob/1.0", "Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers)
    context = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=25, context=context) as response:
        raw = response.read(20_000_000)
    if len(raw) >= 20_000_000:
        raise ValueError(f"Response too large: {url}")
    if "rippling.com" in (urlsplit(url).hostname or "") and "/jobs" in urlsplit(url).path:
        return raw.decode("utf-8", "replace")
    return json.loads(raw)


def _read_html(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    context = ssl.create_default_context(cafile=certifi.where()) if certifi else ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=25, context=context) as response:
        raw = response.read(5_000_000)
    if len(raw) >= 5_000_000:
        raise ValueError("HTML board response too large")
    return raw.decode("utf-8", "replace")


def _job(job_id: object, url: str, title: str, location: str = "", *,
         published: str | None = None, date_field: str | None = None,
         updated: str | None = None, brands: list[str] | None = None) -> dict:
    if not job_id or not url or not title or urlsplit(url).scheme != "https":
        raise ValueError("ATS listing has incomplete job identity")
    return {"id": str(job_id), "url": url, "title": title, "location": location or "",
            "published": published, "date_field": date_field, "updated": updated,
            "brands": brands or []}


def collect(provider: str, token: str, domain: str | None = None) -> list[dict]:
    safe = quote(token, safe="")
    if provider == "greenhouse":
        # Listing fields are enough for title categories and dates. Avoid the
        # large per-job description payload (some boards exceed 20 MB).
        data = _read(f"https://boards-api.greenhouse.io/v1/boards/{safe}/jobs?content=false")
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("Greenhouse listing shape changed")
        jobs = []
        for item in data["jobs"]:
            location = (item.get("location") or {}).get("name") or ""
            brands = [str(x.get("value")) for x in item.get("metadata") or [] if x.get("name") == "Brand" and x.get("value")]
            brands += [str(x.get("name")) for x in item.get("departments") or [] if x.get("name")]
            jobs.append(_job(item["id"], item["absolute_url"], item["title"], location,
                             published=item.get("first_published"),
                             date_field="first_published" if item.get("first_published") else None,
                             updated=item.get("updated_at"), brands=brands))
        return jobs
    if provider == "ashby":
        data = _read(f"https://api.ashbyhq.com/posting-api/job-board/{safe}")
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("Ashby listing shape changed")
        jobs = []
        for item in data["jobs"]:
            if item.get("isListed") is False:
                continue
            url = item.get("jobUrl") or ""
            if urlsplit(url).hostname != "jobs.ashbyhq.com":
                raise ValueError("Ashby returned an unexpected application host")
            # publishedAt can change on republishing; core preserves the earliest
            # observed value for the same posting ID.
            published = item.get("publishedAt")
            jobs.append(_job(item.get("id") or url.rstrip("/").split("/")[-1], url,
                             item["title"], item.get("location") or "",
                             published=published, date_field="publishedAt" if published else None))
        return jobs
    if provider == "lever":
        jobs = []
        for page in range(100):
            batch = _read(f"https://api.lever.co/v0/postings/{safe}?mode=json&limit=100&skip={page * 100}")
            if not isinstance(batch, list):
                raise ValueError("Lever listing shape changed")
            for item in batch:
                url = item.get("hostedUrl") or ""
                if urlsplit(url).hostname != "jobs.lever.co":
                    raise ValueError("Lever returned an unexpected application host")
                categories = item.get("categories") or {}
                locations = categories.get("allLocations") or [categories.get("location") or ""]
                created = item.get("createdAt")
                published = datetime.fromtimestamp(int(created) / 1000, timezone.utc).isoformat() if created else None
                updated = item.get("updatedAt")
                updated_at = datetime.fromtimestamp(int(updated) / 1000, timezone.utc).isoformat() if updated else None
                jobs.append(_job(item["id"], url, item["text"],
                                 "; ".join(str(loc) for loc in locations if loc),
                                 published=published, date_field="createdAt" if published else None,
                                 updated=updated_at))
            if len(batch) < 100:
                return jobs
        raise ValueError("Lever page cap reached")
    if provider == "workday":
        parts = token.split("|")
        if len(parts) != 3:
            raise ValueError("Invalid Workday board token")
        host, tenant, site = parts
        if not (re.fullmatch(r"[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com", host) or
                re.fullmatch(r"wd\d+\.myworkdaysite\.com", host)):
            raise ValueError("Invalid Workday host")
        if not all(re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in (tenant, site)):
            raise ValueError("Invalid Workday tenant or site")
        base = f"https://{host}/wday/cxs/{quote(tenant)}/{quote(site)}"
        jobs = []
        offset = 0
        total = None
        for page in range(300):
            listing = _read(base + "/jobs", {"appliedFacets": {}, "limit": 20,
                                             "offset": offset, "searchText": ""})
            postings = listing.get("jobPostings") if isinstance(listing, dict) else None
            if not isinstance(postings, list):
                raise ValueError("Workday listing shape changed")
            if total is None:
                total = listing.get("total")
                if not isinstance(total, int) or total < len(postings):
                    raise ValueError("Workday total is missing or invalid")
            for item in postings:
                path = item.get("externalPath") or ""
                if not path.startswith("/job/"):
                    continue
                posted_on = item.get("postedOn") or ""
                days = re.fullmatch(r"Posted (\d+)\+? Days? Ago", posted_on, re.I)
                recent = ("Today" in posted_on or "Yesterday" in posted_on or
                          (days is not None and int(days.group(1)) <= 3))
                url = f"https://{host}/{quote(site)}{path}"
                title = item.get("title") or ""
                location = item.get("locationsText") or ""
                published = None
                if recent:
                    detail = _read(base + path)
                    info = detail.get("jobPostingInfo") if isinstance(detail, dict) else None
                    if not isinstance(info, dict):
                        raise ValueError("Workday job detail shape changed")
                    if info.get("canApply") is False:
                        continue
                    country = info.get("country") or {}
                    country_name = country.get("descriptor") or "" if isinstance(country, dict) else ""
                    location = "; ".join(filter(None, (info.get("location") or location, country_name)))
                    title = info.get("title") or title
                    url = info.get("externalUrl") or url
                    published = info.get("startDate")
                jobs.append(_job(path, url, title, location, published=published,
                                 date_field="startDate" if published else None))
            offset += len(postings)
            if offset >= total:
                return jobs
            if not postings:
                raise ValueError("Workday pagination stopped early")
        raise ValueError("Workday page cap reached")
    if provider == "workable":
        data = _read(f"https://www.workable.com/api/accounts/{safe}?details=true")
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("Workable public listing shape changed")
        jobs = []
        for item in data["jobs"]:
            url = item.get("url") or item.get("shortlink") or ""
            if urlsplit(url).hostname != "apply.workable.com":
                raise ValueError("Workable returned an unexpected application host")
            locations = item.get("locations") or []
            if not isinstance(locations, list):
                raise ValueError("Workable locations shape changed")
            places = [", ".join(dict.fromkeys(str(loc.get(key)) for key in
                      ("city", "region", "country") if loc.get(key))) for loc in locations
                      if isinstance(loc, dict)]
            for place in places or [""]:
                jobs.append(_job(item.get("shortcode") or url.rstrip("/").split("/")[-1],
                                 url, item["title"], place,
                                 published=item.get("published_on"),
                                 date_field="published_on" if item.get("published_on") else None))
        return jobs
    if provider == "jazzhr":
        if not re.fullmatch(r"[a-z0-9-]+\.applytojob\.com", token):
            raise ValueError("Invalid JazzHR board host")
        body = _read_html(f"https://{token}/apply")
        pattern = re.compile(r'<h3[^>]*>\s*<a\s+href="(https://[^\"]+/apply/[A-Za-z0-9]+/[^\"]*)"[^>]*>'
                             r'(.*?)</a>\s*</h3>\s*<ul[^>]*>(.*?)</ul>', re.I | re.S)
        matches = list(pattern.finditer(body))
        if not matches and "list-group-item" in body:
            raise ValueError("JazzHR public job-list markup changed")
        jobs = []
        for match in matches:
            url = html.unescape(match.group(1))
            parts = urlsplit(url)
            path = [part for part in parts.path.split("/") if part]
            if parts.hostname != token or len(path) < 2 or path[0] != "apply":
                raise ValueError("JazzHR returned an unexpected job route")
            title = html.unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
            location_match = re.search(r"<i[^>]*fa-map-marker[^>]*></i>\s*([^<]+)", match.group(3), re.I | re.S)
            location = html.unescape(location_match.group(1)).strip() if location_match else ""
            jobs.append(_job(path[1], url, title, location))
        return jobs
    if provider == "smartrecruiters":
        jobs = []
        for page in range(100):
            data = _read(f"https://api.smartrecruiters.com/v1/companies/{safe}/postings?limit=100&offset={page * 100}")
            if not isinstance(data, dict) or not isinstance(data.get("content"), list):
                raise ValueError("SmartRecruiters listing shape changed")
            for item in data["content"]:
                location = item.get("location") or {}
                loc = location.get("fullLocation") or "" if isinstance(location, dict) else str(location)
                url = f"https://jobs.smartrecruiters.com/{safe}/{item['id']}"
                date = item.get("releasedDate")
                jobs.append(_job(item["id"], url, item["name"], loc,
                                 published=date, date_field="releasedDate" if date else None))
            if len(jobs) >= data.get("totalFound", len(jobs)):
                return jobs
            if not data["content"]:
                raise ValueError("SmartRecruiters pagination stopped early")
        raise ValueError("SmartRecruiters page cap reached")
    if provider == "gem":
        data = _read(f"https://api.gem.com/job_board/v0/{safe}/job_posts/")
        items = data if isinstance(data, list) else data.get("job_posts") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError("Gem listing shape changed")
        jobs = []
        for item in items:
            url = item.get("absolute_url") or ""
            if urlsplit(url).hostname != "jobs.gem.com":
                raise ValueError("Gem returned an unexpected application host")
            loc = item.get("location") or {}
            location = loc.get("name") or "" if isinstance(loc, dict) else str(loc)
            date = item.get("first_published_at")
            jobs.append(_job(item.get("id") or url.rstrip("/").split("/")[-1], url,
                             item["title"], location, published=date,
                             date_field="first_published_at" if date else None))
        return jobs
    if provider == "vizirecruiter":
        data = _read(f"https://vizi.vizirecruiter.com/{safe}/vizis.json")
        if not isinstance(data, list):
            raise ValueError("ViziRecruiter listing shape changed")
        jobs = []
        for item in data:
            url = item.get("link") or ""
            parts = urlsplit(url)
            path = [part for part in parts.path.split("/") if part]
            if parts.hostname != "vizi.vizirecruiter.com" or len(path) < 3 or path[0] != token:
                raise ValueError("ViziRecruiter returned an unexpected job route")
            value = item.get("issueDate")
            date = datetime.fromtimestamp(int(value) / 1000, timezone.utc).isoformat() if value else None
            jobs.append(_job(path[1], url, item["title"], item.get("location") or "",
                             published=date, date_field="issueDate" if date else None))
        return jobs
    if provider == "rippling":
        base = f"https://ats.rippling.com/{safe}/jobs"
        jobs = []
        total_pages = None
        for page in range(100):
            url = base if page == 0 else f"{base}?page={page}"
            text = _read(url)
            if not isinstance(text, str):
                raise ValueError("Rippling page shape changed")
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', text)
            if not match:
                raise ValueError("Rippling job payload missing")
            data = json.loads(match.group(1))["props"]["pageProps"]
            matches = [q["state"]["data"] for q in data["dehydratedState"]["queries"]
                       if isinstance(q.get("queryKey"), list) and "job-posts" in q["queryKey"]]
            if len(matches) != 1:
                raise ValueError("Rippling listing shape changed")
            payload = matches[0]
            total_pages = payload["totalPages"]
            for item in payload["items"]:
                id_ = item["id"]
                job_url = item.get("url") or f"{base}/{id_}"
                detail_html = _read(job_url)
                if not isinstance(detail_html, str):
                    raise ValueError("Rippling detail page shape changed")
                detail_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', detail_html)
                if not detail_match:
                    raise ValueError("Rippling job detail missing")
                detail = json.loads(detail_match.group(1))["props"]["pageProps"]["apiData"]["jobPost"]
                if str(detail.get("uuid")) != str(id_):
                    raise ValueError("Rippling job detail ID mismatch")
                date = detail.get("createdOn")
                locations = detail.get("workLocations") or []
                jobs.append(_job(id_, detail.get("url") or job_url, detail.get("name") or item["name"],
                                 "; ".join(locations) if isinstance(locations, list) else str(locations),
                                 published=date, date_field="createdOn" if date else None))
            if page + 1 >= total_pages:
                return jobs
        raise ValueError("Rippling page cap reached")
    if provider == "eightfold":
        if token != "searchcareers.caci.com" and not token.endswith(".eightfold.ai"):
            raise ValueError("Unverified Eightfold host")
        if not domain or not re.fullmatch(r"[a-z0-9.-]+", domain):
            raise ValueError("Eightfold needs the verified company domain")
        encoded_domain = quote(domain, safe="")
        jobs = []
        expected = None
        seen_ids = set()
        for page in range(500):
            data = _read(f"https://{token}/api/pcsx/search?domain={encoded_domain}&start={page * 10}&sort_by=timestamp")
            payload = data.get("data") or {} if isinstance(data, dict) else {}
            positions = payload.get("positions")
            if not isinstance(positions, list):
                raise ValueError("Eightfold listing shape changed")
            if expected is None:
                expected = int(payload.get("count", 0))
                if expected < 0 or expected > 5000:
                    raise ValueError("Eightfold listing count out of range")
            for item in positions:
                if str(item["id"]) in seen_ids:
                    continue
                seen_ids.add(str(item["id"]))
                date = datetime.fromtimestamp(int(item["postedTs"]), timezone.utc).date().isoformat() if item.get("postedTs") else None
                url = f"https://{token}/careers/job/{item['id']}?domain={encoded_domain}&hl=en"
                jobs.append(_job(item["id"], url, item["name"], "; ".join(item.get("locations") or []),
                                 published=date, date_field="postedTs" if date else None))
            if (page + 1) * 10 >= expected or not positions:
                return JobList(jobs, complete=len(jobs) >= expected)
        raise ValueError("Eightfold safety page cap reached; board not complete")
    raise ValueError(f"No collector for provider {provider}")
