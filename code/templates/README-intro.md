# Search Job

Search Job finds public job openings and organizes them by role. It gathers company career and ATS listings into a local job index, then publishes US-located roles in the category tables here.

{{SNAPSHOT_STATUS}}

- **Browse what matters to you:** start with the broad Software Engineering list or jump to Product Manager, Engineering Manager, Analyst and other categories below.
- **See where a role came from:** each row links a company and a saved application page; Age distinguishes an ATS publication date from the time we first found a role.
- **Understand and improve the rules:** the classification logic is public, so contributors can suggest better title matches with concrete examples.

This project is developed with AI assistance. The intended live workflow uses scripts for repeatable company/board checks, collection and classification; bounded AI tasks find new companies and resolve missing ATS routes, adapters or board mappings. The [code guide](code/README.md) explains how to use what exists now, the [architecture and category rules](code/PLAN.md) explain the full workflow, and the [stage record](code/STAGE.md) shows what has actually been verified. A local scheduled refresh is planned after live collection is stable.
