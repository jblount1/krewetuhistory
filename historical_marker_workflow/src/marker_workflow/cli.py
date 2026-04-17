from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional, Tuple

from .adapters.ai_client import build_ai_client
from .adapters.airtable_client import AirtableClient
from .adapters.box_client import FilesystemBoxClient
from .adapters.extractor_registry import ExtractorRegistry
from .adapters.supabase_client import SupabaseClient
from .config import AppConfig
from .services.audit import AuditLogger, WorkflowStateStore
from .services.airtable_editorial import AirtableEditorialWorkflow
from .services.airtable_click_sync import AirtableClickSyncService
from .services.duplicate_detector import DuplicateDetector
from .services.extractor import ExtractionService
from .services.generator import OutputGenerator
from .services.grouper import SubmissionGrouper
from .services.poller import WorkflowOrchestrator
from .services.reconcile import ReconcileService
from .services.reviewer import ReviewEngine
from .services.router import Router
from .services.site_builder import SiteBuilder
from .services.stager import Stager
from .services.supabase_sync import SupabaseSyncService


def build_orchestrator(config: AppConfig) -> Tuple[WorkflowOrchestrator, ReconcileService]:
    box_client = FilesystemBoxClient(config)
    state_store = WorkflowStateStore(config.sqlite_path)
    audit_logger = AuditLogger(config, state_store)
    grouper = SubmissionGrouper(config)
    stager = Stager(config, box_client)
    extractor = ExtractionService(config, box_client, ExtractorRegistry(config))
    duplicate_detector = DuplicateDetector(state_store)
    reviewer = ReviewEngine(config, build_ai_client(config))
    generator = OutputGenerator(config, box_client)
    router = Router(config, box_client)
    orchestrator = WorkflowOrchestrator(
        box_client=box_client,
        state_store=state_store,
        audit_logger=audit_logger,
        grouper=grouper,
        stager=stager,
        extractor=extractor,
        duplicate_detector=duplicate_detector,
        reviewer=reviewer,
        generator=generator,
        router=router,
    )
    reconcile = ReconcileService(config, box_client, state_store)
    return orchestrator, reconcile


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Historical marker Box intake workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("poll", help="Poll the intake folder and process new submissions.")

    process = subparsers.add_parser("process-submission", help="Reprocess an existing submission package.")
    process.add_argument("--submission-id", required=True)

    rebuild = subparsers.add_parser("rebuild-artifacts", help="Regenerate artifacts for an existing submission package.")
    rebuild.add_argument("--submission-id", required=True)

    subparsers.add_parser("reconcile", help="Reconcile workflow state against Box status folders.")

    build_site = subparsers.add_parser("build-site", help="Export approved or preview story packages into the website folder.")
    build_site.add_argument(
        "--source-mode",
        choices=["approved", "processing-preview", "approved-or-processing-preview", "airtable"],
        default=None,
    )
    build_site.add_argument("--limit", type=int, default=None)

    test_airtable = subparsers.add_parser("test-airtable", help="Validate Airtable credentials and fetch sample records.")
    test_airtable.add_argument("--max-records", type=int, default=3)

    review_airtable = subparsers.add_parser(
        "review-airtable",
        help="Review Airtable submissions with story dossiers, update workflow status, and generate AI copy.",
    )
    review_airtable.add_argument("--limit", type=int, default=None)

    sync_supabase = subparsers.add_parser(
        "sync-supabase",
        help="Build the public Airtable story payload, upload public media to Supabase Storage, and upsert story rows.",
    )
    sync_supabase.add_argument("--limit", type=int, default=None)

    subparsers.add_parser(
        "sync-clicks-to-airtable",
        help="Copy live click counts from Supabase submissions back into the Airtable Submissions table.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = AppConfig.from_env(cwd=Path.cwd())

    if args.command == "poll":
        orchestrator, _ = build_orchestrator(config)
        result = orchestrator.poll()
    elif args.command == "process-submission":
        orchestrator, _ = build_orchestrator(config)
        result = orchestrator.process_submission(args.submission_id).to_dict()
    elif args.command == "rebuild-artifacts":
        orchestrator, _ = build_orchestrator(config)
        result = orchestrator.rebuild_artifacts(args.submission_id).to_dict()
    elif args.command == "reconcile":
        _, reconcile = build_orchestrator(config)
        result = reconcile.run()
    elif args.command == "build-site":
        site_builder = SiteBuilder(config, FilesystemBoxClient(config))
        result = site_builder.build(source_mode=args.source_mode, limit=args.limit)
    elif args.command == "test-airtable":
        try:
            result = AirtableClient(config).test_connection(max_records=args.max_records)
        except (RuntimeError, ValueError) as error:
            print(json.dumps({"connected": False, "error": str(error)}, indent=2, ensure_ascii=True))
            return 1
    elif args.command == "review-airtable":
        editorial = AirtableEditorialWorkflow(
            config=config,
            box_client=FilesystemBoxClient(config),
            airtable_client=AirtableClient(config),
            ai_client=build_ai_client(config),
            extractor_registry=ExtractorRegistry(config),
        )
        result = editorial.process_pending(limit=args.limit)
    elif args.command == "sync-supabase":
        site_builder = SiteBuilder(config, FilesystemBoxClient(config))
        syncer = SupabaseSyncService(
            config=config,
            site_builder=site_builder,
            supabase_client=SupabaseClient(config),
        )
        result = syncer.sync_public_stories(limit=args.limit)
    elif args.command == "sync-clicks-to-airtable":
        syncer = AirtableClickSyncService(
            config=config,
            airtable_client=AirtableClient(config),
            supabase_client=SupabaseClient(config),
        )
        result = syncer.sync_clicks()
    else:  # pragma: no cover - argparse prevents this branch
        parser.error(f"Unsupported command: {args.command}")
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
