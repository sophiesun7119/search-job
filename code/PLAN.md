# Search Job extraction plan

Status: scaffold only. These steps remain to be implemented and verified.

1. Extract the nine already implemented ATS collectors and their tests from the frozen experiment. Preserve their provider-specific parsing while consolidating shared routing, identity, and date logic.
2. Add a single provider capability registry. Import previously verified company-to-board mappings as sourced leads needing targeted rechecks. Start with empty job and title-observation tables.
3. Complete full-board scanning, job identity, source-date semantics, last-seen and open state, multi-label categories, and clear failures.
4. Generate the public root README, category Markdown lists, and a versioned JSON export from Search Job's local database. Keep private databases and run logs out of Git.
5. Verify a bounded real run and its downstream private Dashboard, then add local scheduled refreshes. AI-required work runs only in an actual agent task.

`code/README.md` will describe only completed behavior as each gate passes. The public root README will show listings only after a verified export exists.
