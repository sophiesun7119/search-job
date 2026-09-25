# Search Job code

Search Job finds public openings from official company job pages and organizes them into a category-based README and a reusable JSON export. Scripts handle repeatable indexing and title rules; bounded AI tasks handle requested company discovery and unresolved ATS, adapter or board work. [PLAN.md](PLAN.md) explains the full workflow and category rules. [STAGE.md](STAGE.md) shows what has been verified so far.

**Today:** local SQLite indexing, title categories, README/JSON rendering, route-seed import and live collectors for the seven providers in the current company pool work. The root [job list](../README.md) remains a labeled historical preview until a reviewed live export replaces it. A live export is generated under ignored `var/` during a local run.

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

`var/` is ignored by Git. The current root README is a historical preview generated from an earlier cache; the conversion helper and source cache are not included here.

Import a portable JSON seed containing companies and their existing ATS routes, then scan one provider at a time:

```sh
PYTHONPATH=code/src python3 -m search_job.run var/search-job.sqlite3 \
  --seed var/route-seed.json
PYTHONPATH=code/src python3 -m search_job.run var/search-job.sqlite3 \
  --scan --provider greenhouse --lookback-days 3 \
  --markdown var/README-live-preview.md --json var/openings-live.json
```

The seed format is `{"companies":[{"name":"Example","domain":"example.com","routes":[{"provider":"greenhouse","board_token":"example","evidence_url":"https://job-boards.greenhouse.io/example"}]}]}`. Use `identity_review: true` on a route whose company/board ownership is unresolved; it is skipped by the scanner. For a shared Greenhouse board, `brand_filter` can restrict jobs to an exact brand or a brand-prefixed department. Routes enter as pending checks and become verified after a complete listing read. No old job rows or personal filters are imported.

`--lookback-days` controls the **recent count in the run report**. All currently listed jobs enter the database, including older roles. A repeated scan updates the same provider/board/posting identity instead of creating a duplicate; it keeps the earliest observed publication date. If the ATS gives no publication date, the first discovery timestamp drives Age and carries a 🔎 marker. A partial board read adds observed jobs but does not mark absent jobs inactive. The local preview can be reviewed before replacing the root README.

Run the focused checks:

```sh
python3 -m unittest discover -s code/tests -v
```

The root README is the job list, this guide covers the available code, [PLAN.md](PLAN.md) describes the target workflow, and [STAGE.md](STAGE.md) records implementation progress.

For an authorized local run, the [Search Job run skill](../.agents/skills/search-job-run/SKILL.md) coordinates the four distinct AI handoffs and script-run scan. It checks STAGE before using a planned command.
