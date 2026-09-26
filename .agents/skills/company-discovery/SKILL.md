---
name: company-discovery
description: Collect and normalize a bounded Search Job company-lead batch from requested AI discovery, user links, or a named third-party list; hand unresolved companies to ATS routing.
---

# Company discovery

Use this skill for **AI-1** only when new company discovery is requested, or to normalize a user-supplied/named-list lead batch without AI. Read [STAGE.md](../../../code/STAGE.md) before calling a workflow. The bounded Simplify catalog importer is implemented; other named-list parsers may still be planned.

Choose the entrance the user requested: bounded AI/web discovery, supplied company or job/application links, or a named list such as Simplify. Preserve its **Application** URL when present, along with company name, plausible official domain, source, and the cursor or source position needed to resume a large list. Process one bounded batch from the saved position; do not repeatedly restart a thousand-company source or expand the search scope on your own.

For Simplify, use `search_job.run --simplify-catalog <local-catalog> --source-year 2026 --limit N`. It selects the next unimported pending company IDs with sample Apply URLs, skips existing company names, and saves all evidence in `source_leads`. Check that the selected count equals the requested bounded batch; do not silently fill gaps with other years. Normalize and deduplicate with scripts where implemented. A third-party Apply URL is a lead, never proof of company-to-board ownership. Send unresolved official routes to [ATS routing](../ats-routing/SKILL.md), with the original link and source.
