import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from search_job.collectors import collect
from search_job.core import SCHEMA, connect
from search_job.intake import import_seed
from search_job.leads import import_simplify_catalog, recognize_apply_url
from search_job.scan import scan_registered


class CollectorTest(unittest.TestCase):
    def test_stage_one_database_upgrade_preserves_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            old_schema = SCHEMA.read_text().replace("  brand_filter TEXT,\n", "").replace(
                "  source TEXT NOT NULL,\n  scan_cohort TEXT NOT NULL DEFAULT 'new' CHECK (scan_cohort IN ('new','old')),\n  validated_at TEXT\n",
                "  source TEXT NOT NULL\n").replace(
                "'pending_recheck','pending_identity','verified','failed'",
                "'pending_recheck','verified','failed'")
            with sqlite3.connect(path) as db:
                db.executescript(old_schema)
                db.execute("INSERT INTO companies(company_key,name,official_url,source) VALUES ('acme.com','Acme','https://acme.com/','seed')")
                db.execute("INSERT INTO boards(board_key,provider,board_token,route_status) VALUES ('greenhouse:acme','greenhouse','acme','active')")
                db.execute("INSERT INTO company_boards(company_key,board_key,status) VALUES ('acme.com','greenhouse:acme','verified')")
            with connect(path) as db:
                self.assertEqual(db.execute("SELECT status FROM company_boards").fetchone()[0], "verified")
                self.assertIn("brand_filter", {row[1] for row in db.execute("PRAGMA table_info(company_boards)")})
                self.assertEqual(db.execute("SELECT scan_cohort FROM companies").fetchone()[0], "new")
                self.assertEqual(db.execute("SELECT support_status FROM provider_capabilities WHERE provider='workday'").fetchone()[0], "active")
                self.assertEqual(db.execute("SELECT support_status FROM provider_capabilities WHERE provider='oracle'").fetchone()[0], "planned")

    def test_greenhouse_and_ashby_listing_dates(self):
        greenhouse = {"jobs": [{"id": 123, "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/123",
                                 "title": "Engineer", "first_published": "2026-09-24T10:00:00Z",
                                 "updated_at": "2026-09-25T10:00:00Z", "location": {"name": "Chicago"}}]}
        ashby = {"jobs": [{"id": "abc", "jobUrl": "https://jobs.ashbyhq.com/acme/abc",
                           "title": "Analyst", "publishedAt": "2026-09-24T10:00:00Z", "isListed": True},
                          {"id": "hidden", "jobUrl": "https://jobs.ashbyhq.com/acme/hidden",
                           "title": "Hidden", "isListed": False}]}
        with patch("search_job.collectors._read", side_effect=[greenhouse, ashby]):
            green = collect("greenhouse", "acme")
            ash = collect("ashby", "acme")
        self.assertEqual(len(green), 1)
        self.assertEqual(green[0]["published"], "2026-09-24T10:00:00Z")
        self.assertEqual(green[0]["updated"], "2026-09-25T10:00:00Z")
        self.assertEqual(len(ash), 1)

    def test_lever_dates_and_workday_complete_pagination(self):
        lever = [{"id": "abc", "hostedUrl": "https://jobs.lever.co/acme/abc",
                  "text": "Software Engineer", "createdAt": 1780000000000,
                  "categories": {"allLocations": ["Chicago, IL"]}}]
        first = {"total": 2, "jobPostings": [
            {"externalPath": "/job/Older_A", "title": "Analyst", "locationsText": "Austin, TX",
             "postedOn": "Posted 30+ Days Ago"}]}
        second = {"total": 0, "jobPostings": [
            {"externalPath": "/job/Newer_B", "title": "Engineer", "locationsText": "Chicago",
             "postedOn": "Posted Yesterday"}]}
        detail = {"jobPostingInfo": {"title": "Software Engineer", "startDate": "2026-09-25",
                   "location": "Chicago", "country": {"descriptor": "United States of America"},
                   "externalUrl": "https://acme.wd1.myworkdayjobs.com/Careers/job/Newer_B",
                   "canApply": True}}
        with patch("search_job.collectors._read", side_effect=[lever, first, second, detail]):
            lever_jobs = collect("lever", "acme")
            workday_jobs = collect("workday", "acme.wd1.myworkdayjobs.com|acme|Careers")
        self.assertEqual(len(lever_jobs), 1)
        self.assertEqual(lever_jobs[0]["date_field"], "createdAt")
        self.assertEqual(len(workday_jobs), 2)
        self.assertIsNone(workday_jobs[0]["published"])
        self.assertEqual(workday_jobs[1]["published"], "2026-09-25")
        self.assertIn("United States", workday_jobs[1]["location"])

    def test_workable_public_jobs_use_published_on_and_country(self):
        payload = {"jobs": [{"shortcode": "ABC", "url": "https://apply.workable.com/j/ABC",
                             "title": "Software Engineer", "published_on": "2026-09-25",
                             "state": "Illinois", "locations": [{"city": "Chicago", "region": "Illinois",
                                                               "country": "United States"}]}]}
        with patch("search_job.collectors._read", return_value=payload):
            jobs = collect("workable", "acme")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["published"], "2026-09-25")
        self.assertEqual(jobs[0]["date_field"], "published_on")
        self.assertEqual(jobs[0]["location"], "Chicago, Illinois, United States")

    def test_jazzhr_public_board_keeps_unknown_date(self):
        html = ('<li class="list-group-item"><h3 class="list-group-item-heading">'
                '<a href="https://acme.applytojob.com/apply/ABC/Engineer">Engineer</a></h3>'
                '<ul class="list-inline list-group-item-text"><li>'
                '<i class="fa fa-map-marker"></i>Chicago, IL</li></ul></li>')
        with patch("search_job.collectors._read_html", return_value=html):
            jobs = collect("jazzhr", "acme.applytojob.com")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], "ABC")
        self.assertEqual(jobs[0]["location"], "Chicago, IL")
        self.assertIsNone(jobs[0]["published"])

    def test_simplify_lead_import_is_bounded_and_resumable(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.sqlite3"
            with sqlite3.connect(catalog) as source:
                source.executescript("""CREATE TABLE companies(id INTEGER,name TEXT,best_apply_url TEXT,
                  best_year INTEGER,status TEXT); CREATE TABLE observations(id INTEGER,company_id INTEGER,
                  source_year INTEGER,apply_url TEXT,profile_url TEXT,source_url TEXT,title TEXT,location TEXT);""")
                for id_ in (1, 2, 3):
                    url = f"https://jobs.ashbyhq.com/company{id_}/job"
                    source.execute("INSERT INTO companies VALUES (?,?,?,?,?)",
                                   (id_, f"Company {id_}", url, 2026, "pending"))
                    source.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)",
                                   (id_, id_, 2026, url, f"https://simplify.jobs/c/company-{id_}",
                                    "https://example.com/list", "Engineer", "Remote US"))
            with connect(Path(directory) / "jobs.sqlite3") as db:
                first = import_simplify_catalog(db, catalog, limit=2)
                second = import_simplify_catalog(db, catalog, limit=2)
                self.assertEqual(first["source_ids"], [1, 2])
                self.assertEqual(second["source_ids"], [3])
                self.assertEqual(db.execute("SELECT COUNT(*) FROM source_leads").fetchone()[0], 3)
                self.assertEqual(import_simplify_catalog(db, catalog, limit=2)["selected"], 0)
        self.assertEqual(recognize_apply_url("https://jobs.lever.co/acme/123"), ("lever", "acme"))

    def test_seed_and_scan_idempotent_and_failed_scan_is_inert(self):
        with tempfile.TemporaryDirectory() as directory:
            seed = Path(directory) / "seed.json"
            seed.write_text(json.dumps({"companies": [{"name": "Acme", "domain": "acme.com",
                "routes": [{"provider": "greenhouse", "board_token": "acme",
                            "evidence_url": "https://job-boards.greenhouse.io/acme"}]}]}))
            with connect(Path(directory) / "db.sqlite3") as db:
                self.assertEqual(import_seed(db, seed)["boards"], 1)
                sample = [{"id": "1", "url": "https://job-boards.greenhouse.io/acme/jobs/1",
                           "title": "Senior Software Engineer", "location": "Chicago",
                           "published": "2026-09-24T10:00:00Z", "date_field": "first_published"}]
                with patch("search_job.scan.collect", return_value=sample):
                    self.assertEqual(scan_registered(db)["new"], 1)
                    self.assertEqual(scan_registered(db)["new"], 0)
                with patch("search_job.scan.collect", side_effect=ValueError("broken listing")):
                    self.assertEqual(len(scan_registered(db)["failures"]), 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM openings").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT open_state FROM openings").fetchone()[0], "open")

    def test_eightfold_duplicate_pages_are_partial(self):
        pages = [
            {"data": {"count": 13, "positions": [
                {"id": 1, "name": "Engineer", "postedTs": 1780000000, "locations": ["VA"]},
                {"id": 2, "name": "Analyst", "postedTs": 1780000000, "locations": ["VA"]}]}},
            {"data": {"count": 13, "positions": [
                {"id": 2, "name": "Analyst", "postedTs": 1780000000, "locations": ["VA"]}]}},
        ]
        with patch("search_job.collectors._read", side_effect=pages):
            jobs = collect("eightfold", "searchcareers.caci.com", "caci.com")
        self.assertEqual(len(jobs), 2)
        self.assertFalse(jobs.complete)

    def test_company_new_old_windows_and_location_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            seed = Path(directory) / "seed.json"
            seed.write_text(json.dumps({"companies": [{"name": "Acme", "domain": "acme.com",
                "routes": [{"provider": "greenhouse", "board_token": "acme"}]}]}))
            with connect(Path(directory) / "db.sqlite3") as db:
                import_seed(db, seed)
                now = datetime.now(timezone.utc)
                def job(id, hours, location):
                    return {"id": id, "url": f"https://job-boards.greenhouse.io/acme/jobs/{id}",
                            "title": "Senior Software Engineer", "location": location,
                            "published": (now - timedelta(hours=hours)).isoformat(),
                            "date_field": "first_published"}
                first = [job("48h", 48, "Remote - Ireland"), job("12h", 12, "Remote - US")]
                with patch("search_job.scan.collect", return_value=first):
                    initial = scan_registered(db)
                    self.assertEqual(initial["processed"], 2)
                    self.assertEqual(initial["promoted_old"], 1)
                    self.assertEqual(scan_registered(db, full_recheck=True)["promoted_old"], 0)
                self.assertEqual(db.execute("SELECT scan_cohort FROM companies").fetchone()[0], "old")
                changed = [job("48h", 48, "Remote - US"), job("12h", 12, "Remote - US"),
                           job("36h", 36, "Remote - US"), job("1h", 1, "Remote - US")]
                with patch("search_job.scan.collect", return_value=changed):
                    result = scan_registered(db)
                self.assertEqual(result["processed"], 3)  # Refresh saved 48h; admit only 12h and 1h.
                self.assertEqual(result["new"], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM openings").fetchone()[0], 3)
                locations = [r[0] for r in db.execute("""SELECT v.location FROM opening_variants v
                  JOIN openings o USING(opening_key) WHERE o.provider_job_id='48h'""")]
                self.assertEqual(locations, ["Remote - US"])


if __name__ == "__main__":
    unittest.main()
