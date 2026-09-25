---
name: company-discovery
description: Collect and normalize a bounded Search Job company-lead batch from requested AI discovery, user links, or a named third-party list; hand unresolved companies to ATS routing.
---

# Company discovery

Use this skill for **AI-1** only when new company discovery is requested, or to normalize a user-supplied/named-list lead batch without AI. Read [STAGE.md](../../../code/STAGE.md) before calling a workflow; planned intake scripts are not yet available merely because they appear in [PLAN.md](../../../code/PLAN.md).

Choose the entrance the user requested: bounded AI/web discovery, supplied company or job/application links, or a named list such as Simplify. Preserve its **Application** URL when present, along with company name, plausible official domain, source, and the cursor or source position needed to resume a large list. Process one bounded batch from the saved position; do not repeatedly restart a thousand-company source or expand the search scope on your own.

Normalize and deduplicate with scripts where implemented. Skip a company whose verified route is still current, but keep a new application link as evidence if it may reveal a changed board. A third-party Apply URL is a lead, never proof of company-to-board ownership. Send genuinely new, stale or uncertain routes to [ATS routing](../ats-routing/SKILL.md), with the original link and source. This skill does not scan jobs, classify titles, or handle applications.
