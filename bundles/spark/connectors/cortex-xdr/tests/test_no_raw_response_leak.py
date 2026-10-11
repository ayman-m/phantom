"""Output-shape rule guard (see ../../CLAUDE.md § Tool output shape).

A tool must not attach the whole parsed PAPI response a second time as a
`raw_response` dict key alongside fields already extracted from it. Unlike
xsiam, this connector has no legitimate error-path use of raw_response at
all, so this test simply asserts zero occurrences.
"""

from __future__ import annotations

from pathlib import Path


def test_no_raw_response_dict_key_in_connector_source():
    src_path = Path(__file__).resolve().parent.parent / "src" / "connector.py"
    text = src_path.read_text()
    offending = [
        (i, line)
        for i, line in enumerate(text.splitlines(), 1)
        if '"raw_response":' in line
    ]
    assert not offending, (
        "Found raw_response as a dict key (duplicating already-parsed "
        "fields) — see ../CLAUDE.md § Tool output shape. Offending "
        f"lines: {offending}"
    )
