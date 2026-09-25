import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from search_job.collectors import collect
from search_job.core import SCHEMA, connect
from search_job.intake import import_seed
from search_job.scan import scan_registered


class CollectorTest(unittest.TestCase):
    def test_stage_one_database_upgrade_preserves_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            old_schema = SCHEMA.read_text().replace("  brand_filter TEXT,\n", "").replace(
                "'pending_recheck','pending_identity','verified','failed'",
                "'pending_recheck','verified','failed'")
            with sqlite3.connect(path) as db:
                db.executescript(old_schema)
                db.execute("INSERT INTO companies VALUES ('acme.com','Acme','https://acme.com/','seed')")
                db.execute("INSERT INTO boards(board_key,provider,board_token,route_status) VALUES ('greenhouse:acme','greenhouse','acme','active')")
                db.execute("INSERT INTO company_boards(company_key,board_key,status) VALUES ('acme.com','greenhouse:acme','verified')")
            with connect(path) as db:
                self.assertEqual(db.execute("SELECT status FROM company_boards").fetchone()[0], "verified")
                self.assertIn("brand_filter", {row[1] for row in db.execute("PRAGMA table_info(company_boards)")})

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


if __name__ == "__main__":
    unittest.main()
