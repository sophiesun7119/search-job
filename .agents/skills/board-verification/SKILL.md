---
name: board-verification
description: Investigate one unresolved Search Job company-to-ATS-board association after the provider and adapter are known; verify official ownership and board readability.
---

# Board verification

Use for **AI-4** only: the company and ATS provider are known, a working adapter exists, but script checks cannot prove the correct company-to-board URL/token, brand scope, or board readability. Check [STAGE.md](../../../code/STAGE.md) for runnable tools and [PLAN.md](../../../code/PLAN.md) for the route and board contract. Do not use this skill to discover a provider from scratch or build its adapter; those belong to [ATS routing](../ats-routing/SKILL.md) and [ATS adapter](../ats-adapter/SKILL.md).

Inspect the official company careers page and its job/Application links. For a named-list lead, begin with `source_leads` and its sample Apply URL, then verify the route from the official site; `route_evidence_url` must point to the official page, not only the third-party source. Follow redirects or embedded job links only far enough to establish the official company-to-board association. Compare the candidate board's titles, company/brand evidence and canonical Apply URLs with the official source; use a bounded adapter read to confirm the board is readable. Keep provider capability, board identity, and company association separate. A shared board may serve multiple brands, and a company may have multiple boards.

A successful handoff records the company, provider, board URL/token, official evidence, brand scope, verification time and bounded-read result, then sends the verified route to [job search](../job-search/SKILL.md). If the board is unreadable because the adapter is broken, hand that defect to [ATS adapter](../ats-adapter/SKILL.md). If the official evidence remains insufficient after the bounded AI attempt, keep the mapping unverified and record the exact blocker with `--ai-review-lead KEY --ai-review-outcome needs-user --review-note "..."`; the local Dashboard will preserve its source and current links for user review. Do not activate or scan it as a confirmed company route. Do not infer failure of a previously verified association from one failed scan.
