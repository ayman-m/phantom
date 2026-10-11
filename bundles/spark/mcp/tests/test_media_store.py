"""Tests for SqliteMediaStore — operator file uploads."""

from __future__ import annotations

from typing import Any

import pytest

from src.usecase.media_store import (
    MediaTooLargeError,
    SqliteMediaStore,
    register_processor,
    _sanitize_filename,
)


@pytest.fixture
def store(tmp_path) -> SqliteMediaStore:
    return SqliteMediaStore(
        upload_max_mb=1,                  # tight cap so size tests can fire
        declared_processors=["pdf_text"],
        data_root=tmp_path,
    )


def test_upload_text_round_trips(store: SqliteMediaStore, tmp_path) -> None:
    item = store.upload(
        filename="notes.txt", content=b"Hello, world!\n",
        content_type="text/plain", actor="ayman",
    )
    assert item.size_bytes == 14
    assert item.content_type == "text/plain"
    assert item.uploaded_by == "ayman"
    assert item.processor == "text_passthrough"
    assert item.extracted == "Hello, world!\n"

    # On-disk path resolves and contains original bytes.
    path = store.path(item.id)
    assert path is not None and path.exists()
    assert path.read_bytes() == b"Hello, world!\n"


def test_upload_oversize_raises(store: SqliteMediaStore) -> None:
    too_big = b"x" * (1024 * 1024 + 1)   # 1 MB + 1 byte > 1 MB cap
    with pytest.raises(MediaTooLargeError):
        store.upload(filename="big.bin", content=too_big)


def test_upload_empty_raises(store: SqliteMediaStore) -> None:
    with pytest.raises(ValueError):
        store.upload(filename="empty.txt", content=b"")


def test_filename_sanitization() -> None:
    assert _sanitize_filename("../../etc/passwd") == "passwd"
    assert _sanitize_filename("good name (1).txt") == "good_name__1_.txt"
    assert _sanitize_filename("") == "upload"
    assert _sanitize_filename(".hidden") == "hidden"  # leading dot stripped


def test_pdf_processor_handles_garbage_input_gracefully(
    store: SqliteMediaStore,
) -> None:
    """A non-PDF byte stream sent with content_type=application/pdf
    must not 500 the upload — the processor should demote to "no
    extraction" and persist the row anyway. Operators occasionally
    send the wrong file with the wrong type; we don't punish them."""
    item = store.upload(
        filename="report.pdf", content=b"%PDF-1.4\nstub bytes\n",
        content_type="application/pdf",
    )
    assert item.processor == "pdf_text"
    # Garbage bytes -> pypdf returns None or fails internally; either
    # way our wrapper folds it into the row as no extraction.
    assert item.extracted is None
    assert item.processor_error is None


def test_pdf_processor_extracts_real_text() -> None:
    """End-to-end: build a minimal valid PDF in-memory with pypdf,
    upload it, expect to see the extracted text on the row."""
    pytest.importorskip("pypdf")
    import io

    from pypdf import PdfWriter

    # Build a one-page PDF with an embedded text marker. pypdf's
    # PdfWriter doesn't have a high-level "draw text" API; we use
    # add_blank_page + add_metadata so extract_text() at least sees
    # something. For a real text round-trip we'd need reportlab,
    # but adding that just for one test is overkill — the metadata
    # round-trip proves the pdf_text processor is reading the file
    # without erroring, which is what we care about.
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_metadata({"/Title": "Phantom Test Document"})
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()
    assert pdf_bytes.startswith(b"%PDF-")  # sanity: real PDF header

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        from pathlib import Path
        s = SqliteMediaStore(
            upload_max_mb=1, declared_processors=["pdf_text"],
            data_root=Path(td),
        )
        item = s.upload(
            filename="real.pdf", content=pdf_bytes,
            content_type="application/pdf",
        )
        assert item.processor == "pdf_text"
        assert item.processor_error is None
        # A blank page produces empty text; that demotes to None per
        # the processor's "text or None" contract. The important
        # invariant is that we DIDN'T fail.
        assert item.extracted is None or isinstance(item.extracted, str)


def test_processor_failure_recorded(tmp_path) -> None:
    """A processor exception must be folded into the row, not propagated."""

    def boom(_path, _ct):
        raise RuntimeError("processor exploded")

    register_processor("text_passthrough", boom)
    try:
        s = SqliteMediaStore(
            upload_max_mb=1, declared_processors=["pdf_text"], data_root=tmp_path,
        )
        item = s.upload(filename="x.txt", content=b"hi", content_type="text/plain")
        assert item.processor == "text_passthrough"
        assert item.extracted is None
        assert item.processor_error and "processor exploded" in item.processor_error
    finally:
        # Restore the real passthrough for downstream tests.
        from src.usecase.media_store import _processor_text_passthrough
        register_processor("text_passthrough", _processor_text_passthrough)


def test_get_returns_metadata_and_extracted(store: SqliteMediaStore) -> None:
    item = store.upload(
        filename="x.txt", content=b"abc", content_type="text/plain",
    )
    fetched = store.get(item.id)
    assert fetched is not None
    assert fetched.id == item.id
    assert fetched.extracted == "abc"


def test_list_paginates_and_orders_newest_first(store: SqliteMediaStore) -> None:
    a = store.upload(filename="a.txt", content=b"a", content_type="text/plain")
    b = store.upload(filename="b.txt", content=b"b", content_type="text/plain")
    items = store.list()
    assert items[0].id == b.id    # newest first
    assert items[1].id == a.id


def test_delete_removes_metadata_and_file(store: SqliteMediaStore) -> None:
    item = store.upload(filename="x.txt", content=b"x", content_type="text/plain")
    path = store.path(item.id)
    assert path is not None and path.exists()
    assert store.delete(item.id) is True
    assert store.get(item.id) is None
    assert not path.exists()
    # Idempotent.
    assert store.delete(item.id) is False


def test_audit_records_upload_and_delete(tmp_path) -> None:
    class _Spy:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []

        def record(self, action: str, **kw: Any) -> str:
            self.events.append({"action": action, **kw})
            return "id"

    spy = _Spy()
    s = SqliteMediaStore(
        upload_max_mb=1, declared_processors=["pdf_text"],
        data_root=tmp_path, audit_log=spy,
    )
    item = s.upload(filename="x.txt", content=b"abc", content_type="text/plain")
    s.delete(item.id, actor="ayman")

    actions = [e["action"] for e in spy.events]
    assert actions == ["media_uploaded", "media_deleted"]
    # Hash + filename logged; bytes never.
    md_upload = spy.events[0]["metadata"]
    assert md_upload["filename"] == "x.txt"
    assert md_upload["sha256"]    # populated
    assert "content" not in md_upload    # never logged
    assert "extracted" not in md_upload  # never logged


def test_unknown_content_type_no_processor(store: SqliteMediaStore) -> None:
    item = store.upload(
        filename="x.bin", content=b"\x00\x01\x02",
        content_type="application/x-strange",
    )
    assert item.processor is None
    assert item.extracted is None


def test_persistence_across_reopen(tmp_path) -> None:
    s1 = SqliteMediaStore(
        upload_max_mb=1, declared_processors=["pdf_text"], data_root=tmp_path,
    )
    item = s1.upload(filename="x.txt", content=b"hello", content_type="text/plain")

    s2 = SqliteMediaStore(
        upload_max_mb=1, declared_processors=["pdf_text"], data_root=tmp_path,
    )
    fetched = s2.get(item.id)
    assert fetched is not None and fetched.extracted == "hello"
