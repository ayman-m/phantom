"""Output-shape rule guard (see ../../CLAUDE.md § Tool output shape).

A tool must not attach the whole parsed PAPI response a second time as a
`raw_response` dict key alongside fields already extracted from it, which
would serialize the same bytes twice into every tool result.

This test is a static source check, not a behavioral one: it greps
`src/connector.py` for the quoted dict-key form `"raw_response":` and
fails if any is found. The bare keyword-argument form (`raw_response=`,
passed to the error helper `_xsiam_err` on the two legitimate
diagnostic paths in `xsiam_datamodel_describe`) is intentionally not
matched — see the CLAUDE.md rule for why those two are the one
defensible use.
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
        "fields) — see CLAUDE.md § Tool output shape. Offending lines: "
        f"{offending}"
    )
