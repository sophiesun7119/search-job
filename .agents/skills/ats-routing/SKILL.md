---
name: ats-routing
description: Investigate a Search Job company's unresolved official careers-to-ATS provider route using scripts first and bounded AI only when official evidence is ambiguous.
---

# ATS routing

Use for **AI-2** only when saved job Apply links, redirects, and official company careers pages do not yield a clear ATS host/path through scripts. Start from the company, its official domain, and the original source link. For saved Simplify leads, run `search_job.run --triage-leads --limit N` first; inspect `source_leads.stage`, `route_evidence_url` and `last_error`. Check [STAGE.md](../../../code/STAGE.md) before calling a planned command; [PLAN.md](../../../code/PLAN.md) defines the target evidence chain.

Inspect the saved sample job link and redirect first; compare its ATS with the current official page because a live sample can still be stale. If the official route cannot be found or parsed, make one bounded `company + careers` web search and confirm a result against the official company domain. Embedded jobs or a third-party Apply URL are clues, not proof of an official ATS association. Identify the provider and save the official evidence without asserting a company-board mapping yet. When an official page is readable in a browser or web source but rejects the script, `--confirm-route` records the exact official page and ATS link as AI verification. A user-provided confirmed link is the only case labeled user verification.

If the provider is confirmed and a tested adapter exists, send the candidate board link/token to [board verification](../board-verification/SKILL.md). If no working adapter exists, send the confirmed provider and official board sample to [ATS adapter](../ats-adapter/SKILL.md), then board verification. A prior verified route needs attention only when its recheck is due or evidence changes. An imported route is pending until rechecked; a failed scan alone does not erase it.

If the bounded investigation cannot establish an official provider, record the attempted evidence and exact blocker. Use `--ai-review-lead KEY --ai-review-outcome needs-user --review-note "..."` only when the user can supply a specific official link or fact that would resolve it; otherwise retain AI ownership with an investigating note. The local review Dashboard shows the original Simplify profile, company URL when supplied, original sample Job URL, redirect, candidate official URL, script error, and AI note. A script-created AI work item is not a completed investigation. Hand confirmed routes to board verification or adapter development.
