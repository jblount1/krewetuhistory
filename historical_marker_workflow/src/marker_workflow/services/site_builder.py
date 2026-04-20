from __future__ import annotations

import re
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from ..adapters.airtable_client import AirtableClient
from ..adapters.box_client import FilesystemBoxClient
from ..config import AppConfig
from ..utils import detect_media_type, dump_json, ensure_directory, isoformat_z, load_json, relative_to, slugify


class SiteBuilder:
    def __init__(
        self,
        config: AppConfig,
        box_client: FilesystemBoxClient,
        airtable_client: Optional[AirtableClient] = None,
        downloader: Optional[Callable[[str], bytes]] = None,
        pdf_preview_generator: Optional[Callable[[Path, Path], Optional[Path]]] = None,
    ) -> None:
        self.config = config
        self.box_client = box_client
        self.airtable_client = airtable_client or AirtableClient(config)
        self.downloader = downloader or self._download_bytes
        self.pdf_preview_generator = pdf_preview_generator or self._generate_pdf_preview

    def build(self, source_mode: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, object]:
        mode = (source_mode or self.config.site_source_mode).strip().lower()
        site_root = ensure_directory(self.config.site_output_path)
        data_dir = ensure_directory(site_root / "data")
        media_dir = ensure_directory(site_root / "media")
        if mode == "airtable":
            try:
                stories, copied_assets, resolved_mode = self._build_airtable_stories(media_dir, limit=limit)
            except (RuntimeError, ValueError):
                fallback_payload = self._existing_site_payload(data_dir / "stories.json")
                if fallback_payload:
                    return {
                        "site_output_path": str(site_root),
                        "data_path": str(data_dir / "stories.json"),
                        "source_mode": fallback_payload.get("source_mode") or "airtable",
                        "story_count": int(fallback_payload.get("story_count") or len(fallback_payload.get("stories") or [])),
                        "copied_assets": 0,
                        "used_existing_snapshot": True,
                    }
                raise
        else:
            story_package_paths, resolved_mode = self._story_package_paths(mode)
            if limit is not None:
                story_package_paths = story_package_paths[:limit]
            stories = []
            copied_assets = 0
            for story_package_path in story_package_paths:
                story, asset_count = self._build_story_entry(story_package_path, media_dir, resolved_mode)
                if story:
                    copied_assets += asset_count
                    stories.append(story)
            stories.sort(key=lambda story: (story.get("date_received") or "", story.get("headline") or ""), reverse=True)
        payload = {
            "generated_at": isoformat_z(),
            "source_mode": resolved_mode,
            "source_label": self._source_label(resolved_mode),
            "public_publish_ready": resolved_mode == "approved",
            "story_count": len(stories),
            "stories": stories,
        }
        dump_json(data_dir / "stories.json", payload)
        return {
            "site_output_path": str(site_root),
            "data_path": str(data_dir / "stories.json"),
            "source_mode": resolved_mode,
            "story_count": len(stories),
            "copied_assets": copied_assets,
        }

    def _existing_site_payload(self, path: Path) -> Optional[Dict[str, object]]:
        if not path.exists() or not path.is_file():
            return None
        payload = load_json(path)
        if not isinstance(payload, dict):
            return None
        if not isinstance(payload.get("stories"), list):
            return None
        return payload

    def _build_airtable_stories(self, media_root: Path, limit: Optional[int] = None) -> Tuple[List[Dict[str, object]], int, str]:
        submissions = self.airtable_client.list_all_records(self.config.airtable_submissions_table)
        assets = self.airtable_client.list_all_records(self.config.airtable_assets_table)

        assets_by_submission: Dict[str, List[dict]] = {}
        for asset in assets:
            linked_ids = asset.get("fields", {}).get("Linked Submission") or []
            for submission_record_id in linked_ids:
                assets_by_submission.setdefault(submission_record_id, []).append(asset)

        stories: List[Dict[str, object]] = []
        copied_assets = 0
        for submission in submissions:
            story, story_copied_assets = self._build_airtable_story_entry(
                submission=submission,
                linked_assets=assets_by_submission.get(submission.get("id", ""), []),
                media_root=media_root,
            )
            if story:
                stories.append(story)
                copied_assets += story_copied_assets

        stories.sort(
            key=lambda story: (
                -(self._date_sort_value(story.get("date_received"))),
                str(story.get("headline") or "").lower(),
            )
        )
        if limit is not None:
            stories = stories[:limit]
        return stories, copied_assets, "airtable"

    def _story_package_paths(self, mode: str) -> Tuple[List[Path], str]:
        if mode == "processing-preview":
            paths = sorted((self.config.box_root_path / "processing").rglob("*__story-package.json"))
            return paths, mode
        if mode == "approved-or-processing-preview":
            approved = sorted((self.config.box_root_path / "approved").rglob("*__story-package.json"))
            if approved:
                return approved, "approved"
            preview = sorted((self.config.box_root_path / "processing").rglob("*__story-package.json"))
            return preview, "processing-preview"
        approved = sorted((self.config.box_root_path / "approved").rglob("*__story-package.json"))
        return approved, "approved"

    def _build_story_entry(self, story_package_path: Path, media_root: Path, source_mode: str) -> Tuple[Optional[Dict[str, object]], int]:
        story_payload = load_json(story_package_path)
        submission_id = story_payload.get("submission_id") or story_package_path.name.split("__", 1)[0]
        submission_record_path = self._locate_submission_record(story_package_path, submission_id)
        if not submission_record_path:
            return None, 0
        submission_payload = load_json(submission_record_path)
        canonical_package_path = submission_payload.get("canonical_package_path")
        originals_dir = self.config.box_root_path / canonical_package_path / "originals" if canonical_package_path else None
        media_assets, copied_count = self._copy_media_assets(
            submission_id=submission_id,
            asset_names=story_payload.get("associated_media_assets") or [],
            captions=story_payload.get("suggested_image_caption_placeholders") or [],
            originals_dir=originals_dir,
            media_root=media_root,
        )
        story = {
            "submission_id": submission_id,
            "story_slug": submission_payload.get("story_slug") or slugify(story_payload.get("headline", submission_id)),
            "headline": story_payload.get("headline"),
            "summary": story_payload.get("summary_50"),
            "narrative": story_payload.get("narrative_120_180"),
            "themes": story_payload.get("themes") or [],
            "community_labels": story_payload.get("community_labels") or [],
            "credits_line": story_payload.get("suggested_credits_line"),
            "questions_or_gaps": story_payload.get("questions_or_gaps") or [],
            "display_format_recommendation": story_payload.get("display_format_recommendation"),
            "media_assets": media_assets,
            "date_received": submission_payload.get("date_received"),
            "community_label": submission_payload.get("community_label"),
            "geographic_label": submission_payload.get("geographic_label"),
            "tulane_connection": submission_payload.get("tulane_connection"),
            "source_status": source_mode,
            "review_status": submission_payload.get("review_status"),
            "public_display_risk_level": submission_payload.get("public_display_risk_level"),
            "notes_for_human_reviewer": submission_payload.get("notes_for_human_reviewer") or [],
        }
        return story, copied_count

    def _locate_submission_record(self, story_package_path: Path, submission_id: str) -> Optional[Path]:
        direct_candidate = story_package_path.parent.parent / "records" / f"{submission_id}__submission.json"
        if direct_candidate.exists():
            return direct_candidate
        for candidate in story_package_path.parents[2].rglob(f"{submission_id}__submission.json"):
            if candidate.exists():
                return candidate
        return None

    def _copy_media_assets(
        self,
        submission_id: str,
        asset_names: List[str],
        captions: List[str],
        originals_dir: Optional[Path],
        media_root: Path,
    ) -> Tuple[List[Dict[str, object]], int]:
        copied = 0
        story_media_dir = ensure_directory(media_root / submission_id)
        assets: List[Dict[str, object]] = []
        for index, asset_name in enumerate(asset_names):
            caption = captions[index] if index < len(captions) else f"Caption placeholder for {asset_name}"
            if not originals_dir or not originals_dir.exists():
                assets.append(
                    {
                        "filename": asset_name,
                        "kind": detect_media_type(asset_name),
                        "url": None,
                        "caption": caption,
                        "missing": True,
                    }
                )
                continue
            source_path = self._locate_asset(originals_dir, asset_name)
            if not source_path:
                assets.append(
                    {
                        "filename": asset_name,
                        "kind": detect_media_type(asset_name),
                        "url": None,
                        "caption": caption,
                        "missing": True,
                    }
                )
                continue
            destination = story_media_dir / source_path.name
            shutil.copy2(source_path, destination)
            copied += 1
            assets.append(
                {
                    "filename": source_path.name,
                    "kind": detect_media_type(source_path.name),
                    "url": relative_to(destination, self.config.site_output_path),
                    "caption": caption,
                    "missing": False,
                    "source_path": relative_to(source_path, self.config.box_root_path),
                }
            )
        return assets, copied

    def _locate_asset(self, originals_dir: Path, asset_name: str) -> Optional[Path]:
        direct = originals_dir / asset_name
        if direct.exists():
            return direct
        matches = list(originals_dir.rglob(asset_name))
        if matches:
            return matches[0]
        basename_matches = [path for path in originals_dir.rglob("*") if path.is_file() and path.name == Path(asset_name).name]
        if basename_matches:
            return basename_matches[0]
        return None

    def _build_airtable_story_entry(
        self,
        *,
        submission: dict,
        linked_assets: List[dict],
        media_root: Path,
    ) -> Tuple[Optional[Dict[str, object]], int]:
        submission_fields = submission.get("fields", {})
        workflow_status = str(submission_fields.get("Workflow Status") or "").strip()
        if not self._is_public_workflow_status(workflow_status):
            return None, 0
        headline = submission_fields.get("Story Title")
        if not headline:
            return None, 0
        ai_copy = self._public_ai_copy(submission_fields)
        airtable_record_id = submission.get("id")
        submission_id = submission_fields.get("Submission ID") or airtable_record_id or slugify(headline or "story")

        media_assets, copied_assets = self._build_airtable_media_assets(
            submission_id=submission_id,
            submission_fields=submission_fields,
            linked_assets=linked_assets,
            media_root=media_root,
        )
        date_received = submission_fields.get("Created Date")
        if not date_received:
            date_received = submission.get("createdTime")

        response_qr = self._build_response_qr_asset(
            submission_id=submission_id,
            value=submission_fields.get("Response QR"),
            media_root=media_root,
        )

        story = {
            "story_slug": slugify(headline or submission_id),
            "headline": headline,
            "summary": submission_fields.get("Summary") or "",
            "narrative": submission_fields.get("Narrative") or "",
            "ai_generated": self._text_value(submission_fields.get("AI Generated")),
            "themes": self._string_list(submission_fields.get("Theme")),
            "keywords": self._string_list(submission_fields.get("Keywords")),
            "context_connections": self._context_connections(submission_fields),
            "context_sections": self._context_sections(submission_fields),
            "references": self._normalize_references(submission_fields.get("References")),
            "ai_copy": ai_copy,
            "response_qr": response_qr,
            "response_link": self._text_value(submission_fields.get("Response Link")),
            "avg_rating": self._numeric_value(submission_fields.get("Avg Rating")),
            "number_of_responses": self._integer_value(submission_fields.get("Number of Responses")),
            "clicks": self._integer_value(submission_fields.get("Clicks"), default=0),
            "media_assets": media_assets,
            "date_received": date_received,
            "source_status": "airtable",
            "workflow_status": workflow_status,
        }
        return story, copied_assets

    def _fallback_carousel_copy(self, submission_fields: dict) -> str:
        for field_name in ("Summary", "Narrative", "Context and Connections"):
            value = self._text_value(submission_fields.get(field_name))
            if value:
                return value
        return "Story copy will appear here after editorial review."

    def _public_ai_copy(self, submission_fields: dict) -> str:
        candidate = self._text_value(submission_fields.get("AI Copy"))
        normalized = candidate.strip().lower()
        if not normalized:
            return self._fallback_carousel_copy(submission_fields)
        if normalized.startswith("error") or "attachmentfailedtoextract" in normalized:
            return self._fallback_carousel_copy(submission_fields)
        return candidate

    def _text_value(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            parts = [self._text_value(item) for item in value]
            return "\n".join(part for part in parts if part).strip()
        if isinstance(value, dict):
            preferred_keys = ("value", "text", "name", "label", "title")
            for key in preferred_keys:
                nested = self._text_value(value.get(key))
                if nested:
                    return nested
            parts = [self._text_value(item) for item in value.values()]
            return "\n".join(part for part in parts if part).strip()
        return str(value).strip()

    def _integer_value(self, value: object, default: Optional[int] = None) -> Optional[int]:
        if value in (None, ""):
            return default
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return default

    def _numeric_value(self, value: object) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _first_attachment_url(self, value: object) -> Optional[str]:
        if not isinstance(value, list) or not value:
            return None
        first = value[0]
        if isinstance(first, dict):
            url = first.get("url")
            return str(url).strip() if url else None
        return None

    def _build_response_qr_asset(
        self,
        *,
        submission_id: str,
        value: object,
        media_root: Path,
    ) -> Optional[str]:
        if not isinstance(value, list) or not value:
            return None
        first = value[0]
        if not isinstance(first, dict):
            return None
        attachment_url = str(first.get("url") or "").strip()
        if not attachment_url:
            return None
        filename = first.get("filename") or "response-qr"
        local_url, _was_downloaded = self._safe_media_url(
            submission_id=submission_id,
            filename=filename,
            remote_url=attachment_url,
            media_root=media_root,
        )
        return local_url

    def _build_airtable_media_assets(
        self,
        *,
        submission_id: str,
        submission_fields: dict,
        linked_assets: List[dict],
        media_root: Path,
    ) -> Tuple[List[Dict[str, object]], int]:
        assets: List[Dict[str, object]] = []
        copied_assets = 0
        seen_keys: set[str] = set()

        for asset in sorted(linked_assets, key=lambda record: record.get("fields", {}).get("Sort Order") or 10**6):
            asset_fields = asset.get("fields", {})
            attachment_items = asset_fields.get("Attachment") or []
            if attachment_items:
                for attachment in attachment_items:
                    attachment_url = attachment.get("url")
                    filename = attachment.get("filename") or asset_fields.get("Filename") or "attachment"
                    if not attachment_url or attachment_url in seen_keys:
                        continue
                    kind = detect_media_type(filename)
                    if kind not in {"image", "pdf"}:
                        continue
                    local_url, was_downloaded = self._safe_media_url(
                        submission_id=submission_id,
                        filename=filename,
                        remote_url=attachment_url,
                        media_root=media_root,
                    )
                    preview_url = None
                    if kind == "pdf" and was_downloaded:
                        preview_url = self._safe_pdf_preview_url(
                            submission_id=submission_id,
                            filename=filename,
                            media_root=media_root,
                        )
                    copied_assets += 1 if was_downloaded else 0
                    assets.append(
                        {
                            "filename": filename,
                            "kind": kind,
                            "url": local_url if kind == "image" else preview_url or local_url,
                            "document_url": local_url if kind == "pdf" else None,
                            "preview_url": preview_url,
                            "caption": asset_fields.get("Caption") or filename,
                            "mla_citation": asset_fields.get("MLA Citation") or "",
                            "missing": False,
                            "source_path": attachment_url,
                        }
                    )
                    seen_keys.add(attachment_url)

        video_url = str(submission_fields.get("Video URL") or "").strip()
        if video_url and video_url not in seen_keys:
            video_asset = self._build_video_asset(video_url, submission_fields)
            if video_asset:
                assets.append(video_asset)
                seen_keys.add(video_url)

        return assets, copied_assets

    def _download_remote_media(self, *, submission_id: str, filename: str, remote_url: str, media_root: Path) -> str:
        destination = ensure_directory(media_root / submission_id) / Path(filename).name
        if not destination.exists():
            destination.write_bytes(self.downloader(remote_url))
        return relative_to(destination, self.config.site_output_path)

    def _safe_media_url(self, *, submission_id: str, filename: str, remote_url: str, media_root: Path) -> Tuple[str, bool]:
        try:
            return (
                self._download_remote_media(
                    submission_id=submission_id,
                    filename=filename,
                    remote_url=remote_url,
                    media_root=media_root,
                ),
                True,
            )
        except RuntimeError:
            return remote_url, False

    def _safe_pdf_preview_url(self, *, submission_id: str, filename: str, media_root: Path) -> Optional[str]:
        source_path = ensure_directory(media_root / submission_id) / Path(filename).name
        if not source_path.exists():
            return None
        preview_path = ensure_directory(media_root / submission_id) / f"{Path(filename).stem}__preview.png"
        try:
            generated = self.pdf_preview_generator(source_path, preview_path)
        except RuntimeError:
            return None
        if not generated or not generated.exists():
            return None
        return relative_to(generated, self.config.site_output_path)

    def _download_bytes(self, remote_url: str) -> bytes:
        request = Request(remote_url, headers={"User-Agent": "historical-marker-workflow/0.1"})
        try:
            with urlopen(request, timeout=self.config.airtable_timeout_seconds) as response:
                return response.read()
        except HTTPError as error:
            raise RuntimeError(f"Unable to download remote asset ({error.code}).") from error
        except URLError as error:
            raise RuntimeError(f"Unable to download remote asset: {error.reason}") from error

    def _generate_pdf_preview(self, source_path: Path, preview_path: Path) -> Optional[Path]:
        ensure_directory(preview_path.parent)

        try:
            import pypdfium2 as pdfium
        except ImportError:
            pdfium = None

        if pdfium is not None:
            try:
                pdf = pdfium.PdfDocument(str(source_path))
                page = pdf[0]
                bitmap = page.render(scale=1.5)
                pil_image = bitmap.to_pil()
                pil_image.save(preview_path)
                page.close()
                pdf.close()
                if preview_path.exists():
                    return preview_path
            except Exception:
                if preview_path.exists():
                    preview_path.unlink(missing_ok=True)

        sips = shutil.which("sips")
        if not sips:
            return None
        result = subprocess.run(
            [sips, "-s", "format", "png", str(source_path), "--out", str(preview_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not preview_path.exists():
            return None
        return preview_path

    def _build_video_asset(self, video_url: str, submission_fields: dict) -> Optional[Dict[str, object]]:
        parsed = urlparse(video_url)
        host = (parsed.netloc or "").lower()
        path = parsed.path or ""
        caption = submission_fields.get("Story Title") or "Story video"

        youtube_embed = self._youtube_embed_url(video_url)
        if youtube_embed:
            return {
                "filename": "video-url",
                "kind": "video_embed",
                "url": youtube_embed,
                "source_url": video_url,
                "caption": caption,
                "mla_citation": "",
                "missing": False,
                "external": True,
            }

        vimeo_embed = self._vimeo_embed_url(video_url)
        if vimeo_embed:
            return {
                "filename": "video-url",
                "kind": "video_embed",
                "url": vimeo_embed,
                "source_url": video_url,
                "caption": caption,
                "mla_citation": "",
                "missing": False,
                "external": True,
            }

        if detect_media_type(path) == "video":
            filename = Path(path).name or "story-video"
            return {
                "filename": filename,
                "kind": "video",
                "url": video_url,
                "caption": caption,
                "mla_citation": "",
                "missing": False,
                "external": True,
            }

        if host:
            return {
                "filename": host,
                "kind": "external",
                "url": video_url,
                "caption": caption,
                "mla_citation": "",
                "missing": False,
                "external": True,
            }
        return None

    def _youtube_embed_url(self, value: str) -> Optional[str]:
        parsed = urlparse(value)
        host = (parsed.netloc or "").lower()
        if "youtu.be" in host:
            video_id = parsed.path.strip("/")
        elif "youtube.com" in host:
            if parsed.path == "/watch":
                video_id = parse_qs(parsed.query).get("v", [""])[0]
            elif parsed.path.startswith("/embed/"):
                video_id = parsed.path.split("/embed/", 1)[1].split("/", 1)[0]
            else:
                video_id = ""
        else:
            return None
        return f"https://www.youtube.com/embed/{video_id}" if video_id else None

    def _vimeo_embed_url(self, value: str) -> Optional[str]:
        parsed = urlparse(value)
        host = (parsed.netloc or "").lower()
        if "vimeo.com" not in host:
            return None
        candidate = parsed.path.strip("/").split("/", 1)[0]
        return f"https://player.vimeo.com/video/{candidate}" if candidate.isdigit() else None

    def _source_label(self, mode: str) -> str:
        labels = {
            "approved": "Approved archive",
            "processing-preview": "Workflow preview",
            "airtable": "Approved stories",
        }
        return labels.get(mode, "Story source")

    def _is_public_workflow_status(self, value: object) -> bool:
        normalized = str(value or "").strip().lower()
        return normalized in {"approved", "approved and published"}

    def _date_sort_value(self, value: Optional[str]) -> int:
        if not value:
            return 0
        normalized = value.replace("Z", "+00:00")
        try:
            return int(datetime.fromisoformat(normalized).timestamp())
        except ValueError:
            return 0

    def _first_non_empty(self, values: List[Optional[str]]) -> Optional[str]:
        for value in values:
            if value:
                return value
        return None

    def _string_list(self, value: object) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _normalize_references(self, value: object) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if not isinstance(value, str):
            return []
        if not value.strip():
            return []
        return [part.strip() for part in re.split(r"\n{2,}|\n|;\s*", value) if part.strip()]

    def _context_connections(self, submission_fields: dict) -> str:
        explicit = (submission_fields.get("Context and Connections") or "").strip()
        if explicit:
            return explicit
        parts = []
        if submission_fields.get("New Orleans Connection"):
            parts.append(f"New Orleans: {submission_fields.get('New Orleans Connection')}")
        if submission_fields.get("Tulane Connection"):
            parts.append(f"Tulane: {submission_fields.get('Tulane Connection')}")
        if submission_fields.get("Global Community Connection"):
            parts.append(f"Global: {submission_fields.get('Global Community Connection')}")
        return " ".join(parts)

    def _context_sections(self, submission_fields: dict) -> List[Dict[str, str]]:
        sections: List[Dict[str, str]] = []

        explicit = self._text_value(submission_fields.get("Context and Connections"))
        if explicit:
            sections.append({"label": "Context and Connections", "text": explicit})

        mapping = [
            ("New Orleans Connection", "New Orleans Connection"),
            ("Tulane Connection", "Tulane Connection"),
            ("Global Community Connection", "Global Community Connection"),
        ]

        for field_name, label in mapping:
            value = self._text_value(submission_fields.get(field_name))
            if value:
                sections.append({"label": label, "text": value})

        return sections
