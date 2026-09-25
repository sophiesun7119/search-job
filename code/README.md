# Search Job code

**Current status:** stage-one database model and deterministic README/JSON renderer are implemented. The root README is a clearly labeled **historical preview** built from saved ATS posting records. This repository still has no live company intake, ATS collector, official recheck, private Experiment 2 handoff, or schedule. No row in that preview has been confirmed open by this new pipeline.

## What runs now

| Part | Executor | Current behavior |
| --- | --- | --- |
| Schema and identity | Script | SQLite keeps companies, pending board routes, postings, application/location variants, source dates, observations, tags, and scan outcomes. A provider + board + posting ID identifies an opening; canonical URL is fallback evidence. |
| Category rules | Script | Title-first rules create explainable SDE/level, Frontend, Mobile, QA/Test, Analyst, Scientist/Researcher, or Other tags. No per-posting AI judgment or private profile is used. |
| Date and open state | Script | Earliest reliable publication time persists across same-ID updates; otherwise Age uses first discovery with a 🔎 marker. Only complete scans can count a missing posting toward closure. |
| Output | Script | The root README has category links and Company, Role, Location, Application, Age tables. A versioned JSON export comes from the same DB. The renderer accepts an explicit `--as-of` timestamp for repeatable output. |
| Historical preview | Private local helper | A read-only conversion of the old private cache built the current root README. All imported posting states are `unknown`; old personal filter decisions are never copied. The preview SQLite and JSON stay under ignored `var/`. |

Initialize an empty local database from the repository root:

```sh
PYTHONPATH=code/src python3 -m search_job.cli var/search-job.sqlite3
```

Render an indexed database with a fixed timestamp:

```sh
PYTHONPATH=code/src python3 -m search_job.cli var/search-job.sqlite3 \
  --markdown README.md --json var/openings.json --as-of 2026-09-25T15:30:00Z
```

The current historical preview was generated with the private workspace helper `scripts/build-search-job-stage1-preview.py`; that helper is outside this public repository and does not affect the production empty database. Review the generated README and JSON before any Git push. Personal application filtering and the Application Dashboard remain in Experiment 2.

## Planned pipeline

Company leads will come from bounded AI discovery, user-supplied links, or named third-party lists. Scripts will verify official company-to-ATS board routes; actual AI tasks will investigate unresolved providers and build/test missing adapters. Nine existing provider collectors will be extracted and checked. Complete board scans will populate the public opening index; a versioned JSON handoff will feed Experiment 2. See [PLAN.md](PLAN.md) for the remaining stage gates.
