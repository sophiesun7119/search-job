---
name: search-job-run
description: Coordinate one authorized local Search Job refresh or bounded intake batch, selecting scripts and the company, routing, adapter, and scan skills only when their stages are implemented.
---

# Search Job run

Use this skill when the user explicitly starts/resumes a Search Job run, supplies links or a named list to process, or invokes an installed local schedule. A design discussion is not a run. Read [STAGE.md](../../../code/STAGE.md) for available commands and [PLAN.md](../../../code/PLAN.md) for the current target flow; do not execute a planned capability as if it already existed.

Choose one bounded unit and its saved cursor: a refresh of verified boards, a batch from a user-named list such as Simplify, a set of supplied links, or a requested AI company-discovery batch. Reuse known companies, routes, boards and adapters. Do not restart the entire source or widen to unrequested companies. Keep the input compact and one platform or batch at a time.

Route work by what is missing:

| Need | Use |
| --- | --- |
| New company leads or resumable source parsing | [Company discovery](../company-discovery/SKILL.md) |
| Unresolved official ATS provider route | [ATS routing](../ats-routing/SKILL.md) |
| Confirmed provider without a working collector | [ATS adapter](../ats-adapter/SKILL.md) |
| Known provider and adapter, unresolved company-board mapping | [Board verification](../board-verification/SKILL.md) |
| Verified board with a tested adapter | [Job search](../job-search/SKILL.md) |

Let scripts perform known-route checks, board scans, identity, date handling, classification and export. The four conditional AI missions are requested company discovery (AI-1), unresolved official ATS route (AI-2), confirmed provider missing an adapter (AI-3), and unresolved company-to-board verification after provider/adapter are known (AI-4). A schedule or script-created queue item does not itself perform AI reasoning. Retry the affected board after a successful route/adapter fix; after a concrete failed AI attempt, record the exact blocking step for review.

For the existing company pool, use the implemented local route-seed importer and `search_job.run` scanner described in [code usage](../../../code/README.md). The lookback window controls the recent count, while all current listings enter SQLite. Inspect the generated local README and JSON before replacing the root README; report company, provider, complete/partial board, opening, blocked-route and failure counts. Review Git diffs before an authorized development publication to `origin/dev`. Never update `main` without the user's explicit merge request. New-company intake and unattended scheduling remain planned.
