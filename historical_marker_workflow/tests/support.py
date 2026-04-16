from __future__ import annotations

from pathlib import Path

from marker_workflow.config import AppConfig


def build_config(workspace: Path) -> AppConfig:
    env = {
        "BOX_PROVIDER": "filesystem",
        "BOX_ROOT_PATH": str(workspace / "box_root"),
        "LOCAL_WORKDIR": str(workspace / ".workflow_local"),
        "SQLITE_PATH": str(workspace / ".workflow_local" / "state" / "workflow.sqlite3"),
        "OCR_ENABLED": "false",
        "TRANSCRIPTION_ENABLED": "false",
    }
    config = AppConfig.from_env(env=env, cwd=workspace)
    config.ensure_runtime_directories()
    return config

