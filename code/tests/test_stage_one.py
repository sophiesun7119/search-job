import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from search_job.core import classify, classify_level, connect, record_scan, upsert_board, upsert_company, upsert_opening
from search_job.render import render_json, render_markdown
from search_job.location import is_us_location


class StageOneTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / "jobs.sqlite3")
        upsert_company(self.db, "a", "Example Co", "https://example.com", "fixture")
        upsert_board(self.db, "greenhouse:a", "greenhouse", "a", "https://job-boards.greenhouse.io/a")
        self.db.execute("INSERT INTO company_boards(company_key,board_key,status) VALUES ('a','greenhouse:a','verified')")
        self.db.execute("INSERT INTO scan_runs(scan_key,board_key,started_at,outcome) VALUES ('baseline','greenhouse:a','2026-09-25T09:00:00Z','complete')")
        self.as_of = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def add(self, job_id="1", title="Senior Software Engineer", **extra):
        data = dict(company_key="a", provider="greenhouse", board_key="greenhouse:a",
                    provider_job_id=job_id,
                    canonical_apply_url=f"https://job-boards.greenhouse.io/a/jobs/{job_id}",
                    title=title, first_seen_at="2026-09-25T10:00:00+00:00",
                    last_seen_at="2026-09-25T10:00:00+00:00", open_state="open",
                    published_at="2026-09-24T10:00:00+00:00",
                    variants=[("Chicago, IL", f"https://job-boards.greenhouse.io/a/jobs/{job_id}")])
        data.update(extra)
        return upsert_opening(self.db, **data)

    def test_identity_variants_and_earliest_publication(self):
        key = self.add(source_date_field="first_published",
                       source_date_value="2026-09-24T10:00:00+00:00",
                       published_at="2026-09-24T10:00:00+00:00",
                       variants=[("New York", "https://example.com/apply/ny")])
        same = self.add(title="Senior Software Engineer Updated",
                        published_at="2026-09-25T10:00:00+00:00",
                        source_date_field="updated_at",
                        source_date_value="2026-09-25T11:00:00+00:00",
                        updated_at="2026-09-25T11:00:00+00:00",
                        variants=[("Chicago", "https://example.com/apply/chicago")])
        other = self.add(job_id="2", title="Senior Software Engineer")
        self.assertEqual(key, same)
        self.assertNotEqual(key, other)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM openings").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM opening_variants WHERE opening_key=?", (key,)).fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM opening_tags WHERE opening_key=?", (key,)).fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT published_at FROM openings WHERE opening_key=?", (key,)).fetchone()[0],
                         "2026-09-24T10:00:00+00:00")
        self.assertEqual(self.db.execute("SELECT source_date_field FROM openings WHERE opening_key=?", (key,)).fetchone()[0],
                         "first_published")
        self.add(source_date_field="first_published",
                 source_date_value="2026-09-23T10:00:00+00:00",
                 published_at="2026-09-23T10:00:00+00:00",
                 variants=[("New York", "https://example.com/apply/ny")])
        source_value = self.db.execute("SELECT published_at,source_date_value FROM openings WHERE opening_key=?", (key,)).fetchone()
        self.assertEqual(source_value[0], "2026-09-23T10:00:00+00:00")
        self.assertEqual(source_value[1], "2026-09-23T10:00:00+00:00")
        md = render_markdown(self.db, self.as_of)
        self.assertIn("Chicago, New York", md)
        self.assertIn("[Apply](https://example.com/apply/chicago)<br>[Apply](https://example.com/apply/ny)", md)
        self.assertIn("2d", md)
        self.assertNotIn("0d 🔎", md)

    def test_title_precedence_and_specialist_tables(self):
        cases = {
            "Senior Software Engineer": "sde",
            "Software Engineer New Grad": "sde-entry",
            "Staff Software Engineer": "sde-staff",
            "Frontend Software Engineer": "frontend",
            "iOS Software Engineer": "mobile",
            "Software QA Engineer": "qa-test",
            "Business Intelligence Analyst": "analyst",
            "Research Scientist": "scientist",
            "Cloud Platform Engineer": "sde",
            "Technical Program Manager, Platform": "other",
            "Solutions Architect - Cloud Infrastructure": "other",
            "Creative Producer - Short-Form Mobile Video": "other",
            "PRODUCT MANAGER": "product-manager",
            "Manager, Product": "product-manager",
            "Product Marketing Manager": "other",
            "Manager, Talent Products": "other",
            "Senior Developer Advocate": "other",
            "Engineering Manager": "engineering-manager",
            "MANAGER of ENGINEERS": "engineering-manager",
            "Manager, Software Engineering": "engineering-manager",
        }
        for title, expected in cases.items():
            self.assertEqual(classify(title)[0], expected, title)
        self.assertEqual(classify_level("Senior Software Engineer")[0], "level:senior")
        self.assertEqual(classify_level("Software Engineer")[0], "level:unspecified")

    def test_manager_categories_can_overlap(self):
        key = self.add(title="Manager, Product Engineering")
        tags = {row[0] for row in self.db.execute(
            "SELECT tag FROM opening_tags WHERE opening_key=?", (key,))}
        self.assertNotIn("product-manager", tags)
        self.assertIn("engineering-manager", tags)
        self.assertIn("## Engineering Manager", render_markdown(self.db, self.as_of))

    def test_reader_intro_and_preview_status_survive_regeneration(self):
        self.add()
        md = render_markdown(self.db, self.as_of, historical_preview=True)
        self.assertIn("Search Job finds public job openings", md)
        self.assertIn("[architecture and category rules](code/PLAN.md)", md)
        self.assertIn("[stage record](code/STAGE.md)", md)
        self.assertIn("Historical preview — open status not verified", md)
        self.assertNotIn("{{SNAPSHOT_STATUS}}", md)

    def test_complete_scan_only_closes_after_two_misses(self):
        key = self.add()
        record_scan(self.db, "greenhouse:a", "x1", "2026-09-25T11:00:00Z", "2026-09-25T11:01:00Z", "failed", set())
        self.assertEqual(self.db.execute("SELECT open_state FROM openings").fetchone()[0], "open")
        record_scan(self.db, "greenhouse:a", "x2", "2026-09-25T11:02:00Z", "2026-09-25T11:03:00Z", "complete", set())
        self.assertEqual(self.db.execute("SELECT open_state FROM openings").fetchone()[0], "open")
        self.assertNotIn("Senior Software Engineer", render_markdown(self.db, self.as_of))
        record_scan(self.db, "greenhouse:a", "x3", "2026-09-25T11:04:00Z", "2026-09-25T11:05:00Z", "partial", set())
        self.assertEqual(self.db.execute("SELECT missing_complete_scans FROM openings").fetchone()[0], 1)
        record_scan(self.db, "greenhouse:a", "x4", "2026-09-25T11:06:00Z", "2026-09-25T11:07:00Z", "complete", set())
        self.assertEqual(self.db.execute("SELECT open_state FROM openings").fetchone()[0], "inactive")
        self.assertNotIn("Senior Software Engineer", render_markdown(self.db, self.as_of))
        record_scan(self.db, "greenhouse:a", "x5", "2026-09-25T11:08:00Z", "2026-09-25T11:09:00Z", "complete", {key})
        self.assertEqual(self.db.execute("SELECT open_state FROM openings").fetchone()[0], "open")

    def test_deterministic_json_and_date_precision(self):
        self.add(job_id="1", source_date_field="postedTs", source_date_value="2026-09-25",
                 source_date_precision="day", published_at="2026-09-25")
        self.add(job_id="2", published_at=None)
        self.add(job_id="3", published_at="2026-06-27T12:00:00+00:00")
        one = render_json(self.db, self.as_of)
        self.assertEqual(one, render_json(self.db, self.as_of))
        self.assertEqual(json.loads(one)["schema_version"], 1)
        md = render_markdown(self.db, self.as_of)
        self.assertEqual(md, render_markdown(self.db, self.as_of))
        self.assertIn("0d †", md)
        self.assertNotIn("0d 🔎", md)
        self.assertNotIn("90d", md)

    def test_us_readme_filter_keeps_source_jobs_in_json(self):
        self.add(job_id="us", variants=[("Remote - US", "https://example.com/us")])
        self.add(job_id="ireland", variants=[("Remote - Ireland", "https://example.com/ireland")])
        self.add(job_id="spain", variants=[("Remote - Spain", "https://example.com/spain")])
        self.add(job_id="unknown", variants=[("Remote", "https://example.com/unknown")])
        md = render_markdown(self.db, self.as_of)
        self.assertIn("Remote - US", md)
        self.assertNotIn("Remote - Ireland", md)
        self.assertNotIn("Remote - Spain", md)
        self.assertNotIn("https://example.com/unknown", md)
        self.assertEqual(len(json.loads(render_json(self.db, self.as_of))["openings"]), 4)
        self.assertTrue(is_us_location("San Francisco, CA | New York City, NY"))
        self.assertTrue(is_us_location("Remote (Any State)"))
        self.assertFalse(is_us_location("Remote - Canada"))
        self.assertFalse(is_us_location("Hybrid"))
        self.assertFalse(is_us_location("Perth, WA, Australia"))
        self.assertFalse(is_us_location("Madrid, MD, Spain"))
        self.assertTrue(is_us_location("London, UK; San Francisco, CA"))


if __name__ == "__main__":
    unittest.main()
