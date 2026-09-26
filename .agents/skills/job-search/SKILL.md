---
name: job-search
description: Run a bounded Search Job scan of already verified ATS boards, normalize openings, and regenerate the public root README and JSON export when the live collector stage exists.
---

# Job search

Use a verified company-to-board route and a tested adapter. Check [STAGE.md](../../../code/STAGE.md) first for supported providers and current gaps; the existing-pool live scanner is documented in [code usage](../../../code/README.md). [PLAN.md](../../../code/PLAN.md) defines the identity, date, open-state, and category contract; use implemented rules in `code/src/search_job/` rather than reinterpreting every title with AI.

Scan a bounded set of boards with complete pagination. For a new Simplify intake, use `search_job.run --scan --new-leads-only --provider <provider>` so existing company boards are not rescanned. Prefer listing API fields; reuse a description already returned and fetch a separate detail only for ambiguous classification or selected optional evidence. Preserve provider + board + posting ID, canonical Apply URL, all location/link variants, raw date field and precision, first/last seen, and complete/partial/failed scan outcome. Updates to the same posting do not reset publication or first-discovery age. A failed or incomplete scan cannot close previously seen jobs.

Apply title-based categories without per-posting AI judgment. Store openings in Search Job SQLite; generate the README preview and versioned JSON export from that database. Review category counts, official links, date markers, output size and unresolved board failures before replacing the public root README. Do not create a separate `lists/` output.

After a real bounded search test, inspect the generated README and JSON, then report candidate companies, confirmed/adapter-pending providers, complete/partial boards, stored and recent openings, blocked routes and failures. State which route or collector step remains unfinished when a test cannot complete.
