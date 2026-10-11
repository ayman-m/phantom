"""Tests for `OverrideSender.format_record()` — the wire format.

OverrideSender encodes records according to `data_type` (not always JSON),
because the XSIAM broker → `<vendor>_<product>_raw` routing:
the broker parses the CEF/LEEF header out of incoming syslog to pick
the dataset, and JSON has no such header.

These tests assert the four-way branch (CEF / SYSLOG / LEEF / *) emits
the right wire format. They call `format_record()` directly — no
sockets, no threads, fully deterministic.
"""

from __future__ import annotations

import json
import re

import pytest

from app.override_sender import (
    OverrideSender,
    _escape_cef_extension_value,
    _escape_cef_header,
    _flatten_extension,
)


def _make_sender(data_type: str, vendor: str = "Fortinet", product: str = "FortiGate"):
    """Build an OverrideSender without actually starting the thread.

    We pass a stub vendor_fields list so __init__ doesn't reject the
    config; format_record() doesn't read vendor_fields at all.
    """
    return OverrideSender(
        worker_name="test-worker",
        data_type=data_type,
        destination="udp:127.0.0.1:9999",
        vendor_fields=[],
        vendor=vendor,
        product=product,
    )


# ── CEF ────────────────────────────────────────────────────────────────


def test_cef_header_uses_constructor_vendor_product():
    s = _make_sender("CEF", vendor="Cisco", product="ASA")
    out = s.format_record({"srcip": "10.0.0.1"})
    assert "CEF:0|Cisco|ASA|" in out


def test_cef_emits_syslog_wrapper_with_priority():
    s = _make_sender("CEF")
    out = s.format_record({"srcip": "10.0.0.1"})
    # `<134>Mon DD HH:MM:SS hostname CEF:0|…`
    assert out.startswith("<134>")
    assert " CEF:0|" in out


def test_cef_extension_key_value_format():
    s = _make_sender("CEF")
    out = s.format_record({"srcip": "10.0.0.1", "dstport": 443})
    # Extension comes after the 7th pipe (after Severity|).
    ext = out.split("|", 7)[7]
    assert "srcip=10.0.0.1" in ext
    assert "dstport=443" in ext


def test_cef_hoists_signature_id_name_severity_when_record_provides_them():
    s = _make_sender("CEF")
    out = s.format_record({
        "signatureId": "fortinet-blocked-traffic-001",
        "name": "Blocked outbound traffic",
        "severity": 7,
        "srcip": "10.0.0.1",
    })
    # CEF:0|Vendor|Product|Version|SigID|Name|Severity|extension
    parts = out.split("|")
    assert parts[4] == "fortinet-blocked-traffic-001"
    assert parts[5] == "Blocked outbound traffic"
    assert parts[6] == "7"


def test_cef_severity_defaults_to_5_when_record_omits_it():
    s = _make_sender("CEF")
    out = s.format_record({"srcip": "10.0.0.1"})
    parts = out.split("|")
    assert parts[6] == "5"


def test_cef_severity_non_int_falls_back_to_5():
    """Severity field with a string value (some vendors use 'high'/'low')
    should not blow up — fall back to the neutral default."""
    s = _make_sender("CEF")
    out = s.format_record({"severity": "high", "srcip": "10.0.0.1"})
    parts = out.split("|")
    assert parts[6] == "5"


# ── CEF: XSIAM header column names ─────────────────────────────────────


def _header_and_ext(out: str) -> tuple[list[str], str]:
    head, ext = out.rsplit("|", 1)
    return head.split("|"), ext


def test_cef_lifts_xsiam_header_columns_into_header():
    """Bundled schemas name header fields the way modeling rules read them."""
    s = _make_sender("CEF", vendor="Zscaler", product="NSSWebLog")
    parts, _ = _header_and_ext(s.format_record({
        "cefDeviceVersion": "6.1",
        "cefDeviceEventClassId": "Allowed",
        "cefName": "Web Transaction",
        "cefSeverity": 3,
        "act": "Allowed",
    }))
    # [<prefix> CEF:0, Vendor, Product, Version, SigID, Name, Severity]
    assert parts[3:7] == ["6.1", "Allowed", "Web Transaction", "3"]


def test_cef_header_columns_never_reach_the_extension():
    """Reproduces the Acme measurement: on a whitelisting vendor an extension
    `cefName=` glued onto the previous field (`act = "Allowed cefName=..."`)."""
    s = _make_sender("CEF", vendor="Zscaler", product="NSSWebLog")
    _, ext = _header_and_ext(s.format_record({
        "act": "Allowed",
        "cefName": "Web Transaction",
        "reason": "Allowed",
        "cefSeverity": "3",
        "app": "HTTPS",
        "cefVersion": "0",
        "cefDeviceEventClassId": "Allowed",
        "cefDeviceVersion": "6.1",
        "cefDeviceVendor": "Zscaler",
        "cefDeviceProduct": "NSSWebLog",
    }))
    assert ext == "act=Allowed reason=Allowed app=HTTPS"


def test_cef_xsiam_columns_win_over_generic_aliases():
    s = _make_sender("CEF")
    parts, ext = _header_and_ext(s.format_record({
        "signatureId": "generic-id",
        "cefDeviceEventClassId": "13",
        "msg": "free text",
        "cefName": "traffic:forward",
        "severity": 9,
        "cefSeverity": 2,
    }))
    assert parts[4:7] == ["13", "traffic:forward", "2"]
    # Generic aliases keep their extension slot — `msg` is a real CEF key.
    assert "msg=free text" in ext


def test_cef_record_vendor_product_never_reroute_the_event():
    """The worker's vendor/product choose the dataset; a record's copy must not."""
    s = _make_sender("CEF", vendor="Zscaler", product="NSSWebLog")
    out = s.format_record({"cefDeviceVendor": "Other", "cefDeviceProduct": "Thing", "act": "Allowed"})
    assert "CEF:0|Zscaler|NSSWebLog|" in out
    assert "Other" not in out and "Thing" not in out


def test_cef_severity_accepts_cef_spec_words():
    s = _make_sender("CEF")
    parts, _ = _header_and_ext(s.format_record({"cefSeverity": "Very-High", "act": "x"}))
    assert parts[6] == "Very-High"


def test_cef_lifted_header_values_are_escaped():
    s = _make_sender("CEF")
    parts, _ = _header_and_ext(s.format_record({"cefName": "a|b", "act": "x"}))
    assert "a\\|b" in "|".join(parts)


def test_cef_extension_skips_empty_values():
    s = _make_sender("CEF")
    out = s.format_record({"srcip": "10.0.0.1", "user": None, "comment": ""})
    ext = out.split("|", 7)[7]
    assert "srcip=10.0.0.1" in ext
    assert "user=" not in ext
    assert "comment=" not in ext


def test_cef_extension_json_encodes_lists_and_dicts():
    s = _make_sender("CEF")
    out = s.format_record({"tags": ["malware", "exfil"]})
    ext = out.split("|", 7)[7]
    # JSON-encoded array, with `=` escaped per CEF spec
    assert 'tags=["malware", "exfil"]' in ext or "tags=" in ext


def test_cef_header_escapes_pipe_in_vendor():
    """A vendor name containing | (rare but possible) must escape it
    so the CEF parser doesn't split the header at the wrong place."""
    s = _make_sender("CEF", vendor="Acme|Corp", product="X")
    out = s.format_record({"srcip": "10.0.0.1"})
    # Vendor field in header should be 'Acme\|Corp', not 'Acme|Corp'.
    parts = out.split("|")
    # parts[0] ends with '<…> Mon DD HH:MM:SS hostname CEF:0', parts[1] = vendor
    assert parts[1] == "Acme\\"
    assert parts[2] == "Corp"  # the unescaped vendor split into 2 raw parts


def test_cef_extension_escapes_equals_and_backslash():
    """Per ArcSight CEF spec, `=` and `\\` in extension values must escape."""
    s = _make_sender("CEF")
    out = s.format_record({"path": "C:\\Windows\\System32"})
    ext = out.split("|", 7)[7]
    # backslash escaping → \\\\
    assert "path=C:\\\\Windows\\\\System32" in ext


# ── SYSLOG ─────────────────────────────────────────────────────────────


def test_syslog_emits_priority_and_tag():
    s = _make_sender("SYSLOG", vendor="Fortinet", product="FortiGate")
    out = s.format_record({"srcip": "10.0.0.1"})
    assert out.startswith("<134>")
    assert "fortinet-fortigate:" in out


def test_syslog_body_is_key_value_pairs():
    s = _make_sender("SYSLOG")
    out = s.format_record({"srcip": "10.0.0.1", "dstport": 443})
    # Body comes after the tag
    body = out.split(": ", 1)[1]
    assert "srcip=10.0.0.1" in body
    assert "dstport=443" in body


def test_syslog_vendor_lowercased_in_tag():
    """Tags conventionally lowercase + replace spaces with underscores."""
    s = _make_sender("SYSLOG", vendor="Palo Alto", product="Cortex XDR")
    out = s.format_record({"srcip": "10.0.0.1"})
    assert "palo_alto-cortex_xdr:" in out


# ── LEEF ───────────────────────────────────────────────────────────────


def test_leef_header_uses_constructor_vendor_product():
    s = _make_sender("LEEF", vendor="IBM", product="QRadar")
    out = s.format_record({"srcip": "10.0.0.1"})
    assert "LEEF:2.0|IBM|QRadar|" in out


def test_leef_hoists_event_id():
    s = _make_sender("LEEF")
    out = s.format_record({"eventId": "auth-failed-42"})
    assert "|auth-failed-42|" in out


# ── JSON fallback ──────────────────────────────────────────────────────


def test_unknown_type_falls_back_to_json():
    """Any data_type not in {CEF, SYSLOG, LEEF} keeps JSON
    behavior — JSON / XSIAM_Parsed / Incident / etc."""
    s = _make_sender("JSON")
    out = s.format_record({"srcip": "10.0.0.1", "dstport": 443})
    parsed = json.loads(out)
    assert parsed == {"srcip": "10.0.0.1", "dstport": 443}


def test_data_type_none_falls_back_to_json():
    """Defensive — if data_type was lost somewhere, don't crash, just JSON."""
    s = _make_sender("")
    s.data_type = None  # simulate corruption
    out = s.format_record({"srcip": "10.0.0.1"})
    parsed = json.loads(out)
    assert parsed == {"srcip": "10.0.0.1"}


def test_winevent_falls_back_to_json():
    """WINEVENT isn't yet a structured encoder — keep JSON for now."""
    s = _make_sender("WINEVENT")
    out = s.format_record({"srcip": "10.0.0.1"})
    json.loads(out)  # must parse


# ── data_type case insensitivity ───────────────────────────────────────


def test_lowercase_cef_still_routes_to_cef_encoder():
    """schema.py passes `request_input.type.name` which is upper-cased,
    but be tolerant in case future callers pass lower-case."""
    s = _make_sender("cef")
    out = s.format_record({"srcip": "10.0.0.1"})
    assert "CEF:0|" in out


# ── helper unit tests ──────────────────────────────────────────────────


def test_flatten_extension_skips_empty_collections():
    out = _flatten_extension({"a": [], "b": "x", "c": None, "d": ""})
    assert out == "b=x"


def test_escape_cef_header_escapes_pipe_and_backslash():
    assert _escape_cef_header("a|b") == "a\\|b"
    assert _escape_cef_header("a\\b") == "a\\\\b"


def test_escape_cef_extension_value_escapes_equals_backslash_newline():
    assert _escape_cef_extension_value("a=b") == "a\\=b"
    assert _escape_cef_extension_value("a\\b") == "a\\\\b"
    assert _escape_cef_extension_value("a\nb") == "a\\nb"


def test_flatten_extension_composite_json_is_compact():
    """A composite dict value serializes to COMPACT JSON (no internal
    spaces) so it survives CEF's space-delimited extension parsing as a
    single value — the MR's json_extract_scalar then parses it."""
    rec = {"actor": {"id": "00uA", "alternateId": "a@b.com", "type": "User"}}
    ext = _flatten_extension(rec)
    assert "actor=" in ext
    # compact: no space after ':' or ',' inside the JSON
    assert '"id": ' not in ext
    assert '", "' not in ext
    # and the embedded JSON round-trips (after un-escaping the CEF `\=`)
    val = ext.split("actor=", 1)[1].replace("\\=", "=")
    assert json.loads(val) == rec["actor"]


def test_format_cef_embeds_composite_json():
    """End-to-end: a record with a composite dict → CEF line carries the
    composite as a compact JSON extension value."""
    s = _make_sender("CEF", vendor="Okta", product="Okta")
    line = s.format_record({"eventType": "user.session.start",
                            "actor": {"id": "00uA", "alternateId": "a@b.com"}})
    assert "CEF:0|Okta|Okta|" in line
    assert 'actor={"id":"00uA","alternateId":"a@b.com"}' in line
    assert "eventType=user.session.start" in line
