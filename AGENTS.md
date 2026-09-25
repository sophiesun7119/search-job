# Search Job project guidance

Stage 1 has a database model, renderer, JSON export, and a labeled historical preview. Do not claim that live collectors, schedules, current verified public listings, or Experiment 2 handoff are active until their code and a verified run exist.

Keep Search Job independent of personal profiles, application data, private dashboards, and machine-specific paths. Official company and ATS evidence establish board routes. Scripts handle routine recognition and scanning; an actual AI task handles requested discovery, unresolved route/board evidence, or adapter development. A script-created work item does not mean AI has completed it.

For an authorized local run, use `.agents/skills/search-job-run/` to coordinate one bounded batch. Its four conditional AI handoffs have separate skills: company discovery, official ATS investigation, adapter development, and company-board verification. Routine scans and public title classification stay script-run. Read `code/STAGE.md` before invoking any planned capability.

Work in bounded batches. After a real bounded test, refresh and inspect the private Application Dashboard through its documented handoff and report candidate count, confirmed and adapter-pending providers, scanned boards, retained and blocked counts, and failures. Do not run searches or submissions during design discussion.

Treat `code/README.md` as concise usage for verified code, `code/PLAN.md` as the latest target architecture and public rules, and `code/STAGE.md` as implementation progress. Edit the root README introduction in `code/templates/README-intro.md`, then regenerate it; the root README holds all public category tables. Before publishing, inspect the exact tracked files and Git history for private data.

## Git branches

Use `dev` as the local working branch and push reviewed development commits to `origin/dev`. Inspect the diff, choose a descriptive commit title and body, and verify the pushed branch. Do not merge, push, or otherwise update `main` or `origin/main` unless the user explicitly asks to merge the completed development work. If `main` changes independently, fetch and reconcile it on `dev` without changing `main`.
