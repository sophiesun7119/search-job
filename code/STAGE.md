# Implementation stage

This file tracks **verified progress and next gates**. The target workflow and public filter rules live in [PLAN.md](PLAN.md); the code entry point and commands live in [README.md](README.md). Update this file when a stage passes or its scope changes. A planned step below is not a claim that it currently runs.

| Stage | State | Evidence and next gate |
| --- | --- | --- |
| 0. Public repository scaffold | Complete | Separate `search-job/` repository, private/public boundary, `dev` workflow and documented target. |
| 1. Data and output contract | Complete for local fixtures and historical preview | SQLite schema, opening identity/variants, title categories, age/open-state rules, deterministic README/JSON renderer and focused tests exist. A read-only old-cache projection produced the labeled root README from 78 known companies: 50 have 797 saved ATS postings; one custom-careers row lacked a verified board and was excluded. All preview postings have **unknown** current open state. The independent production DB starts with an empty openings table. |
| 2. Collector extraction | Next | Move and recheck the nine existing provider collectors and their fixtures without private profile or Dashboard dependencies. Confirm full pagination, provider-specific IDs/dates and listing-first detail use. |
| 3. Company intake and routes | Planned | Implement three lead entrances, official script-first ATS discovery, provider capability registry and company-to-board verification. Import old route mappings only as pending-recheck seeds. |
| 4. Bounded live loop and private handoff | Planned | Recheck a small set of official boards, scan, classify, render, and export JSON; import at most 10 new private candidates per batch. After a real test, refresh and inspect the separate private Dashboard and report counts/failures. |
| 5. Local refresh and release | Planned | Add a local periodic refresh after live runs are stable; review generated changes, tests, paths and public Git history before publication. No GitHub Actions or unattended AI task is assumed. |

**Current limit:** the README is a historical layout preview. It is not a current-openings feed; no new company discovery, ATS scan, route recheck, adapter extraction, Experiment 2 JSON import or schedule has run in this repository. No personal filter state or private database is published.
