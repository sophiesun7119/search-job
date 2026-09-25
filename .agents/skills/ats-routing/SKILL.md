---
name: ats-routing
description: Investigate a Search Job company's unresolved official careers-to-ATS provider route using scripts first and bounded AI only when official evidence is ambiguous.
---

# ATS routing

Use for **AI-2** only when the official company careers page and saved Application links do not yield a clear ATS host/path through scripts. Start from the company, its official domain, and the original source link. Check [STAGE.md](../../../code/STAGE.md) before calling a planned command; [PLAN.md](../../../code/PLAN.md) defines the target evidence chain.

Use official careers/job links first. If the route cannot be found or parsed, make one bounded `company + careers` web search and confirm a result against the official company domain. Embedded jobs or a third-party Apply URL are clues, not proof of an official ATS association. Identify the provider and save the official evidence without asserting a company-board mapping yet.

If the provider is confirmed and a tested adapter exists, send the candidate board link/token to [board verification](../board-verification/SKILL.md). If no working adapter exists, send the confirmed provider and official board sample to [ATS adapter](../ats-adapter/SKILL.md), then board verification. A prior verified route needs attention only when its recheck is due or evidence changes. An imported route is pending until rechecked; a failed scan alone does not erase it.

If the bounded investigation cannot establish an official provider, record the unresolved route with the attempted evidence for review. A script-created AI work item is not a completed investigation. Hand confirmed routes to board verification or adapter development.
