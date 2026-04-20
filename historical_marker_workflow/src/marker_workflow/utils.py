from __future__ import annotations

import hashlib
import json
import re
import shutil
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

MEDIA_TYPE_MAP = {
    "document": {".txt", ".md", ".rtf", ".doc", ".docx", ".odt"},
    "pdf": {".pdf"},
    "presentation": {".ppt", ".pptx", ".key"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".heic", ".webp", ".avif"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".flac"},
    "video": {".mp4", ".mov", ".m4v", ".avi", ".mkv"},
    "spreadsheet": {".csv", ".tsv", ".xls", ".xlsx"},
    "data": {".json", ".xml"},
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_z(value: Optional[datetime] = None) -> str:
    current = value or utc_now()
    return current.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def generate_prefixed_id(prefix: str, when: Optional[datetime] = None, suffix: Optional[str] = None) -> str:
    current = when or utc_now()
    base = current.strftime("%Y%m%dT%H%M%SZ")
    if prefix.upper() == "SUB":
        base = current.strftime("%Y%m%d")
    token = suffix or "".join(current.strftime("%f"))[-6:]
    return f"{prefix.upper()}-{base}-{token.upper()}" if prefix.upper() == "SUB" else f"{prefix.upper()}-{base}"


def slugify(value: str, *, fallback: str = "untitled") -> str:
    cleaned = value.strip().lower()
    cleaned = cleaned.replace("&", " and ")
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    cleaned = cleaned.strip("-")
    return cleaned or fallback


def normalize_basename(filename: str) -> str:
    base = Path(filename).stem.lower()
    base = re.sub(r"[_\-\s]+", " ", base)
    base = re.sub(r"\b(copy|final|draft|scan|img|image)\b", " ", base)
    base = re.sub(r"\d+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base or Path(filename).stem.lower()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def dump_json(path: Path, data: Any) -> None:
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=True, sort_keys=False)
        handle.write("\n")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_text(path: Path, text: str) -> None:
    ensure_directory(path.parent)
    path.write_text(text, encoding="utf-8")


def copy_and_verify(source: Path, destination: Path) -> str:
    ensure_directory(destination.parent)
    shutil.copy2(source, destination)
    digest = sha256_file(destination)
    if digest != sha256_file(source):
        raise ValueError(f"Hash verification failed after copying {source} to {destination}")
    return digest


def detect_media_type(filename: str) -> str:
    extension = Path(filename).suffix.lower()
    for media_type, extensions in MEDIA_TYPE_MAP.items():
        if extension in extensions:
            return media_type
    return "unsupported"


def relative_to(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def render_template(template_text: str, context: dict[str, Any]) -> str:
    normalized = {key: stringify(value) for key, value in context.items()}
    return string.Template(template_text).safe_substitute(normalized)


def stringify(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return "\n".join(f"- {item}" for item in value) if value else "- none"
    if isinstance(value, dict):
        return json.dumps(value, indent=2, ensure_ascii=True)
    return str(value)


def format_bullets(values: Iterable[str], empty: str = "- none") -> str:
    cleaned = [value for value in values if value]
    if not cleaned:
        return empty
    return "\n".join(f"- {item}" for item in cleaned)


def excerpt(text: str, limit: int = 1200) -> str:
    squashed = re.sub(r"\s+", " ", text or "").strip()
    if len(squashed) <= limit:
        return squashed
    return f"{squashed[: limit - 3].rstrip()}..."


def token_overlap_score(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-z0-9]+", left.lower()))
    right_tokens = set(re.findall(r"[a-z0-9]+", right.lower()))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    return len(overlap) / len(union)


def coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
