# Search Job code

This is a repository scaffold. It does not yet contain runnable discovery, routing, adapter, collection, classification, or export code. The existing tested ATS collectors will be extracted in a later stage without rebuilding them from scratch.

## Planned responsibilities

| Stage | Executor | Intended result |
| --- | --- | --- |
| Company lead intake | AI for bounded discovery; scripts for supplied links and named lists | Candidate company and useful application link |
| Official ATS and board routing | Script first; AI only for unresolved evidence | Verified company-to-board route |
| New ATS adapter | AI task develops it; fixture and scripts verify it | Reusable collector or concrete failure |
| Board scan, identity, dates, and open state | Scripts | Normalized opening index |
| Public categories and Markdown/JSON export | Rules and scripts, with review for ambiguous tags | Root README, category lists, versioned JSON |

This table describes the intended design, not completed behavior. See [PLAN.md](PLAN.md) for implementation gates. The root [README](../README.md) is the public result page; this document describes the implementation.
