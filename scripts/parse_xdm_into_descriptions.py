#!/usr/bin/env python3
"""Parse XDM mappings from demisto/content .xif files
and backfill field descriptions into bundled data_source.yaml files.

# Why

The agent + UI can DISPLAY field descriptions, but many fields lack
one. The .xif modeling rules carry `xdm.X.Y = raw_field` assignments
that tell us what every raw field means. This script extracts the map
and writes descriptions into the YAMLs.

# How

1. Walk `scripts/maintainer/modeling_rules/*.xif`
2. For each, parse all `xdm.X = <expr>` assignments. Extract bare raw
   field names from the expressions (unwrap to_string, coalesce, if,
   arrayindex(regextract(...)), etc.).
3. Build per-(pack, rule) map: {raw_field: xdm_canonical_name}.
4. For each xdm name, generate a human description algorithmically:
   `xdm.source.user.username` → "Source user username"
   `xdm.target.host.fqdn` → "Destination host FQDN"
5. Walk `bundles/spark/data-sources/<id>/data_source.yaml`. For each
   field without a description, look up its XDM mapping → write
   description. Skip fields that already have a description (manually
   curated ones — those are richer than what we can auto-generate).
6. Stats: how many of the missing descriptions got filled.

# Run

    python3 scripts/parse_xdm_into_descriptions.py            # apply
    python3 scripts/parse_xdm_into_descriptions.py --dry-run  # report only
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Reuse the render helper for safe YAML writes
sys.path.insert(0, str(Path(__file__).parent))
from extend_data_source_fields import update_one_yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_ROOT = REPO_ROOT / "bundles" / "spark" / "data-sources"
XIF_ROOT = REPO_ROOT / "scripts" / "maintainer" / "modeling_rules"


# ─── XIF expression unwrapping ───────────────────────────────────


# Functions whose first non-literal positional argument is the raw
# field. `to_X` wrappers and `arrayindex(...)` are simple unary wraps;
# `coalesce(a, b, c)` takes the first arg; `if(cond, true_branch, ...)`
# we treat similarly (cond is the discriminator, true_branch is the
# value source).
_UNWRAP_FUNCS = {
    "to_string", "to_integer", "to_float", "to_boolean", "to_timestamp",
    "to_number", "to_epoch", "arrayindex", "lowercase", "uppercase",
}

# `_FIELD_RE` matches a bare identifier. Common raw field names look
# like `src`, `srcip`, `cs1`, `FTNTFGTviruscat`, `deviceExternalId`,
# `_raw_log`, etc. Restricted to bare names (no dots — those would be
# xdm.* or function calls).
_FIELD_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b")

# XQL/XIF keywords + functions to ignore when collecting candidate
# raw field names from an expression.
_RESERVED_TOKENS = {
    "alter", "filter", "comp", "sort", "asc", "desc", "limit", "if",
    "then", "else", "and", "or", "not", "null", "true", "false",
    "case", "when", "end", "as", "to_string", "to_integer", "to_float",
    "to_boolean", "to_timestamp", "to_number", "to_epoch",
    "arrayindex", "regextract", "regexcapture", "coalesce",
    "lowercase", "uppercase", "split", "concat", "substring",
    "len", "starts_with", "ends_with", "contains", "matches",
    "is_ipv4", "is_ipv6", "is_null", "to", "from",
    # XDM constants
    "XDM_CONST", "FALSE", "TRUE", "NULL",
}


def extract_candidate_raw_fields(expr: str) -> list[str]:
    """Extract candidate raw field names from a single XIF expression.

    Returns identifiers that aren't:
      - keywords / reserved (if/then/else/and/or/...)
      - known XIF functions (to_string/coalesce/regextract/...)
      - xdm.* names (excluded by the bare-identifier match — `\\b` and
        no-dots in the regex)
      - numeric literals (regex starts with letter/underscore)
    """
    out: list[str] = []
    seen: set[str] = set()
    for m in _FIELD_RE.finditer(expr):
        tok = m.group(1)
        if tok in _RESERVED_TOKENS:
            continue
        if tok in seen:
            continue
        # Skip if it looks like a function being called: identifier(
        end = m.end()
        if end < len(expr) and expr[end] == "(":
            continue
        # Skip if it's part of an XDM_CONST.X reference (handled above
        # because XDM_CONST is in reserved; but the X-suffix wouldn't be
        # caught — fine, it's a constant name not a field)
        # Skip if it's a constant like "0", "1" — regex already filtered
        seen.add(tok)
        out.append(tok)
    return out


# Match `xdm.X.Y = <expr>` or `xdm.X.Y.Z = <expr>`. Expression terminates
# at the next comma at brace-depth 0 OR a newline followed by `|` (pipe)
# OR a newline followed by another `xdm.` or top-level alter clause.
# For simplicity + robustness against complex expressions, capture to
# end-of-line and unwrap.
_XDM_ASSIGN_RE = re.compile(
    r"(xdm\.[a-zA-Z_][a-zA-Z0-9_.]+)\s*=\s*([^,\n][^,\n]*)",
)


def parse_xif(xif_path: Path) -> dict[str, str]:
    """Parse one .xif file. Returns {raw_field: xdm_canonical_name}.

    When the same raw_field maps to multiple XDM names across the file
    (e.g. cs1 used for both alert.id and event.id depending on a case
    branch), the LAST mapping wins. This is a best-effort
    approach; vendor-doc dictionaries can override.
    """
    text = xif_path.read_text(errors="replace")
    mapping: dict[str, str] = {}

    for m in _XDM_ASSIGN_RE.finditer(text):
        xdm = m.group(1)
        expr = m.group(2)
        # Don't propagate from synthetic intermediate fields (those
        # generated within the .xif itself for downstream re-use).
        candidates = extract_candidate_raw_fields(expr)
        if not candidates:
            continue
        # First candidate is usually the most representative source
        raw = candidates[0]
        # Drop XIF-synthetic intermediate alias names (start with `_`
        # or have `_request_` / `_response_` infix — these are derived
        # in the same .xif file)
        if raw.startswith("_"):
            continue
        if any(infix in raw for infix in ("_request_", "_response_",
                                          "_payload_")):
            continue
        # Map this raw field to xdm canonical name (last assignment wins
        # because multiple xdm.X = same_raw are common for fallback)
        mapping[raw] = xdm

    return mapping


# ─── XDM name → human description ────────────────────────────────


# Top-level prefix translations
_PREFIX_TRANSLATIONS = {
    "source": "Source",
    "target": "Destination",
    "intermediate": "Intermediate",
    "observer": "Observer",
    "alert": "Alert",
    "event": "Event",
    "network": "Network",
    "auth": "Auth",
    "email": "Email",
    "database": "Database",
    "logon": "Logon",
    "session_context_id": "Session context id",
}

# Abbreviation/initialism overrides. Apply AFTER snake_case→Title to
# uppercase ones the dumb capitalizer would've gotten wrong.
_ABBREV_OVERRIDES = {
    "Ip": "IP",
    "Ipv4": "IPv4",
    "Ipv6": "IPv6",
    "Fqdn": "FQDN",
    "Mac": "MAC",
    "Url": "URL",
    "Uri": "URI",
    "Dns": "DNS",
    "Tcp": "TCP",
    "Udp": "UDP",
    "Ssl": "SSL",
    "Tls": "TLS",
    "Http": "HTTP",
    "Https": "HTTPS",
    "Smtp": "SMTP",
    "Ftp": "FTP",
    "Sftp": "SFTP",
    "Ssh": "SSH",
    "Pid": "PID",
    "Tgt": "TGT",
    "Ntlm": "NTLM",
    "Ldap": "LDAP",
    "Os": "OS",
    "Id": "ID",
    "Guid": "GUID",
    "Uuid": "UUID",
    "Md5": "MD5",
    "Sha1": "SHA1",
    "Sha256": "SHA256",
    "Cve": "CVE",
    "Asn": "ASN",
    "Vpn": "VPN",
    "Cn": "CN",
    "Ou": "OU",
    "Iso": "ISO",
}


def xdm_to_description(xdm_name: str) -> str:
    """Convert an xdm.X.Y.Z name to a human-readable description.

    Examples:
      xdm.source.ipv4                       → "Source IPv4"
      xdm.target.host.fqdn                  → "Destination host FQDN"
      xdm.source.user.username              → "Source user username"
      xdm.network.http.http_header.value    → "Network HTTP header value"
      xdm.alert.severity                    → "Alert severity"
      xdm.event.outcome                     → "Event outcome"
      xdm.observer.unique_identifier        → "Observer unique identifier"
    """
    if not xdm_name.startswith("xdm."):
        return xdm_name
    parts = xdm_name[4:].split(".")
    if not parts:
        return xdm_name

    # Translate prefix
    prefix = _PREFIX_TRANSLATIONS.get(parts[0], parts[0].capitalize())
    rest_tokens: list[str] = []
    for seg in parts[1:]:
        # snake_case → space-separated words, but keep multi-word segs
        # intact (e.g. `http_header` → "http header" then later both
        # tokens go through abbrev capitalization)
        for sub in seg.split("_"):
            if not sub:
                continue
            rest_tokens.append(sub)

    # First word: capitalized (the prefix). Subsequent words: lowercase
    # unless they're a known abbreviation/initialism. This matches
    # natural English description style ("Destination host FQDN" reads
    # better than "Destination Host FQDN").
    out_tokens = [prefix]
    for tok in rest_tokens:
        # Capitalize first to check abbreviation table (table keys are
        # Title-case form like "Fqdn")
        cap_form = tok.capitalize() if tok.islower() else tok
        if cap_form in _ABBREV_OVERRIDES:
            out_tokens.append(_ABBREV_OVERRIDES[cap_form])
        else:
            # Keep lowercase for non-abbrev tokens (natural English)
            out_tokens.append(tok.lower() if tok.islower() else tok)

    # Collapse duplicates like "http http header" → "http header"
    # (xdm.network.http.http_header → "Network http http header" → "Network http header")
    cleaned: list[str] = []
    for t in out_tokens:
        if cleaned and t.lower() == cleaned[-1].lower():
            continue
        cleaned.append(t)

    return " ".join(cleaned)


# ─── YAML reading without PyYAML ─────────────────────────────────


def _load_yaml_doc(yaml_path: Path) -> dict[str, Any]:
    """PyYAML-backed load of the whole doc. Faster + safer than the
    earlier naive regex approach (which under-counted ~500 fields)."""
    import yaml
    return yaml.safe_load(yaml_path.read_text()) or {}


def read_yaml_header(yaml_path: Path) -> dict[str, str]:
    d = _load_yaml_doc(yaml_path)
    return {
        k: str(d.get(k, "")).strip()
        for k in ("pack_name", "rule_name", "dataset_name")
        if d.get(k)
    }


def read_yaml_fields(yaml_path: Path) -> list[dict[str, Any]]:
    """Return the fields[] list as parsed by PyYAML — keeps every key
    including `is_array`, `is_meta`, `description`, `example`,
    `enum_values`, etc."""
    d = _load_yaml_doc(yaml_path)
    return list(d.get("fields") or [])


# ─── Apply ───────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Report stats; don't modify YAMLs")
    args = p.parse_args()

    if not BUNDLE_ROOT.is_dir():
        sys.exit(f"ERROR: bundle missing: {BUNDLE_ROOT}")
    if not XIF_ROOT.is_dir():
        sys.exit(f"ERROR: maintainer modeling rules missing: {XIF_ROOT}")

    print("=== XDM description backfill ===\n")

    # Step 1: parse each .xif → (pack, rule) → raw_field → xdm_name
    rule_mappings: dict[tuple[str, str], dict[str, str]] = {}
    for xif_path in sorted(XIF_ROOT.glob("*.xif")):
        stem = xif_path.stem  # e.g. "F5ASM__F5ASMModelingRules_1_3"
        if "__" not in stem:
            continue
        pack, rule = stem.split("__", 1)
        rule_mappings[(pack, rule)] = parse_xif(xif_path)

    print(f"  parsed {len(rule_mappings)} modeling rules")
    total_mappings = sum(len(m) for m in rule_mappings.values())
    print(f"  total raw_field → xdm_name mappings extracted: {total_mappings}")

    # Step 2: collect all unique xdm names + show description samples
    all_xdms = set()
    for m in rule_mappings.values():
        all_xdms.update(m.values())
    print(f"  unique XDM canonical names: {len(all_xdms)}")
    print()
    print("  Sample description generation:")
    for sample in ["xdm.source.ipv4", "xdm.target.host.fqdn",
                   "xdm.source.user.username", "xdm.network.http.url",
                   "xdm.network.rule", "xdm.alert.severity",
                   "xdm.observer.unique_identifier"]:
        print(f"    {sample:50s} → {xdm_to_description(sample)!r}")
    print()

    # Step 3: walk YAMLs, fill missing descriptions
    stats: dict[str, int] = {
        "yamls_total": 0, "yamls_no_rule": 0,
        "fields_total": 0, "fields_with_desc": 0,
        "fields_filled": 0, "fields_no_xdm_mapping": 0,
        "yamls_modified": 0,
    }
    no_mapping_examples: Counter[str] = Counter()

    for yaml_path in sorted(BUNDLE_ROOT.glob("*/data_source.yaml")):
        stats["yamls_total"] += 1
        header = read_yaml_header(yaml_path)
        pack = header.get("pack_name")
        rule = header.get("rule_name")
        if not (pack and rule):
            continue
        rule_map = rule_mappings.get((pack, rule), {})
        if not rule_map:
            stats["yamls_no_rule"] += 1
            continue

        fields = read_yaml_fields(yaml_path)
        if not fields:
            continue

        modified_fields: list[dict[str, Any]] = []
        any_filled = False
        for f in fields:
            stats["fields_total"] += 1
            name = f.get("name")
            existing_desc = (f.get("description") or "").strip()
            if existing_desc:
                stats["fields_with_desc"] += 1
                modified_fields.append(f)
                continue
            xdm_name = rule_map.get(name) if name else None
            if not xdm_name:
                stats["fields_no_xdm_mapping"] += 1
                no_mapping_examples[f"{pack}:{name}"] += 1
                modified_fields.append(f)
                continue
            desc = xdm_to_description(xdm_name)
            new_f = dict(f)
            new_f["description"] = desc
            modified_fields.append(new_f)
            stats["fields_filled"] += 1
            any_filled = True

        if any_filled and not args.dry_run:
            ok, msg = update_one_yaml(yaml_path, modified_fields)
            if ok:
                stats["yamls_modified"] += 1
            else:
                print(f"  ✗ write failed for {yaml_path.parent.name}: {msg}")
        elif any_filled:
            stats["yamls_modified"] += 1  # would have been

    print("=== Summary ===")
    print(f"  YAMLs scanned         : {stats['yamls_total']}")
    print(f"  YAMLs missing rule    : {stats['yamls_no_rule']}")
    print(f"  YAMLs modified        : {stats['yamls_modified']}{' (dry-run)' if args.dry_run else ''}")
    print(f"  Total fields          : {stats['fields_total']}")
    print(f"  Already had desc      : {stats['fields_with_desc']}")
    print(f"  Newly filled          : {stats['fields_filled']}")
    print(f"  No XDM mapping (gap)  : {stats['fields_no_xdm_mapping']}")
    if stats["fields_total"]:
        coverage = (
            (stats["fields_with_desc"] + stats["fields_filled"])
            / stats["fields_total"] * 100
        )
        print(f"  Coverage after run    : {coverage:.1f}%")
    print()
    print("  Top 15 fields without XDM mapping (need vendor-doc dictionaries):")
    for entry, count in no_mapping_examples.most_common(15):
        print(f"    - {entry}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
