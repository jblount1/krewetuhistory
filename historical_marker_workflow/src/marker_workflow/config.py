from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .utils import coerce_bool, ensure_directory

TOP_LEVEL_FOLDERS = [
    "intake",
    "processing",
    "review",
    "approved",
    "rejected",
    "needs-more-info",
    "presentations",
    "working-docs",
    "logs",
    "templates",
    "archive",
]


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    workspace_root: Path
    box_root_path: Path
    box_provider: str
    box_intake_folder: str
    local_workdir: Path
    sqlite_path: Path
    site_output_path: Path
    site_source_mode: str
    poll_interval_minutes: int
    max_file_size_mb: int
    ocr_enabled: bool
    transcription_enabled: bool
    openai_api_key: Optional[str]
    openai_base_url: str
    openai_model_classify: str
    openai_model_moderate: str
    openai_model_draft: str
    airtable_api_key: Optional[str]
    airtable_base_id: Optional[str]
    airtable_table_name: Optional[str]
    airtable_view: Optional[str]
    airtable_url: Optional[str]
    airtable_share_id: Optional[str]
    airtable_submissions_table: str
    airtable_assets_table: str
    airtable_display_queue_table: str
    airtable_base_url: str
    airtable_timeout_seconds: int
    supabase_url: Optional[str]
    supabase_anon_key: Optional[str]
    supabase_service_role_key: Optional[str]
    supabase_schema: str
    supabase_stories_table: str
    supabase_storage_bucket: str
    supabase_storage_prefix: str

    @classmethod
    def from_env(cls, env: Optional[dict[str, str]] = None, cwd: Optional[Path] = None) -> "AppConfig":
        raw_env = dict(env or os.environ)
        project_root = Path(cwd or raw_env.get("PROJECT_ROOT", Path.cwd())).expanduser().resolve()
        workspace_root = project_root.parent if project_root.name == "historical_marker_workflow" else project_root
        env_map = {
            **_load_env_file(workspace_root / ".env"),
            **_load_env_file(project_root / ".env"),
            **raw_env,
        }
        box_root_path = Path(env_map.get("BOX_ROOT_PATH", workspace_root / "box_project_root")).expanduser().resolve()
        local_workdir = Path(env_map.get("LOCAL_WORKDIR", project_root / ".workflow_local")).expanduser().resolve()
        sqlite_path = Path(env_map.get("SQLITE_PATH", local_workdir / "state" / "workflow.sqlite3")).expanduser().resolve()
        site_output_path = Path(env_map.get("SITE_OUTPUT_PATH", workspace_root / "historical_marker_site")).expanduser().resolve()
        airtable_api_key = env_map.get("AIRTABLE_PERSONAL_ACCESS_TOKEN") or env_map.get("AIRTABLE_API_KEY") or None
        airtable_url = (env_map.get("AIRTABLE_URL") or env_map.get("AIRTABLE_SHARED_VIEW_URL") or "").strip() or None
        parsed_base_id, parsed_share_id = _parse_airtable_url(airtable_url)
        return cls(
            project_root=project_root,
            workspace_root=workspace_root,
            box_root_path=box_root_path,
            box_provider=env_map.get("BOX_PROVIDER", "filesystem").strip().lower(),
            box_intake_folder=env_map.get("BOX_INTAKE_FOLDER", "intake").strip("/"),
            local_workdir=local_workdir,
            sqlite_path=sqlite_path,
            site_output_path=site_output_path,
            site_source_mode=env_map.get("SITE_SOURCE_MODE", "approved").strip().lower(),
            poll_interval_minutes=int(env_map.get("POLL_INTERVAL_MINUTES", "15")),
            max_file_size_mb=int(env_map.get("MAX_FILE_SIZE_MB", "100")),
            ocr_enabled=coerce_bool(env_map.get("OCR_ENABLED"), default=False),
            transcription_enabled=coerce_bool(env_map.get("TRANSCRIPTION_ENABLED"), default=False),
            openai_api_key=env_map.get("OPENAI_API_KEY") or None,
            openai_base_url=env_map.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            openai_model_classify=env_map.get("OPENAI_MODEL_CLASSIFY", "gpt-4.1-mini"),
            openai_model_moderate=env_map.get("OPENAI_MODEL_MODERATE", "gpt-4.1-mini"),
            openai_model_draft=env_map.get("OPENAI_MODEL_DRAFT", "gpt-4.1-mini"),
            airtable_api_key=airtable_api_key,
            airtable_base_id=(env_map.get("AIRTABLE_BASE_ID") or "").strip() or parsed_base_id,
            airtable_table_name=(env_map.get("AIRTABLE_TABLE_NAME") or env_map.get("AIRTABLE_TABLE_ID") or "").strip() or None,
            airtable_view=(env_map.get("AIRTABLE_VIEW") or "").strip() or None,
            airtable_url=airtable_url,
            airtable_share_id=parsed_share_id,
            airtable_submissions_table=env_map.get("AIRTABLE_SUBMISSIONS_TABLE", "Submissions").strip() or "Submissions",
            airtable_assets_table=env_map.get("AIRTABLE_ASSETS_TABLE", "Assets").strip() or "Assets",
            airtable_display_queue_table=env_map.get("AIRTABLE_DISPLAY_QUEUE_TABLE", "Display Queue").strip() or "Display Queue",
            airtable_base_url=env_map.get("AIRTABLE_BASE_URL", "https://api.airtable.com/v0").rstrip("/"),
            airtable_timeout_seconds=int(env_map.get("AIRTABLE_TIMEOUT_SECONDS", "20")),
            supabase_url=(env_map.get("SUPABASE_URL") or "").strip().rstrip("/") or None,
            supabase_anon_key=(
                env_map.get("SUPABASE_ANON_KEY")
                or env_map.get("SUPABASE_PUBLISHABLE_KEY")
                or ""
            ).strip()
            or None,
            supabase_service_role_key=(
                env_map.get("SUPABASE_SERVICE_ROLE_KEY")
                or env_map.get("SUPABASE_SECRET_KEY")
                or ""
            ).strip()
            or None,
            supabase_schema=env_map.get("SUPABASE_SCHEMA", "public").strip() or "public",
            supabase_stories_table=env_map.get("SUPABASE_STORIES_TABLE", "stories_public").strip() or "stories_public",
            supabase_storage_bucket=env_map.get("SUPABASE_STORAGE_BUCKET", "stories-public").strip() or "stories-public",
            supabase_storage_prefix=env_map.get("SUPABASE_STORAGE_PREFIX", "stories").strip().strip("/"),
        )

    def ensure_runtime_directories(self) -> None:
        ensure_directory(self.box_root_path)
        ensure_directory(self.local_workdir)
        ensure_directory(self.sqlite_path.parent)
        ensure_directory(self.site_output_path)
        for folder_name in TOP_LEVEL_FOLDERS:
            ensure_directory(self.box_root_path / folder_name)
        ensure_directory(self.local_workdir / "locks")
        ensure_directory(self.local_workdir / "tmp")

    def processing_package_path(self, submission_id: str, year: str, month: str) -> Path:
        return self.box_root_path / "processing" / year / month / submission_id

    def review_packet_path(self, queue_name: str, submission_id: str, year: str, month: str) -> Path:
        return self.box_root_path / "review" / queue_name / year / month / submission_id

    def archive_package_path(self, submission_id: str, year: str, month: str) -> Path:
        return self.box_root_path / "archive" / year / month / submission_id

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


def _parse_airtable_url(value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not value:
        return None, None
    match = re.search(r"/(app[a-zA-Z0-9]+)/(?:(?:tbl[a-zA-Z0-9]+|viw[a-zA-Z0-9]+|shr[a-zA-Z0-9]+))", value)
    if match:
        base_match = re.search(r"/(app[a-zA-Z0-9]+)/", value)
        share_match = re.search(r"/(shr[a-zA-Z0-9]+)", value)
        return (
            base_match.group(1) if base_match else None,
            share_match.group(1) if share_match else None,
        )
    base_match = re.search(r"/(app[a-zA-Z0-9]+)", value)
    share_match = re.search(r"/(shr[a-zA-Z0-9]+)", value)
    return (
        base_match.group(1) if base_match else None,
        share_match.group(1) if share_match else None,
    )


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values
