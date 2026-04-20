# Historical Marker Workflow

This project scaffolds a Box-centered intake automation for the Krewe TU History digital historical marker project. It treats Box as the canonical content system, performs a first-pass AI and rules-based review, generates structured editorial artifacts, and routes each submission into auditable review queues without publishing anything automatically.

## What is included

- A modular Python worker with CLI entrypoints for `poll`, `process-submission`, `reconcile`, and `rebuild-artifacts`
- A `review-airtable` command that reviews dossier-ready Airtable submissions, writes AI copy, and advances workflow status
- A `build-site` command that exports approved public stories into a sibling static website folder
- A `sync-supabase` command that uploads the public story payload and media into Supabase for runtime delivery
- A local filesystem Box adapter so the workflow can be exercised without live Box credentials
- An OpenAI-ready provider interface with a heuristic fallback for offline development
- SQLite-backed state tracking for processed files, hashes, runs, and submission snapshots
- Prompt files, markdown templates, and tests for grouping, duplicate detection, review decisions, and routing

## Quick start

1. Set `BOX_ROOT_PATH` to a directory that mirrors the Box project root, or let the app create `./box_project_root`.
2. Add incoming files to `BOX_ROOT_PATH/intake`.
3. Run:

```bash
PYTHONPATH=src python3 -m marker_workflow.cli poll
```

4. Review generated canonical packages under `processing/YYYY/MM/SUB-...` and reviewer packets under `review/<queue>/YYYY/MM/SUB-...`.
5. Build the website payload from approved content:

```bash
PYTHONPATH=src python3 -m marker_workflow.cli build-site --source-mode approved
```

To build the website directly from Airtable instead:

```bash
PYTHONPATH=src python3 -m marker_workflow.cli build-site --source-mode airtable
```

To process dossier-ready Airtable submissions and generate AI copy:

```bash
PYTHONPATH=src python3 -m marker_workflow.cli review-airtable
```

To sync the public-ready Airtable payload into Supabase:

```bash
PYTHONPATH=src python3 -m marker_workflow.cli sync-supabase
```

## Core environment variables

The worker reads configuration from environment variables. The most important ones are:

- `BOX_ROOT_PATH`
- `BOX_PROVIDER`
- `LOCAL_WORKDIR`
- `SQLITE_PATH`
- `OPENAI_API_KEY`
- `OPENAI_MODEL_CLASSIFY`
- `OPENAI_MODEL_MODERATE`
- `OPENAI_MODEL_DRAFT`
- `AIRTABLE_PERSONAL_ACCESS_TOKEN`
- `AIRTABLE_BASE_ID`
- `AIRTABLE_TABLE_NAME`
- `AIRTABLE_VIEW`
- `AIRTABLE_URL`
- `AIRTABLE_SUBMISSIONS_TABLE`
- `AIRTABLE_ASSETS_TABLE`
- `AIRTABLE_DISPLAY_QUEUE_TABLE`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY` or `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_SECRET_KEY`
- `SUPABASE_SCHEMA`
- `SUPABASE_STORIES_TABLE`
- `SUPABASE_STORAGE_BUCKET`
- `SUPABASE_STORAGE_PREFIX`
- `SITE_OUTPUT_PATH`
- `SITE_SOURCE_MODE`
- `POLL_INTERVAL_MINUTES`
- `OCR_ENABLED`
- `TRANSCRIPTION_ENABLED`

An example file is provided in `.env.example`.

## Airtable connection

You can validate an Airtable connection without running the full workflow:

```bash
cd historical_marker_workflow
PYTHONPATH=src python3 -m marker_workflow.cli test-airtable --max-records 3
```

Set these environment variables first:

- `AIRTABLE_PERSONAL_ACCESS_TOKEN` for your Airtable token
- `AIRTABLE_BASE_ID` for the base you want to query, or `AIRTABLE_URL` with a full Airtable base/view link
- `AIRTABLE_TABLE_NAME` for the table name or table ID
- `AIRTABLE_VIEW` optionally, if you want to limit the query to a view

If `AIRTABLE_TABLE_NAME` is not set, the command will still verify the base connection and return the first few tables it can see.

The command returns a small JSON summary showing whether the connection succeeded and which sample records or tables were read.

When `SITE_SOURCE_MODE=airtable`, `build-site` reads public-ready content from the `Submissions` and `Assets` tables only. A story is exported to the website only when:

- `Workflow Status = Approved and Published`

The public website payload intentionally excludes contributor/contact information, internal review data, submission IDs, and `Display Queue` content.

## Supabase runtime mode

The lowest-disruption hosting setup is:

- GitHub Actions runs `sync-supabase` to move public stories and media out of Airtable and into Supabase.
- The static site on Netlify reads from Supabase at runtime.
- `data/stories.json` remains as a fallback snapshot so the site can still render if Supabase is unavailable.

The workflow expects a public table shaped like [`sql/supabase_stories_public.sql`](sql/supabase_stories_public.sql), with `workflow_status` stored as a top-level column and the full public story object stored in `payload`.

## Notes

- The default `filesystem` Box provider is intentionally safe and traceable for development. It mirrors the Box folder model locally and never deletes material outside the configured Box root.
- The OpenAI integration is optional. If no API key is set, the workflow falls back to deterministic heuristics so the pipeline remains runnable and testable.
- Human review remains mandatory. The workflow can recommend next steps, but it never approves content for public display.
- The website builder defaults to `approved` content only. Use `processing-preview` explicitly when you need an internal preview site before editorial approval.
