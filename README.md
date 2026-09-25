# Search Job

Search Job is being separated from a private Job Apply experiment so that company discovery, official ATS routing, and public job listings can be developed and shared independently.

**Current status:** repository scaffold. No live collectors, scheduled refresh, or job listings have been moved into this repository yet. The existing tested ATS adapters remain in the frozen experiment until the next extraction stage.

## Job lists

The public job tables will appear on this page, grouped by category, after a verified export from Search Job's own local database. The broad mid-to-senior SDE view will appear first, followed by other categories and levels. There are no published openings in this scaffold.

## How it will work

Company leads can come from a bounded AI discovery task, a supplied job or application link, or a named third-party list. Official company and ATS evidence will establish a board route. Reusable adapters will collect openings, which will be grouped into multiple job categories. This README will show category links, active job tables, and collapsed inactive roles as a snapshot of that database; personal application filters and submission data belong elsewhere.

The [code guide](code/README.md) records what exists now, and the [plan](code/PLAN.md) tracks the extraction work. A future local refresh will regenerate this README. GitHub reflects a refresh only after the generated changes are committed and pushed.
