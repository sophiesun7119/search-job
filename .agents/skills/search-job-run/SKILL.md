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

For a requested Simplify batch (for example, "import 50" or "import 100"), read the local Simplify catalog and import the next unimported 2026 source IDs with `search_job.run --simplify-catalog ... --source-year 2026 --limit N`. The importer skips names already in the company pool and saves source position, profile, sample Apply URL, provider hint and exact stage in `source_leads`; repeat requests advance rather than restart. For unresolved leads, run `--triage-leads --limit N`: its enforced order is saved job Apply link and redirect first, candidate company-site resolution second, official careers-to-ATS verification third. Use `--verify-routes --lead-key` for one retry after a parser fix. A 200 response or recognizable ATS host in a third-party sample is a clue, never ownership proof.

At each gate, use the script first and invoke the matching bounded AI task when the script fails or evidence conflicts. AI-2 inspects the official page, follows its job/Apply links, and may use one `company + careers` search; compare the current ATS with the saved sample because sites migrate. If the official page blocks script access but its exact ATS link is confirmed through another read-only source, record it with `--confirm-route LEAD_KEY --evidence-url OFFICIAL_PAGE --board-url EXACT_ATS_LINK`. This is `ai_official_page`; reserve `--confirmation-source user` and `user_official_page` for an official link supplied or confirmed by the user. AI-3 builds or repairs one reusable adapter when the confirmed provider is unsupported, with a fixture and live board test before activation. AI-4 resolves ambiguous board tokens or brand ownership and retries the affected script check. Keep exact failures in `source_leads` and advance only after the gate succeeds. Do not use an unverified sample board to bypass a failed gate. Report script-confirmed and AI-confirmed routes separately using `--route-report`; keep older unattributed rows separate rather than guessing their method.

After a script failure, leave the company in `ai_pending` on `var/review-dashboard.html`; this is a queue, not evidence that AI has already tried. When AI begins one bounded investigation, record `--ai-review-lead KEY --ai-review-outcome investigating --review-note "..."`. If the actual AI attempt still cannot establish official evidence, record `--ai-review-outcome needs-user` with the concrete blocker and the exact link or answer the user could supply. Open the refreshed Dashboard and tell the user which records need their input. Do not mark the whole failed script batch `needs-user` without per-company AI work. If the route is resolved, use `--confirm-route` or retry the corrected script; successful scans leave the unresolved queue. Preserve original Simplify sample and company-profile links in the Dashboard even when the current ATS changed.

Scan only evidenced new-company boards with `--scan --new-leads-only --provider ...`. New companies admit source-published jobs from the past 72 hours and become `old` only after one complete scan. Store all admitted jobs in SQLite, then render and review the local README/JSON before replacing the public README. Report the selected 50/100 lead count, routes and adapters by stage, complete/partial boards, recent jobs, README survivors, blocked leads and failures. Review Git diffs before an authorized development publication to `origin/dev`; never update `main` without an explicit merge request. Unattended scheduling remains planned.
