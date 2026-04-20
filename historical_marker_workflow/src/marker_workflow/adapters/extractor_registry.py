from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..config import AppConfig
from ..models import FileExtraction
from ..utils import detect_media_type


class ExtractorRegistry:
    """Dispatches best-effort extraction handlers by file type."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def extract(self, path: Path, item_id: str, relative_path: str) -> FileExtraction:
        media_type = detect_media_type(path.name)
        metadata: Dict[str, Any] = {
            "filename": path.name,
            "suffix": path.suffix.lower(),
            "size_bytes": path.stat().st_size,
        }
        try:
            if media_type in {"document", "spreadsheet", "data"}:
                text, extra_metadata = self._extract_textual(path)
            elif media_type == "pdf":
                text, extra_metadata = self._extract_pdf(path)
            elif media_type == "presentation":
                text, extra_metadata = self._extract_office(path)
            elif media_type == "image":
                text, extra_metadata = self._extract_image(path)
            elif media_type in {"audio", "video"}:
                text, extra_metadata = self._extract_av(path)
            else:
                return FileExtraction(
                    item_id=item_id,
                    original_name=path.name,
                    relative_path=relative_path,
                    media_type="unsupported",
                    metadata=metadata,
                    success=False,
                    error="Unsupported file type.",
                )
            metadata.update(extra_metadata)
            return FileExtraction(
                item_id=item_id,
                original_name=path.name,
                relative_path=relative_path,
                media_type=media_type,
                extracted_text=text,
                metadata=metadata,
                success=True,
            )
        except Exception as exc:  # pragma: no cover - defensive branch
            return FileExtraction(
                item_id=item_id,
                original_name=path.name,
                relative_path=relative_path,
                media_type=media_type,
                metadata=metadata,
                success=False,
                error=str(exc),
            )

    def _extract_textual(self, path: Path) -> Tuple[str, Dict[str, Any]]:
        suffix = path.suffix.lower()
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            return json.dumps(payload, indent=2, ensure_ascii=True), {"parser": "json"}
        if suffix in {".doc", ".docx", ".rtf", ".odt"}:
            return self._extract_office(path)
        return path.read_text(encoding="utf-8", errors="ignore"), {"parser": "text"}

    def _extract_pdf(self, path: Path) -> Tuple[str, Dict[str, Any]]:
        pdftotext = shutil.which("pdftotext")
        if pdftotext:
            result = subprocess.run(
                [pdftotext, str(path), "-"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout, {"parser": "pdftotext"}
        return "", {"parser": "metadata_only", "warning": "PDF text extraction unavailable"}

    def _extract_office(self, path: Path) -> Tuple[str, Dict[str, Any]]:
        textutil = shutil.which("textutil")
        if textutil:
            result = subprocess.run(
                [textutil, "-convert", "txt", "-stdout", str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout, {"parser": "textutil"}
        return "", {"parser": "metadata_only", "warning": "Office extraction unavailable"}

    def _extract_image(self, path: Path) -> Tuple[str, Dict[str, Any]]:
        if self.config.ocr_enabled and shutil.which("tesseract"):
            result = subprocess.run(
                ["tesseract", str(path), "stdout"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout, {"parser": "ocr"}
        return "", {"parser": "metadata_only", "warning": "OCR disabled or unavailable"}

    def _extract_av(self, path: Path) -> Tuple[str, Dict[str, Any]]:
        transcript_path = self._find_sidecar_transcript(path)
        if transcript_path and transcript_path.exists():
            return transcript_path.read_text(encoding="utf-8", errors="ignore"), {"parser": "sidecar_transcript"}
        return "", {"parser": "metadata_only", "warning": "Transcript unavailable"}

    def _find_sidecar_transcript(self, path: Path) -> Optional[Path]:
        if not self.config.transcription_enabled:
            return None
        for suffix in (".txt", ".vtt", ".srt"):
            candidate = path.with_suffix(suffix)
            if candidate.exists():
                return candidate
        return None

