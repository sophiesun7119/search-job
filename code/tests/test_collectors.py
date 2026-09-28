import json
import io
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from search_job.collectors import _read, collect
from search_job.core import SCHEMA, connect
from search_job.intake import import_seed
from search_job.leads import (_official_route, confirm_official_route, import_simplify_catalog,
                              mark_ai_review, probe_saved_samples, recognize_apply_url,
                              verify_official_routes)
from search_job.review_dashboard import write_review_dashboard
from search_job.scan import scan_registered


class CollectorTest(unittest.TestCase):
    def test_jobsyn_uses_source_date_and_complete_count(self):
        response = {"pagination": {"total": 1, "page_size": 10, "offset": "0"},
                    "jobs": [{"buid": 57625, "guid": "A" * 32,
                              "title_exact": "Software Engineer", "location_exact": "Austin, TX",
                              "country_exact": "United States", "date_new": "2026-09-26T14:00:00Z"}]}
        with patch("search_job.collectors._read", return_value=response) as read:
            jobs = collect("jobsyn", "careers.textron.com", "textron.com")
        self.assertTrue(jobs.complete)
        self.assertEqual(jobs[0]["date_field"], "date_new")
        self.assertEqual(jobs[0]["location"], "Austin, TX; United States")
        self.assertEqual(jobs[0]["url"],
                         "https://careers.textron.com/-/-/" + "A" * 32 + "/job/")
        self.assertEqual(read.call_args.kwargs["origin_header"], "careers.textron.com")

    def test_jazzhr_official_widget_identifies_board(self):
        self.assertEqual(recognize_apply_url(
            "https://app.jazz.co/widgets/basic/create/wonderbotz"),
            ("jazzhr", "wonderbotz.applytojob.com"))
        with patch("search_job.leads._site_page", side_effect=[
                ("https://wonderbotz.com/", ["https://wonderbotz.com/careers/"], ""),
                ("https://wonderbotz.com/careers/",
                 ["https://app.jazz.co/widgets/basic/create/wonderbotz"], "")]):
            route = _official_route({"official_url": "https://wonderbotz.com/",
                                     "provider_hint": "jazzhr",
                                     "board_hint": "wonderbotz.applytojob.com"})
        self.assertEqual(route["provider"], "jazzhr")
        self.assertEqual(route["board"], "wonderbotz.applytojob.com")

    def test_greenhouse_embedded_application_identifies_real_board(self):
        self.assertEqual(recognize_apply_url(
            "https://job-boards.greenhouse.io/embed/job_app?for=studycareers&token=5429313008"),
            ("greenhouse", "studycareers"))
        self.assertEqual(recognize_apply_url(
            "https://boards.greenhouse.io/embed/job_board/js?for=studycareers"),
            ("greenhouse", "studycareers"))

    def test_careers_page_precedes_generic_site_search(self):
        with patch("search_job.leads._site_page", side_effect=[
                ("https://corp.example.com/", ["https://www.example.com/search",
                  "https://corp.example.com/corp/careers"], ""),
                ("https://corp.example.com/corp/careers",
                 ["https://boards.greenhouse.io/example"], ""),
                ("https://www.example.com/search", [], "")]) as read:
            route = _official_route({"official_url": "https://corp.example.com/",
                                     "provider_hint": "greenhouse", "board_hint": "example"})
        self.assertEqual(route["board"], "example")
        self.assertEqual(read.call_args_list[1].args[0],
                         "https://corp.example.com/corp/careers")

    def test_avature_complete_listing_preserves_date_and_location(self):
        listing = ('''<span>1</span> of 1 results <article class="article article--result">'''
                   '''<a class="link" href="https://careers.acme.com/en_US/careers/JobDetail/Engineer/123">'''
                   '''Engineer</a><span class="list-item-location">Location: Chicago, IL, US</span>'''
                   '''<span class="list-item-posted">Posted Date: 09/26/2026</span></article>''')
        with patch("search_job.collectors._read_html", return_value=listing):
            jobs = collect("avature", "careers.acme.com", "acme.com")
        self.assertTrue(jobs.complete)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["published"], "2026-09-26")
        self.assertEqual(jobs[0]["location"], "Chicago, IL, US")

    def test_successfactors_official_page_and_dated_listing(self):
        listing = ('''<body class="coreCSB search-page body"><span class="paginationLabel">'''
                   '''Results <b>1 – 1</b> of <b>1</b></span><table id="searchresults">'''
                   '''<tr class="data-row"><a href="/job/Chicago-Engineer-IL/123/" '''
                   '''class="jobTitle-link">Engineer</a><span class="jobLocation">'''
                   '''Chicago, IL, US</span><span class="jobDate">Sep 26, 2026</span>'''
                   '''</tr></table></body>''')
        self.assertEqual(recognize_apply_url(
            "https://careers.acme.com/job/Chicago-Engineer-IL/123/?ats=successfactors"),
            ("successfactors", "careers.acme.com"))
        with patch("search_job.collectors._read_html", return_value=listing):
            jobs = collect("successfactors", "careers.acme.com", "acme.com")
        self.assertTrue(jobs.complete)
        self.assertEqual(jobs[0]["published"], "2026-09-26")
        self.assertEqual(jobs[0]["location"], "Chicago, IL, US")
        with patch("search_job.leads._site_page", side_effect=[
                ("https://acme.com/careers", ["https://careers.acme.com/"], ""),
                ("https://careers.acme.com/", ["https://careers.acme.com/search/"], ""),
                ("https://careers.acme.com/search/", [], listing)]):
            route = _official_route({"official_url": "https://acme.com/careers",
                                     "provider_hint": "unknown", "board_hint": None})
        self.assertEqual(route["provider"], "successfactors")
        self.assertEqual(route["board"], "careers.acme.com")

    def test_eightfold_company_domain_uses_explicit_country_location(self):
        listing = {"data": {"count": 1, "positions": [{"id": 123, "name": "Engineer",
            "postedTs": 1790294400, "locations": ["Billerica,MA"],
            "standardizedLocations": ["Billerica, MA, US"]}]}}
        self.assertEqual(recognize_apply_url(
            "https://careers.acme.com/careers/job/123?domain=acme.com"),
            ("eightfold", "careers.acme.com"))
        with patch("search_job.collectors._read", return_value=listing):
            jobs = collect("eightfold", "careers.acme.com", "acme.com")
        self.assertEqual(jobs[0]["location"], "Billerica, MA, US")
        with self.assertRaisesRegex(ValueError, "Unverified Eightfold host"):
            collect("eightfold", "careers.other.com", "acme.com")

    def test_bamboohr_public_listing_uses_detail_date_and_country(self):
        listing = {"meta": {"totalCount": 1}, "result": [{"id": "62", "jobOpeningName": "Engineer"}]}
        detail = {"result": {"jobOpening": {"jobOpeningStatus": "Open",
            "datePosted": "2026-09-25", "location": {"city": "Burnaby",
                "state": "British Columbia", "addressCountry": "Canada"}}}}
        with patch("search_job.collectors._read", side_effect=[listing, detail]) as read:
            jobs = collect("bamboohr", "acme.bamboohr.com")
        self.assertEqual(recognize_apply_url("https://acme.bamboohr.com/careers/62"),
                         ("bamboohr", "acme.bamboohr.com"))
        self.assertEqual(recognize_apply_url("https://acme.bamboohr.com/js/embed.js"),
                         ("bamboohr", "acme.bamboohr.com"))
        self.assertEqual(read.call_args_list[0].args[0], "https://acme.bamboohr.com/careers/list")
        self.assertEqual(jobs[0]["published"], "2026-09-25")
        self.assertEqual(jobs[0]["location"], "Burnaby, British Columbia, Canada")
        with patch("search_job.collectors._read", return_value={"meta": {"totalCount": 2}, "result": []}):
            with self.assertRaisesRegex(ValueError, "count"):
                collect("bamboohr", "acme.bamboohr.com")

    def test_pinpoint_public_feed_and_detail_date(self):
        feed = {"data": [{"id": "123", "title": "Engineer", "url":
            "https://careers.acme.com/en/postings/abc", "location": {"name": "Chicago, IL"}}]}
        detail = '<script type="application/ld+json">{"datePosted":"2026-09-25T10:00:00Z"}</script>'
        with patch("search_job.collectors._read", return_value=feed), patch(
                "search_job.collectors._read_html", return_value=detail):
            jobs = collect("pinpoint", "acme.pinpointhq.com", "acme.com")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], "123")
        self.assertEqual(jobs[0]["location"], "Chicago, IL")
        self.assertEqual(jobs[0]["published"], "2026-09-25T10:00:00Z")

    def test_icims_classic_listing_reads_pages_and_source_detail_date(self):
        card = ('<li class="iCIMS_JobCardItem"><a href="https://careers-acme.icims.com/jobs/123/'
                'engineer/job?in_iframe=1" class="iCIMS_Anchor"><h3>Engineer</h3></a>'
                '<div class="iCIMS_JobHeaderTag"><dt>Job Location</dt><dd>US-IL-Chicago</dd></div></li>')
        listing = ('<ul class="iCIMS_JobsTable">' + card + '</ul>'
                   '<a href="https://careers-acme.icims.com/jobs/search?pr=0&amp;in_iframe=1">1</a>')
        detail = '<script type="application/ld+json">{"datePosted":"2026-09-25T04:00:00Z"}</script>'
        with patch("search_job.collectors._read_html", side_effect=[listing, detail]):
            jobs = collect("icims", "careers-acme.icims.com", "acme.com")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["location"], "US-IL-Chicago")
        self.assertEqual(jobs[0]["published"], "2026-09-25T04:00:00Z")
        self.assertEqual(jobs[0]["url"], "https://careers-acme.icims.com/jobs/123/engineer/job?in_iframe=1")

    def test_icims_jibe_redirect_uses_company_domain_and_paginates(self):
        redirect = "<script>window.top.location.href = 'https:\\/\\/careers.acme.com\\/jobs';</script>"
        item = {"ats_code": "icims", "slug": "123", "title": "Engineer",
                "full_location": "Chicago, Illinois", "country": "United States",
                "posted_date": "2026-09-25T12:00:00+0000",
                "meta_data": {"canonical_url": "https://careers.acme.com/jobs/123"}}
        data = {"totalCount": 1, "jobs": [{"data": item}]}
        with patch("search_job.collectors._read_html", return_value=redirect), patch(
                "search_job.collectors._read", return_value=data) as read:
            jobs = collect("icims", "careers-acme.icims.com", "acme.com")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["location"], "Chicago, Illinois; United States")
        self.assertEqual(jobs[0]["published"], "2026-09-25T12:00:00+0000")
        self.assertIn("careers.acme.com/api/jobs?limit=99&page=1", read.call_args.args[0])

    def test_icims_company_domain_requires_marker_and_verified_domain(self):
        self.assertEqual(recognize_apply_url("https://careers.acme.com/jobs/123?icims=1"),
                         ("icims", "careers.acme.com"))
        self.assertEqual(recognize_apply_url("https://careers.acme.com/jobs/123"),
                         ("unknown", None))
        with patch("search_job.collectors._read", return_value={"totalCount": 0, "jobs": []}):
            self.assertEqual(collect("icims", "careers.acme.com", "acme.com"), [])
            with self.assertRaisesRegex(ValueError, "outside the verified company domain"):
                collect("icims", "careers.other.com", "acme.com")

    def test_careerpuck_public_board_preserves_identity_location_and_source_date(self):
        payload = {"permalink": "acme", "jobs": [
            {"status": "public", "atsSourceId": "123", "title": " Engineer ",
             "location": "Remote, USA", "postedAt": "2026-09-25T12:00:00Z",
             "publicUrl": "https://app.careerpuck.com/job-board/acme/job/123"},
            {"status": "draft", "atsSourceId": "456", "title": "Hidden",
             "publicUrl": "https://app.careerpuck.com/job-board/acme/job/456"}]}
        with patch("search_job.collectors._read", return_value=payload):
            jobs = collect("careerpuck", "acme")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], "123")
        self.assertEqual(jobs[0]["title"], "Engineer")
        self.assertEqual(jobs[0]["location"], "Remote, USA")
        self.assertEqual(jobs[0]["date_field"], "postedAt")
        self.assertEqual(jobs[0]["published"], "2026-09-25T12:00:00Z")

    def test_public_listing_retries_one_connection_reset(self):
        with patch("search_job.collectors.urllib.request.urlopen",
                   side_effect=[ConnectionResetError("temporary reset"), io.BytesIO(b'{"jobs":[]}')]) as urlopen:
            self.assertEqual(_read("https://example.com/jobs"), {"jobs": []})
        self.assertEqual(urlopen.call_count, 2)

    def test_oracle_listing_paginates_and_preserves_location_and_date(self):
        first = {"items": [{"Offset": 0, "TotalJobsCount": 2, "requisitionList": [
            {"Id": "157648", "Title": "Software Engineer", "PostedDate": "2026-09-25",
             "PrimaryLocation": "Phoenix, AZ", "PrimaryLocationCountry": "US",
             "secondaryLocations": [{"Name": "Chicago, IL", "CountryCode": "US"}]}]}]}
        second = {"items": [{"Offset": 1, "TotalJobsCount": 2, "requisitionList": [
            {"Id": "157649", "Title": "Engineer", "PostedDate": "2026-09-24",
             "PrimaryLocation": "Dublin, Ireland", "PrimaryLocationCountry": "IE"}]}]}
        with patch("search_job.collectors._read", side_effect=[first, second]) as read:
            jobs = collect("oracle", "ibqbjb.fa.ocs.oraclecloud.com|Honeywell")
        self.assertTrue(jobs.complete)
        self.assertEqual(len(jobs), 3)
        self.assertEqual(jobs[0]["id"], "157648")
        self.assertEqual(jobs[0]["date_field"], "PostedDate")
        self.assertEqual(jobs[0]["location"], "Phoenix, AZ; United States")
        self.assertEqual(jobs[1]["location"], "Chicago, IL; United States")
        self.assertEqual(jobs[2]["location"], "Dublin, Ireland")
        self.assertIn("offset=1", read.call_args_list[1].args[0])

    def test_oracle_one_hidden_requisition_needs_matching_second_sort(self):
        def page(offset, ids):
            return {"items": [{"Offset": offset, "TotalJobsCount": 3,
                "requisitionList": [{"Id": id_, "Title": "Engineer", "PostedDate": "2026-09-25",
                                     "PrimaryLocation": "Chicago, IL", "PrimaryLocationCountry": "US"}
                                    for id_ in ids]}]}
        with patch("search_job.collectors._read", side_effect=[
                page(0, ["1", "2"]), page(2, ["2"]),
                page(0, ["1", "2"]), page(2, ["2"])]):
            jobs = collect("oracle", "tenant.fa.ocs.oraclecloud.com|Careers")
        self.assertTrue(jobs.complete)
        self.assertEqual(jobs.source_count_gap, 1)
        self.assertEqual({job["id"] for job in jobs}, {"1", "2"})
        with patch("search_job.collectors._read", side_effect=[
                page(0, ["1", "2"]), page(2, ["2"]),
                page(0, ["1", "3"]), page(2, ["3"])]):
            mismatched = collect("oracle", "tenant.fa.ocs.oraclecloud.com|Careers")
        self.assertFalse(mismatched.complete)

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
                self.assertEqual(db.execute("SELECT support_status FROM provider_capabilities WHERE provider='oracle'").fetchone()[0], "active")

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

    def test_workday_underscore_host_uses_verified_tenant_over_valid_tls_alias(self):
        listing = {"total": 1, "jobPostings": [{"externalPath": "/job/Engineer_1",
            "title": "Engineer", "locationsText": "Chicago, IL", "postedOn": "Posted 20 Days Ago"}]}
        with patch("search_job.collectors._read", return_value=listing) as read:
            jobs = collect("workday", "osv_amerisure.wd5.myworkdayjobs.com|osv_amerisure|Amerisure")
        self.assertEqual(len(jobs), 1)
        self.assertIn("https://osv_amerisure.wd5.myworkdayjobs.com/Amerisure/job/Engineer_1", jobs[0]["url"])
        self.assertIn("osv-amerisure.wd5.myworkdayjobs.com", read.call_args.args[0])
        self.assertEqual(read.call_args.kwargs["host_header"], "osv_amerisure.wd5.myworkdayjobs.com")

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
                  best_year INTEGER,status TEXT,canonical_domain TEXT); CREATE TABLE observations(id INTEGER,company_id INTEGER,
                  source_year INTEGER,apply_url TEXT,profile_url TEXT,source_url TEXT,title TEXT,location TEXT);""")
                for id_ in (1, 2, 3):
                    url = f"https://jobs.ashbyhq.com/company{id_}/job"
                    source.execute("INSERT INTO companies VALUES (?,?,?,?,?,?)",
                                   (id_, f"Company {id_}", url, 2026, "pending",
                                    "company1.example" if id_ == 1 else None))
                    source.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)",
                                   (id_, id_, 2026, url, f"https://simplify.jobs/c/company-{id_}",
                                    "https://example.com/list", "Engineer", "Remote US"))
            with connect(Path(directory) / "jobs.sqlite3") as db:
                first = import_simplify_catalog(db, catalog, limit=2)
                second = import_simplify_catalog(db, catalog, limit=2)
                self.assertEqual(first["source_ids"], [1, 2])
                self.assertEqual(second["source_ids"], [3])
                self.assertEqual(db.execute("SELECT COUNT(*) FROM source_leads").fetchone()[0], 3)
                self.assertEqual(db.execute("SELECT source_company_url FROM source_leads WHERE lead_key='simplify:1'").fetchone()[0],
                                 "https://company1.example/")
                self.assertEqual(import_simplify_catalog(db, catalog, limit=2)["selected"], 0)
        self.assertEqual(recognize_apply_url("https://jobs.lever.co/acme/123"), ("lever", "acme"))
        self.assertEqual(recognize_apply_url("https://app.careerpuck.com/job-board/color-health/job/123"),
                         ("careerpuck", "color-health"))
        self.assertEqual(recognize_apply_url("https://boards-api.greenhouse.io/v1/boards/ixllearning/jobs/123"),
                         ("greenhouse", "ixllearning"))
        self.assertEqual(recognize_apply_url("https://osv_amerisure.wd5.myworkdayjobs.com/Amerisure/jobs"),
                         ("workday", "osv_amerisure.wd5.myworkdayjobs.com|osv_amerisure|Amerisure"))

    def test_agent_reviewed_route_requires_official_evidence_domain(self):
        with tempfile.TemporaryDirectory() as directory:
            with connect(Path(directory) / "jobs.sqlite3") as db:
                db.execute("""INSERT INTO source_leads(lead_key,source_name,source_id,name,source_year,
                  official_url,stage) VALUES ('simplify:1','simplify','1','Acme',2026,
                  'https://acme.com/','route_pending')""")
                with self.assertRaisesRegex(ValueError, "official company domain"):
                    confirm_official_route(db, "simplify:1", evidence_url="https://other.com/careers",
                                           board_url="https://jobs.ashbyhq.com/acme")
                result = confirm_official_route(db, "simplify:1",
                    evidence_url="https://careers.acme.com/jobs",
                    board_url="https://jobs.ashbyhq.com/acme")
                self.assertEqual(result["stage"], "scan_pending")
                self.assertEqual(result["route_resolution_method"], "ai_official_page")
                self.assertEqual(db.execute("SELECT stage FROM source_leads").fetchone()[0], "scan_pending")
                self.assertEqual(db.execute("SELECT route_resolution_method FROM source_leads").fetchone()[0],
                                 "ai_official_page")
                self.assertEqual(db.execute("SELECT status FROM company_boards").fetchone()[0],
                                 "pending_recheck")

    def test_sample_probe_does_not_replace_official_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            with connect(Path(directory) / "jobs.sqlite3") as db:
                db.execute("""INSERT INTO source_leads(lead_key,source_name,source_id,name,
                  sample_apply_url,provider_hint,board_hint,route_evidence_url,stage)
                  VALUES ('simplify:1','simplify','1','Acme',
                  'https://jobs.ashbyhq.com/old/123','careerpuck','new',
                  'https://acme.com/careers','adapter_pending')""")
                with patch("search_job.leads._probe_sample", return_value=(
                        "https://jobs.ashbyhq.com/old/123", 200, None)):
                    probe_saved_samples(db)
                row = db.execute("SELECT provider_hint,board_hint FROM source_leads").fetchone()
                self.assertEqual(tuple(row), ("careerpuck", "new"))

    def test_review_dashboard_preserves_links_and_requires_actual_ai_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            with connect(Path(directory) / "jobs.sqlite3") as db:
                db.execute("""INSERT INTO source_leads(lead_key,source_name,source_id,name,
                  profile_url,source_company_url,official_url,sample_apply_url,stage,last_error,
                  review_state) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                  ("simplify:1", "simplify", "1", "Acme <test>",
                   "https://simplify.jobs/c/Acme", "https://acme.example/", "https://acme.example/",
                   "https://jobs.ashbyhq.com/acme/123", "route_pending", "HTTP 403", "ai_pending"))
                page = Path(directory) / "review.html"
                result = write_review_dashboard(db, page)
                self.assertEqual(result["pending"], 1)
                body = page.read_text()
                self.assertIn("Acme &lt;test&gt;", body)
                self.assertIn("https://acme.example/", body)
                self.assertIn("https://jobs.ashbyhq.com/acme/123", body)
                self.assertIn("待 AI 处理", body)
                self.assertNotIn("需要你提供线索</span>", body)
                mark_ai_review(db, "simplify:1", outcome="needs-user",
                               note="Official careers page still blocks access; no board ownership evidence")
                self.assertEqual(write_review_dashboard(db, page)["needs_user"], 1)
                self.assertIn("Official careers page still blocks access", page.read_text())
                with patch("search_job.leads._official_route", return_value={
                        "stage": "route_pending", "error": "Still blocked"}):
                    verify_official_routes(db, lead_key="simplify:1")
                self.assertEqual(db.execute("SELECT review_state FROM source_leads").fetchone()[0],
                                 "needs_user")

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
                           "published": (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat(),
                           "date_field": "first_published"}]
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
