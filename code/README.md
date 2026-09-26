# Search Job code

Search Job finds public openings from official company job pages and organizes them into a category-based README and a reusable JSON export. Scripts handle repeatable indexing and title rules; bounded AI tasks handle requested company discovery and unresolved ATS, adapter or board work. [PLAN.md](PLAN.md) explains the full workflow and category rules. [STAGE.md](STAGE.md) shows what has been verified so far.

[SCHEMA.md](SCHEMA.md) documents every current SQLite table, its columns and relationships.

**Today:** local SQLite indexing, title categories, README/JSON rendering, route-seed import and live collectors for the existing company pool work. Bounded Simplify lead import and script-first official-route checks are available; unresolved routes still need review. The root [job list](../README.md) shows open, ATS-dated postings from the past 72 hours with a confirmed US location and a complete latest board scan. The full index remains in SQLite and JSON. A local preview is generated under ignored `var/` during a run.

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

Import a bounded batch from a local Simplify catalog, then investigate its leads without re-importing earlier source IDs:

```sh
PYTHONPATH=code/src python3 -m search_job.run var/search-job.sqlite3 \
  --simplify-catalog /path/to/catalog.sqlite3 --source-year 2026 --limit 100
PYTHONPATH=code/src python3 -m search_job.run var/search-job.sqlite3 --triage-leads --limit 100
PYTHONPATH=code/src python3 -m search_job.run var/search-job.sqlite3 \
  --scan --new-leads-only --provider ashby --limit 100
```

The catalog's company and sample Apply link become a `source_leads` row, not a verified company-board route. Script checks follow the candidate official site to find its careers/ATS links. Unsupported providers remain `adapter_pending`; ambiguous or inaccessible routes remain pending with their last error. Once a missing provider collector has passed a live board test, `--activate-adapter PROVIDER` registers its officially evidenced leads for scanning. Run one provider at a time and inspect the source-lead stages before publishing; only a complete board scan promotes a new company to the `old` cohort.

`--triage-leads` checks each saved Apply URL and redirect first, extracts an ATS hint, then resolves missing company domains and checks official careers pages for the current board. A live third-party sample does not activate its board. If an official page rejects the script but AI verifies its exact ATS link, use `--confirm-route LEAD_KEY --evidence-url OFFICIAL_PAGE --board-url ATS_LINK`; this records `ai_official_page`. Only use `--confirmation-source user` if the user supplied or confirmed the official link. `--route-report` counts source methods and exact sample-board matches; unattributed older rows are kept separate. `--verify-routes --lead-key LEAD_KEY` retries one lead after a parser fix. See the run skill for the script-first, AI-on-failure order.

Each `search_job.run` call refreshes the **local review Dashboard** at `var/review-dashboard.html`. It shows every unfinished Simplify lead, its script error, AI review state, original Simplify profile, original sample Job link and redirect, and the company website from either the catalog, the Simplify profile or current investigation. The catalog's `canonical_domain` is copied when present; it is empty for all companies in the first 100-lead batch, so the Dashboard says so rather than inventing an original catalog URL. Run `--preserve-profile-links --limit 100` once to retain websites extracted from older saved Simplify profiles without changing route decisions. The generated HTML and SQLite remain ignored by Git; open the HTML locally to review and filter companies.

Script failures enter `ai_pending`, which means **AI has not yet finished**. After investigating one lead, record the attempt with `--ai-review-lead simplify:ID --ai-review-outcome investigating --review-note "what was checked"`. Only after an actual AI attempt cannot resolve it, use `--ai-review-outcome needs-user --review-note "exact blocker and link needed"`; that state and note appear on the Dashboard. A confirmed route or completed scan clears the review queue. The Dashboard is read-only: provide a corrected official link to the Search Job task for script/AI verification and database update.

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
