---
name: ats-adapter
description: Research, implement, and verify one reusable Search Job ATS collector when an official provider is confirmed and no working adapter exists.
---

# ATS adapter

Use for **AI-3** only after [ATS routing](../ats-routing/SKILL.md) confirms a provider and an official sample board that existing capabilities cannot read. The sample board does not by itself prove a particular company's route. Check [STAGE.md](../../../code/STAGE.md) and `code/src/search_job/collectors.py` first for active providers and remaining gaps. Do not create a duplicate adapter for a company whose provider is already supported.

On one provider at a time, inspect the official careers/board surface and its public listing mechanism. Build a **provider-reusable** collector, preserving provider posting ID, official Apply URL, location variants, source date field/value/precision, and pagination or completeness status. Prefer listing response fields and defer extra job detail reads until needed. Keep shared identity, category and open-state policy outside provider-specific parsing.

Verify with a representative fixture and a bounded official-board read. An adapter is ready when the provider is recognized, its sample board can be fully read, and normalized jobs have stable identities and links. Hand the tested capability and official sample to [board verification](../board-verification/SKILL.md) for the separate company-board decision, then a targeted scan. If the adapter attempt fails on code, pagination, or a provider API, keep the lead in AI work with the exact technical blocker and continue repair; do not label it `needs-user` or ask for a company link that cannot fix the adapter. Use `needs-user` only when a specific missing company or board fact can be supplied by the user. A queued work item is not a tested adapter.
