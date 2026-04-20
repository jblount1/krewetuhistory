from __future__ import annotations

from pathlib import Path
from typing import List

from ..adapters.box_client import FilesystemBoxClient
from ..adapters.extractor_registry import ExtractorRegistry
from ..config import AppConfig
from ..models import ExtractedSubmission, FileExtraction, SubmissionRecord
from ..utils import dump_json, ensure_directory, relative_to, slugify, write_text


class ExtractionService:
    def __init__(self, config: AppConfig, box_client: FilesystemBoxClient, registry: ExtractorRegistry) -> None:
        self.config = config
        self.box_client = box_client
        self.registry = registry

    def run(self, submission: SubmissionRecord) -> ExtractedSubmission:
        package_root = self.box_client.absolute_path(submission.canonical_package_path or "")
        originals_dir = package_root / "originals"
        derivatives_dir = ensure_directory(package_root / "derivatives")
        manifests_dir = ensure_directory(package_root / "manifests")

        extracted_files: List[FileExtraction] = []
        combined_parts: List[str] = []
        errors: List[str] = []
        media_types: List[str] = []
        for path in sorted(originals_dir.rglob("*")):
            if not path.is_file():
                continue
            relative_path = relative_to(path, package_root)
            extraction = self.registry.extract(path, item_id=relative_path, relative_path=relative_path)
            extracted_files.append(extraction)
            media_types.append(extraction.media_type)
            if extraction.extracted_text:
                combined_parts.append(f"FILE: {path.name}\n{extraction.extracted_text}")
                derivative_name = f"{slugify(path.name, fallback='artifact')}.txt"
                write_text(derivatives_dir / derivative_name, extraction.extracted_text)
            if extraction.error:
                errors.append(f"{path.name}: {extraction.error}")
            dump_json(
                manifests_dir / f"{slugify(path.name, fallback='artifact')}__metadata.json",
                {
                    "relative_path": relative_path,
                    "media_type": extraction.media_type,
                    "metadata": extraction.metadata,
                    "success": extraction.success,
                    "error": extraction.error,
                },
            )
        combined_text = "\n\n".join(combined_parts)
        detected_language = self._detect_language(combined_text)
        submission.media_types = sorted({media_type for media_type in media_types if media_type})
        submission.detected_language = detected_language
        submission.processing_errors = list(dict.fromkeys(submission.processing_errors + errors))
        submission.pipeline_status = "extracted"
        return ExtractedSubmission(
            submission_id=submission.submission_id,
            files=extracted_files,
            combined_text=combined_text,
            media_types=submission.media_types,
            detected_language=detected_language,
            errors=errors,
        )

    def _detect_language(self, text: str) -> str:
        if not text.strip():
            return "unknown"
        ascii_chars = sum(1 for char in text if ord(char) < 128)
        ratio = ascii_chars / max(len(text), 1)
        return "en" if ratio > 0.90 else "unknown"
