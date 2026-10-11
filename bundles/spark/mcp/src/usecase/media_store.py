"""SqliteMediaStore — operator file uploads with optional content extraction.

Implements the spec's `media` capability per
manifest.media.{uploadMaxMb, processors[]}.

# Layout

    <data_root>/media.db                 — metadata table
    <data_root>/media/<id>/<filename>    — original bytes (mode 0640)

# Schema

    media(
      id            TEXT PRIMARY KEY,    -- uuid4
      filename      TEXT NOT NULL,        -- as-uploaded; sanitized
      content_type  TEXT,                 -- as declared by uploader
      size_bytes    INTEGER NOT NULL,
      sha256        TEXT NOT NULL,        -- of original bytes
      uploaded_at   TEXT NOT NULL,        -- ISO8601 UTC
      uploaded_by   TEXT,                 -- actor identity
      processor     TEXT,                 -- name applied (e.g. "pdf_text")
      extracted     TEXT,                 -- extracted text (NULL if no/failed)
      processor_error TEXT                 -- nullable; failure detail
    );

# Processors

A processor is a callable `(path, content_type) -> str | None`. The
manifest's processors[] list is advisory: this module dispatches by
processor name picked based on content_type at upload time. Today
the registry has:
  * `pdf_text` — stubbed; returns None and logs a warning. Future
                 work: wire `pypdf` for actual extraction.

Adding a real processor is purely additive — register a callable
into `_PROCESSORS` (or override at runtime via `register_processor`).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("Phantom MCP")

DEFAULT_DATA_ROOT = Path("/app/data")

ProcessorFn = Callable[[Path, str | None], str | None]


# ─── Built-in processors ────────────────────────────────────────────


def _processor_pdf_text(path: Path, content_type: str | None) -> str | None:
    """Extract text from a PDF upload using pypdf.

    Returns the concatenated text of all pages, joined with double
    newlines so paragraph boundaries survive even when individual
    pages don't end with whitespace. Pages that pypdf can't decode
    (encrypted, corrupt, image-only) contribute an empty string —
    we don't want one bad page to drop the whole extraction.

    If pypdf isn't installed (CI image not yet rebuilt to include
    the dep), falls back to None and logs a warning. The upload row
    still persists; the operator just doesn't get extracted text.

    Returning None here ALSO covers the encrypted-PDF case: pypdf
    raises on `extract_text()` for password-protected files, which
    we catch and demote to "no extraction" rather than failing the
    upload. Operators can still download the original via /raw.
    """
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "media: pypdf not installed — pdf_text processor skipped for %s. "
            "Add pypdf to requirements.txt and rebuild the image.", path.name,
        )
        return None
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            # pypdf will raise on extract_text() for encrypted PDFs.
            # Try a no-password decrypt first (common for "encrypted
            # but unprotected" exports); fall back to None if that
            # fails too.
            try:
                reader.decrypt("")
            except Exception:
                logger.info(
                    "media: pdf %s is encrypted; skipping extraction.", path.name,
                )
                return None
        chunks: list[str] = []
        for page in reader.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "media: pdf %s page extract failed (%s); using empty for that page.",
                    path.name, exc,
                )
                chunks.append("")
        text = "\n\n".join(chunks).strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        # Defensive: any pypdf failure (corrupt file, unsupported
        # filter, out-of-memory) is a non-fatal "no extraction" rather
        # than a 500 on the upload endpoint.
        logger.warning(
            "media: pypdf failed on %s: %s. Upload kept; no extracted text.",
            path.name, exc,
        )
        return None


def _processor_text_passthrough(path: Path, content_type: str | None) -> str | None:
    """For text/* uploads, the bytes ARE the extracted text. We just
    decode them with utf-8 (with replacement on bad bytes — safer
    than raising mid-upload)."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("media: failed to read text upload %s: %s", path, exc)
        return None


_PROCESSORS: dict[str, ProcessorFn] = {
    "pdf_text": _processor_pdf_text,
    "text_passthrough": _processor_text_passthrough,
}


def register_processor(name: str, fn: ProcessorFn) -> None:
    """Replace or add a processor. Used by tests and future real impls."""
    _PROCESSORS[name] = fn


def _processor_for_content_type(
    content_type: str | None,
    declared_processors: set[str],
) -> str | None:
    """Pick a processor name based on content_type, gated by what the
    manifest declared. Returns None when no match (upload still succeeds,
    just no extraction)."""
    if not content_type:
        return None
    ct = content_type.split(";", 1)[0].strip().lower()
    # PDF
    if ct in {"application/pdf", "application/x-pdf"} and "pdf_text" in declared_processors:
        return "pdf_text"
    # Text — always safe to passthrough; not gated by manifest because
    # it's a degenerate "extract = read" rather than a real processor.
    if ct.startswith("text/"):
        return "text_passthrough"
    return None


_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_filename(raw: str) -> str:
    """Defensive: never trust an uploaded filename — it's used as a
    filesystem path. Strip directory separators, collapse to a safe
    charset, fall back to 'upload' on empty input."""
    just_name = os.path.basename(raw or "")
    cleaned = _FILENAME_SAFE.sub("_", just_name).strip(".")
    return cleaned or "upload"


# ─── Storage ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MediaItem:
    id: str
    filename: str
    content_type: str | None
    size_bytes: int
    sha256: str
    uploaded_at: str
    uploaded_by: str | None
    processor: str | None
    extracted: str | None
    processor_error: str | None

    def to_dict(self, include_extracted: bool = False) -> dict[str, Any]:
        d = {
            "id": self.id,
            "filename": self.filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "uploaded_at": self.uploaded_at,
            "uploaded_by": self.uploaded_by,
            "processor": self.processor,
            "processor_error": self.processor_error,
        }
        if include_extracted:
            d["extracted"] = self.extracted
        return d


class MediaTooLargeError(ValueError):
    pass


class SqliteMediaStore:
    def __init__(
        self,
        upload_max_mb: int = 25,
        declared_processors: list[str] | None = None,
        data_root: Path | None = None,
        audit_log: Any | None = None,
    ) -> None:
        self._upload_max_bytes = int(upload_max_mb) * 1024 * 1024
        self._declared_processors = set(declared_processors or [])
        self._data_root = (data_root or self._resolve_data_root()).resolve()
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._media_root = self._data_root / "media"
        self._media_root.mkdir(parents=True, exist_ok=True, mode=0o750)
        self._db_path = self._data_root / "media.db"
        self._lock = threading.Lock()
        self._audit = audit_log
        self._init_schema()

    @staticmethod
    def _resolve_data_root() -> Path:
        env = os.getenv("DATA_ROOT")
        return Path(env) if env else DEFAULT_DATA_ROOT

    def _init_schema(self) -> None:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS media (
                    id              TEXT PRIMARY KEY,
                    filename        TEXT NOT NULL,
                    content_type    TEXT,
                    size_bytes      INTEGER NOT NULL,
                    sha256          TEXT NOT NULL,
                    uploaded_at     TEXT NOT NULL,
                    uploaded_by     TEXT,
                    processor       TEXT,
                    extracted       TEXT,
                    processor_error TEXT
                )
                """
            )

    @property
    def upload_max_bytes(self) -> int:
        return self._upload_max_bytes

    @property
    def declared_processors(self) -> set[str]:
        return set(self._declared_processors)

    # ─────────────────────────────────────────────────────────────
    # Upload + read + delete
    # ─────────────────────────────────────────────────────────────

    def upload(
        self,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        actor: str | None = None,
    ) -> MediaItem:
        if not isinstance(content, (bytes, bytearray)):
            raise TypeError("content must be bytes")
        size = len(content)
        if size == 0:
            raise ValueError("empty upload")
        if size > self._upload_max_bytes:
            raise MediaTooLargeError(
                f"upload of {size} bytes exceeds limit of {self._upload_max_bytes} bytes "
                f"(manifest.media.uploadMaxMb)"
            )

        item_id = str(uuid.uuid4())
        clean_name = _sanitize_filename(filename)
        item_dir = self._media_root / item_id
        item_dir.mkdir(parents=True, exist_ok=False, mode=0o750)
        on_disk = item_dir / clean_name
        on_disk.write_bytes(bytes(content))
        try:
            os.chmod(on_disk, 0o640)
        except OSError:
            pass  # filesystem may not honor (windows, etc.)

        digest = hashlib.sha256(content).hexdigest()
        ts = self._utc_now()

        # Pick + run processor.
        proc_name = _processor_for_content_type(content_type, self._declared_processors)
        extracted: str | None = None
        proc_error: str | None = None
        if proc_name and proc_name in _PROCESSORS:
            try:
                extracted = _PROCESSORS[proc_name](on_disk, content_type)
            except Exception as exc:  # noqa: BLE001
                proc_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "media processor %s failed for %s: %s", proc_name, clean_name, proc_error,
                )

        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO media (
                    id, filename, content_type, size_bytes, sha256,
                    uploaded_at, uploaded_by, processor, extracted, processor_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item_id, clean_name, content_type, size, digest,
                 ts, actor, proc_name, extracted, proc_error),
            )

        item = MediaItem(
            id=item_id, filename=clean_name, content_type=content_type,
            size_bytes=size, sha256=digest, uploaded_at=ts,
            uploaded_by=actor, processor=proc_name, extracted=extracted,
            processor_error=proc_error,
        )
        self._audit_event(
            "media_uploaded", actor=actor, target=f"media:{item_id}",
            metadata={
                "filename": clean_name, "content_type": content_type,
                "size_bytes": size, "sha256": digest, "processor": proc_name,
            },
        )
        return item

    def get(self, media_id: str) -> MediaItem | None:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone()
        if not row:
            return None
        return self._row_to_item(row)

    def path(self, media_id: str) -> Path | None:
        item = self.get(media_id)
        if not item:
            return None
        return self._media_root / media_id / item.filename

    def list(self, limit: int = 100, offset: int = 0) -> list[MediaItem]:
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM media ORDER BY uploaded_at DESC LIMIT ? OFFSET ?",
                (int(limit), int(offset)),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def delete(self, media_id: str, actor: str | None = None) -> bool:
        item = self.get(media_id)
        if not item:
            return False
        # Delete on-disk first (file before metadata) so a crash
        # mid-delete doesn't leave a dangling DB row pointing at a
        # missing file. Worst case after crash: the file is gone but
        # the row remains — get() can detect via path().exists().
        item_dir = self._media_root / media_id
        try:
            for f in item_dir.iterdir():
                f.unlink()
            item_dir.rmdir()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("media: failed to remove %s: %s", item_dir, exc)
            return False
        with self._lock, sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
        self._audit_event(
            "media_deleted", actor=actor, target=f"media:{media_id}",
            metadata={"filename": item.filename, "sha256": item.sha256},
        )
        return True

    # ─────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────

    def _row_to_item(self, row: sqlite3.Row) -> MediaItem:
        return MediaItem(
            id=row["id"], filename=row["filename"],
            content_type=row["content_type"], size_bytes=row["size_bytes"],
            sha256=row["sha256"], uploaded_at=row["uploaded_at"],
            uploaded_by=row["uploaded_by"], processor=row["processor"],
            extracted=row["extracted"], processor_error=row["processor_error"],
        )

    def _audit_event(
        self,
        action: str,
        *,
        actor: str | None = None,
        target: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._audit is None:
            return
        try:
            record = getattr(self._audit, "record", None)
            if record is None:
                return
            record(action, target=target, actor=actor, metadata=metadata or {})
        except Exception as exc:  # pragma: no cover
            logger.warning("Media audit record failed for %s: %s", action, exc)

    @staticmethod
    def _utc_now() -> str:
        from usecase._time_utils import utc_now_micros
        return utc_now_micros()


# ─────────────────────────────────────────────────────────────────
# Module-level singleton accessor
# ─────────────────────────────────────────────────────────────────

_media_store: SqliteMediaStore | None = None


def set_media_store(store: SqliteMediaStore | None) -> None:
    global _media_store
    _media_store = store


def media_store() -> SqliteMediaStore | None:
    return _media_store
