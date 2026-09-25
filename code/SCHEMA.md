# Search Job SQLite schema

The executable schema is [`src/search_job/schema.sql`](src/search_job/schema.sql). This page explains the **current** local database, not the later intake workflow in [PLAN.md](PLAN.md). The SQLite file is normally `var/search-job.sqlite3` and is ignored by Git. Timestamps are UTC ISO 8601 text; nullable fields may be unknown.

## Relationships

`companies` is the company pool. `company_boards` links a company to one or more `boards`; a board records its ATS provider and route token. `scan_runs` records attempts against boards. `openings` holds one logical posting per stable key. `opening_variants` holds its locations and application URLs, and `opening_tags` holds its category and level rules. The README and JSON are generated projections, not additional database tables.

| Table | Primary key | Columns and meaning |
| --- | --- | --- |
| `companies` | `company_key` (domain) | `name` display name; `official_url` company site; `source` how this pool entry was imported. Pool membership alone does not verify an ATS route. |
| `provider_capabilities` | `provider` | `adapter_key` collector identifier; `support_status` is `planned`, `tested`, or `active`. **Currently empty:** the seven working collectors are selected in `collectors.py`, not registered in this table. Do not use its row count to judge collector coverage. |
| `boards` | `board_key` | `provider` ATS type; `board_token` provider-specific route; `board_url` saved route URL; `route_status` is `pending_recheck`, `active`, or `failed`; `last_complete_scan_at` is set only after a complete scan. `(provider, board_token)` is unique. |
| `company_boards` | (`company_key`, `board_key`) | Foreign keys to `companies` and `boards`; `evidence_url` saved route evidence; `brand_filter` optional shared-board restriction; `checked_at` last completed check; `status` is `pending_recheck`, `pending_identity`, `verified`, or `failed`. A listing read can mark a route verified, but it does not by itself prove disputed company ownership. |
| `scan_runs` | `scan_key` | `board_key` foreign key; `started_at`, `finished_at`; `outcome` is `complete`, `partial`, or `failed`; nullable `error`. The current scanner records failed attempts with `error` unset; the run report carries the exception text. Multiple attempts at one board create multiple rows. |
| `openings` | `opening_key` | `company_key`, optional `board_key` foreign keys; `provider`, optional `provider_job_id`; `canonical_url`, `title`; `open_state` is `open`, `inactive`, or `unknown`; `source_date_field`, `source_date_value`, `source_date_precision` preserve ATS date provenance; `published_at` is the earliest saved publication time; `updated_at` the latest saved update; `first_seen_at`, `last_seen_at` are local observations; `status_evidence` explains state; `missing_complete_scans` counts consecutive complete scans where this posting was absent. `(provider, board_key, provider_job_id)` is unique when both optional identity fields exist. |
| `opening_variants` | (`opening_key`, `location`, `apply_url`) | `opening_key` foreign key to `openings`; one posting can have multiple locations and application URLs without becoming multiple postings. |
| `opening_tags` | (`opening_key`, `tag`) | `opening_key` foreign key; `tag` contains a README category or `level:*`; `rule_version` and `evidence` record which title rule assigned it. One posting may have multiple category tags. |

The broad Senior/unspecified, Junior/New Grad, Staff/Principal, Product Manager, Engineering Manager and other sections in the root README come from `opening_tags` joined to `openings`. They are **not separate SQLite tables**. The title rules live in [`src/search_job/core.py`](src/search_job/core.py), and the renderer lives in [`src/search_job/render.py`](src/search_job/render.py). All currently listed jobs are stored, including those older than a three-day lookback; `--lookback-days` affects the scan report's recent count only.

To inspect a local copy without modifying it, run `sqlite3 -readonly var/search-job.sqlite3 '.schema'`. For row counts, use `SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;` and `SELECT COUNT(*) FROM openings;` in a read-only SQLite session.
