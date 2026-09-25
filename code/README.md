# Search Job code

Search Job is being built to turn official company job pages into a public, category-organized README and a reusable JSON export. Scripts handle repeatable indexing and title rules; a bounded AI task is reserved for unresolved ATS routes or a missing adapter. [PLAN.md](PLAN.md) explains the full workflow and exact public category rules. [STAGE.md](STAGE.md) shows what has been verified so far.

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

`var/` is ignored by Git. The public README is generated from a separate, read-only conversion of saved records in the private experiment; that conversion helper and its SQLite/JSON files are not part of this public repository. The documented CLI does **not** collect jobs yet, so a newly initialized database renders an empty list. When live collection exists, the same renderer will produce the reviewed root README.

Run the focused stage-one checks:

```sh
python3 -m unittest discover -s code/tests -v
```

The root README is for readers, this guide is for running the available code, [PLAN.md](PLAN.md) is the latest architecture, and [STAGE.md](STAGE.md) is the progress record. Personal application filters and submissions belong outside Search Job.
