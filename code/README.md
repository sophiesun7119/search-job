# Search Job code

Search Job finds public openings from official company job pages and organizes them into a category-based README and a reusable JSON export. Scripts handle repeatable indexing and title rules; bounded AI tasks handle requested company discovery and unresolved ATS, adapter or board work. [PLAN.md](PLAN.md) explains the full workflow and category rules. [STAGE.md](STAGE.md) shows what has been verified so far.

[SCHEMA.md](SCHEMA.md) documents every current SQLite table, its columns and relationships.

**Today:** local SQLite indexing, title categories, README/JSON rendering, route-seed import and live collectors for the seven providers in the current company pool work. The root [job list](../README.md) shows open, ATS-dated postings from the past 72 hours with a confirmed US location and a complete latest board scan. The full index remains in SQLite and JSON. A local preview is generated under ignored `var/` during a run.

## Run the code

From the repository root, initialize an empty local database:

```sh
PYTHONPATH=code/src python3 -m search_job.cli var/search-job.sqlite3
```

Render a database already populated with openings, choosing an explicit timestamp for repeatable output:

```sh
PYTHONPATH=code/src python3 -m search_job.cli var/search-job.sqlite3 \
  --markdown var/README-preview.md --json var/openings.json \
  --as-of 2026-09-25T15:30:00Z
```

`var/` is ignored by Git. The root README is regenerated from the local live database after reviewing the local preview.

Import a portable JSON seed containing companies and their existing ATS routes, then scan one provider at a time:

```sh
PYTHONPATH=code/src python3 -m search_job.run var/search-job.sqlite3 \
  --seed var/route-seed.json
PYTHONPATH=code/src python3 -m search_job.run var/search-job.sqlite3 \
  --scan --provider greenhouse --company twilio.com \
  --markdown var/README-live-preview.md --json var/openings-live.json
```

The seed format is `{"companies":[{"name":"Example","domain":"example.com","routes":[{"provider":"greenhouse","board_token":"example","evidence_url":"https://job-boards.greenhouse.io/example"}]}]}`. Use `identity_review: true` on a route whose company/board ownership is unresolved; it is skipped by the scanner. For a shared Greenhouse board, `brand_filter` can restrict jobs to an exact brand or a brand-prefixed department. Routes enter as pending checks and become verified after a complete listing read. No old job rows or personal filters are imported.

`--company` limits a refresh to one saved company domain. Companies start `new`: a normal scan admits ATS postings published in the past 72 hours. A complete successful board read marks that company `old` with `validated_at`; later normal scans admit new postings from the past 24 hours and refresh already saved postings still visible in the 72-hour README. `--full-recheck --lookback-days 3` refreshes every currently listed posting for an explicit audit and reports the past-three-day count. Stable provider/board/posting IDs deduplicate repeated reads. Current ATS location/link variants replace stale variants for processed postings. The collectors still fetch full listing pages when an ATS offers no server-side date filter; the time window limits new admissions, not necessarily network reads.

The README shows only open postings seen in the latest complete board scan, with an ATS publication time within 72 hours and a confirmed US location. Older, non-US, date-unknown and unclear-location postings remain in SQLite and the full JSON export. A posting missing from one complete scan is hidden immediately; two complete misses mark it inactive in SQLite. A failed or partial board read cannot close missing postings; a subsequent successful complete read is needed before that board appears in the README. Review the local preview before replacing the root README.

Run the focused checks:

```sh
python3 -m unittest discover -s code/tests -v
```

The root README is the job list, this guide covers the available code, [PLAN.md](PLAN.md) describes the target workflow, and [STAGE.md](STAGE.md) records implementation progress.

For an authorized local run, the [Search Job run skill](../.agents/skills/search-job-run/SKILL.md) coordinates the four distinct AI handoffs and script-run scan. It checks STAGE before using a planned command.
