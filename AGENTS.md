# Search Job project guidance

The data model, renderer, JSON export, route-seed and bounded Simplify lead import, and eleven collectors have passed local tests. The public root README is a generated past-72-hour, US-location-filtered view of the saved local live index; the full JSON export remains local. Companies have `new`/`old` scan cohorts with 72-hour/24-hour processing windows. Do not claim that every imported lead has an officially verified route or that scheduling is implemented. Read `code/STAGE.md` for the current verified scope.

Search Job finds and publishes public job openings. Keep credentials and machine-specific paths out of the repository. Official company and ATS evidence establish board routes. Scripts handle routine recognition and scanning; an actual AI task handles requested discovery, unresolved route/board evidence, or adapter development. A script-created work item does not mean AI has completed it.

For an authorized local run, use `.agents/skills/search-job-run/` to coordinate one bounded batch. Its four conditional AI handoffs have separate skills: company discovery, official ATS investigation, adapter development, and company-board verification. Routine scans and public title classification stay script-run. Read `code/STAGE.md` before invoking any planned capability.

When the user requests "import 50/100 companies from Simplify," take the next unimported 2026 leads with saved sample Apply links from the local catalog. Keep all selected leads and their exact route/adapter/board/scan stage in `source_leads`; do not place a lead in `companies` from third-party evidence alone. Confirm ATS association from official company pages, reuse tested adapters, build a missing adapter only for a confirmed provider, then scan only the new verified boards with a 72-hour admission window. Resolve failures at the affected stage and preserve the batch cursor. Regenerate the root README only from completed board scans. The full procedure and current commands are in `.agents/skills/search-job-run/SKILL.md`.

Work in bounded batches. After a real bounded test, inspect the generated README and JSON and report company candidates, confirmed and adapter-pending providers, complete and partial boards, stored openings, blocked routes and failures. Do not run searches during design discussion.

Treat `code/README.md` as concise usage for verified code, `code/PLAN.md` as the latest target architecture and category rules, and `code/STAGE.md` as implementation progress. Edit the root README introduction in `code/templates/README-intro.md`, then regenerate it; the root README holds all category tables. Before publishing, inspect the exact tracked files and Git history for sensitive data.

## Git branches

Use `dev` as the local working branch and push reviewed development commits to `origin/dev`. Inspect the diff, choose a descriptive commit title and body, and verify the pushed branch. Do not merge, push, or otherwise update `main` or `origin/main` unless the user explicitly asks to merge the completed development work. If `main` changes independently, fetch and reconcile it on `dev` without changing `main`.
