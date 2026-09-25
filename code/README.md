# Search Job code

Search Job finds public openings from official company job pages and organizes them into a category-based README and a reusable JSON export. Scripts handle repeatable indexing and title rules; bounded AI tasks handle requested company discovery and unresolved ATS, adapter or board work. [PLAN.md](PLAN.md) explains the full workflow and category rules. [STAGE.md](STAGE.md) shows what has been verified so far.

**Today:** the SQLite model and README/JSON renderer work locally. The root [job list](../README.md) is a labeled historical preview; this repository does not yet run live collectors or verify that those saved links are still open.

## Run the available code

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

`var/` is ignored by Git. The current root README is a historical preview generated from a read-only cache; the conversion helper and source cache are not included here. The documented CLI does **not** collect jobs yet, so a newly initialized database renders an empty list. When live collection exists, the same renderer will produce the reviewed root README.

Run the focused stage-one checks:

```sh
python3 -m unittest discover -s code/tests -v
```

The root README is the job list, this guide covers the available code, [PLAN.md](PLAN.md) describes the target workflow, and [STAGE.md](STAGE.md) records implementation progress.

For a future authorized local run, the [Search Job run skill](../.agents/skills/search-job-run/SKILL.md) coordinates the four distinct AI handoffs and script-run scan. It checks STAGE before using any planned command.
