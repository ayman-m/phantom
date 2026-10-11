#!/usr/bin/env python3
"""Extract intermediate field names from .xif `alter` blocks
to fill out sparse "rawlog-only" packs.

# Why

parse_xdm_into_descriptions.py captures only `xdm.X = raw_field` direct
assignments. For packs whose modeling rule extracts fields via regex from _raw_log
(Cisco Catalyst, jamf, VMware vCenter, Huawei FW, GoogleCloudSCC,
etc.), this missed the intermediate field names that the .xif file
creates in `alter` clauses. Example from CiscoCatalyst_1_3.xif:

    alter
      change_state = arrayindex(regextract(msg, ...), 0),
      device_hostname = arrayindex(regextract(_raw_log, ...), 0),
      device_serial_number = arrayindex(regextract(msg, ...), 0),
      ...
    | alter
      xdm.observer.name = device_hostname,
      xdm.source.host.device_id = coalesce(device_serial_number, device_hostname),
      ...

The intermediate names (device_hostname, device_serial_number, vlan,
etc.) ARE the vendor field set we want in fields[]. Each one's
purpose is revealed by the xdm.<canonical> it maps to.

# What this script does

1. Walks scripts/maintainer/modeling_rules/*.xif
2. Parses alter blocks for `<name> = <expr>` lines (intermediates)
3. Parses the subsequent xdm assignments to learn which xdm.<canonical>
   each intermediate maps to
4. Generates a description from the xdm name (reusing the
   xdm_to_description algorithm from parse_xdm_into_descriptions.py) — or "Intermediate field for
   <vendor>" if no XDM mapping
5. For each pack with <= 5 fields in YAML, ADDS the missing
   intermediates with derived descriptions (preserves any existing
   fields untouched)

Idempotent — re-running won't duplicate.
"""
from __future__ import annotations
import re, sys, json
from collections import defaultdict
from pathlib import Path
from typing import Any

# Reuse the description generator from parse_xdm_into_descriptions.py
sys.path.insert(0, str(Path(__file__).parent))
from extend_data_source_fields import update_one_yaml
from parse_xdm_into_descriptions import xdm_to_description, extract_candidate_raw_fields

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_ROOT = REPO_ROOT / "bundles" / "spark" / "data-sources"
XIF_ROOT = REPO_ROOT / "scripts" / "maintainer" / "modeling_rules"

# Match `<identifier> = <expr>` inside the file. Captures both
# intermediate (no dots) and xdm.X.Y assignments.
_ASSIGN_RE = re.compile(
    r"^\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*=\s*([^,\n][^,\n]*)",
    re.MULTILINE,
)

# Known XIF/XQL keywords + functions — exclude from intermediate names.
_KEYWORDS = {
    "alter", "filter", "comp", "sort", "asc", "desc", "limit", "if",
    "then", "else", "and", "or", "not", "null", "true", "false",
    "case", "when", "end", "as", "to_string", "to_integer", "to_float",
    "to_boolean", "to_timestamp", "to_number", "to_epoch",
    "arrayindex", "regextract", "regexcapture", "coalesce",
    "lowercase", "uppercase", "split", "concat", "substring",
    "len", "starts_with", "ends_with", "contains", "matches",
    "is_ipv4", "is_ipv6", "is_null", "to", "from",
}

# Field-name patterns we want to SKIP as intermediates (synthetic stuff
# the .xif creates only as workflow plumbing).
_SKIP_NAME_PREFIX = ("_", "msg", "facility")  # _raw_log, _time, msg, facility are meta


def parse_xif_intermediates(text: str) -> tuple[dict[str, str], dict[str, str]]:
    """Return ({intermediate_name: xdm_canonical_name | ''},
              {xdm_name: derived_human_description}).

    First dict: vendor-side field names (intermediates) → the XDM name
    they ultimately map to (or empty string if unmapped).
    Second dict: XDM canonical names → human descriptions (for handy
    lookup).
    """
    intermediates: dict[str, str] = {}
    xdm_to_intermediate: dict[str, list[str]] = defaultdict(list)

    for m in _ASSIGN_RE.finditer(text):
        lhs = m.group(1)
        rhs = m.group(2)
        if lhs in _KEYWORDS:
            continue
        if lhs.startswith("xdm."):
            # Right-hand side: extract candidate raw field names
            candidates = extract_candidate_raw_fields(rhs)
            for c in candidates:
                # Skip meta/skip names
                if c in _KEYWORDS:
                    continue
                if c.startswith(_SKIP_NAME_PREFIX):
                    continue
                xdm_to_intermediate[lhs].append(c)
                # Tentatively map this candidate to the XDM name (last wins)
                if c not in intermediates or not intermediates[c]:
                    intermediates[c] = lhs
        else:
            # Intermediate definition. Skip if it looks like a function
            # call (LHS shouldn't have parens; already filtered by regex)
            if lhs.startswith(_SKIP_NAME_PREFIX):
                continue
            if "." in lhs:
                # Some intermediates use dot notation; skip those
                continue
            # Only add if not already mapped to an xdm — defer to
            # the xdm-assignment pass to fill the xdm value
            if lhs not in intermediates:
                intermediates[lhs] = ""

    return intermediates, {}


def derive_description(intermediate_name: str, xdm_name: str) -> str:
    """If we have an XDM mapping, derive from that. Otherwise generic."""
    if xdm_name and xdm_name.startswith("xdm."):
        return xdm_to_description(xdm_name)
    # Best-effort: humanize the intermediate name itself
    parts = intermediate_name.replace("_", " ").strip().split()
    if parts:
        return parts[0].capitalize() + (" " + " ".join(parts[1:]) if len(parts) > 1 else "")
    return intermediate_name


# Type inference from the intermediate name + XDM mapping
def infer_type(name: str, xdm_name: str) -> str:
    n = name.lower()
    xdm = xdm_name.lower()
    if "ipv6" in n or "ipv6" in xdm:
        return "ipv6"
    if "ipv4" in n or "ipv4" in xdm or n.endswith("_ip") or n.endswith("ip") and "port" not in n:
        return "ipv4"
    if "port" in n or "port" in xdm:
        return "integer_port"
    if n.endswith("_mac") or "mac_address" in xdm or "mac" in n:
        return "mac"
    if "url" in n or "url" in xdm:
        return "url"
    if "domain" in n or "fqdn" in xdm:
        return "domain"
    if "email" in n or "email" in xdm:
        return "email"
    if "username" in xdm or "user_name" in n or n == "username" or n.endswith("_user"):
        return "user"
    if "host" in n or "hostname" in xdm:
        return "host"
    if "time" in n or "date" in n or "datetime" in xdm or "timestamp" in xdm:
        return "datetime"
    if any(h in n for h in ("md5",)) or "md5" in xdm:
        return "hash_md5"
    if "sha1" in n or "sha1" in xdm:
        return "hash_sha1"
    if "sha256" in n or "sha256" in xdm:
        return "hash_sha256"
    if "country" in n or "country" in xdm:
        return "country_code"
    if "outcome" in n or "outcome" in xdm or "severity" in n:
        return "string_short"
    if n.endswith("_id") or n == "id" or n.endswith("Id"):
        return "string_short"
    return "string"


def main() -> int:
    print("=== extract .xif intermediates for rawlog packs ===\n")
    import yaml

    # Build a {pack__rule: {intermediate: (xdm_name, description, inferred_type)}} map
    rule_intermediates: dict[str, dict[str, tuple[str, str, str]]] = {}
    for xif in sorted(XIF_ROOT.glob("*.xif")):
        text = xif.read_text(errors="replace")
        intermediates, _ = parse_xif_intermediates(text)
        derived: dict[str, tuple[str, str, str]] = {}
        for name, xdm_name in intermediates.items():
            if not name or not name.isidentifier():
                continue
            desc = derive_description(name, xdm_name)
            ftype = infer_type(name, xdm_name)
            derived[name] = (xdm_name, desc, ftype)
        rule_intermediates[xif.stem] = derived

    total_added = 0
    yamls_modified = 0

    for ds_dir in sorted(BUNDLE_ROOT.glob("*/")):
        yaml_path = ds_dir / "data_source.yaml"
        if not yaml_path.is_file():
            continue
        d = yaml.safe_load(yaml_path.read_text()) or {}
        pack = d.get("pack_name")
        rule = d.get("rule_name")
        if not (pack and rule):
            continue
        key = f"{pack}__{rule}"
        if key not in rule_intermediates:
            continue
        intermediates = rule_intermediates[key]

        existing_fields = d.get("fields") or []
        existing_names = {
            (f.get("name") if isinstance(f, dict) else None)
            for f in existing_fields
        }
        existing_names.discard(None)

        # Only target packs that LOOK sparse OR have rawlog-only flag
        if len(existing_fields) > 5 and not d.get("is_rawlog_only"):
            continue

        added = 0
        new_fields = list(existing_fields)
        for name, (xdm_name, desc, ftype) in intermediates.items():
            if name in existing_names:
                continue
            new_fields.append({
                "name": name,
                "type": ftype,
                "description": desc,
            })
            existing_names.add(name)
            added += 1

        if added > 0:
            ok, msg = update_one_yaml(yaml_path, new_fields)
            if ok:
                yamls_modified += 1
                total_added += added
                print(f"  +{added:3d} fields  {ds_dir.name}")
            else:
                print(f"  ! write failed: {ds_dir.name} — {msg}")

    print()
    print(f"=== Summary ===")
    print(f"  Fields added : {total_added}")
    print(f"  YAMLs touched: {yamls_modified}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
