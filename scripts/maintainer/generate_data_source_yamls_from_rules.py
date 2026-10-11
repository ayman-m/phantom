#!/usr/bin/env python3
"""Generate enriched data_source.yaml per pack, baking in the CEF wire-format
rules learned from end-to-end testing.

# Input

`scripts/maintainer/rules_by_dataset/` populated by `organize_rules_by_dataset.py`:
  - direct_mapped_cef/<dataset>/{modeling*.xif, parsing*.xif, manifest.json}
  - direct_mapped_other/<dataset>/{modeling*.xif, parsing*.xif, manifest.json}
  - raw_log_based/<dataset>/... — **SKIPPED** (requires operator-side broker
    applet; doesn't fit the CEF auto-route pattern this generator targets)
  - raw_json_based/<dataset>/... — also skipped for the same reason

# Output

`scripts/maintainer/generated_data_sources/<dataset>/data_source.yaml` — does
NOT touch `bundles/spark/data-sources/`. This is a dry-run preview so we can
review the enriched format before deciding which subset to promote.

# What the enriched YAML carries (on top of the existing schema)

  - `broker_routing`: vendor + product strings the broker reads from the CEF
    header to construct `<lower(vendor)>_<lower(product)>_raw`.
  - `mr_filter`: top-level MR filter requirements (cefDeviceProduct value,
    `cat` value, cefDeviceEventClassId range). Without these, MR doesn't fire.
  - `label_pairings`: per-slot Label values the MR consumes (e.g. cs2 only
    maps to xdm.network.rule when cs2Label="Rule Name").
  - `xdm_mappings`: list of {cef_source_field, xdm_target, requires_label?,
    constraint?} extracted from MR alter clauses.
  - `coalesce_groups`: fields the MR treats as interchangeable (operator can
    populate either, MR picks first non-null).
  - `marker_field`: recommended carrier for the E2E saturation testing
    pattern. Picks a CEF field whose XDM target is uniquely identifying.
  - `field_constraints`: per-field hints from lessons (rt must be 10+ digit
    epoch, src must match IPv4 regex, etc.).

# Rules baked in — short list of refinements:

  - rt: type=timestamp_ms (not datetime); MR regextracts \\d{10} slice.
  - src/dst: type=ipv4 when MR has `if(src ~= "\\d{1,3}\\..." ...)` gate.
  - spt/dpt: type=integer_port (already).
  - cs*/cn*: type unchanged but `label_required` populated.
  - duration / `in` / `out`: type=integer (MR uses to_integer).
  - cefSeverity: type=integer_short (numeric 0-10 typically).

# Run

    python3 scripts/maintainer/generate_data_source_yamls_from_rules.py

Re-runnable. Wipes `scripts/maintainer/generated_data_sources/` on each run
so stale entries don't accumulate.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:
    sys.stderr.write("install pyyaml: pip install pyyaml\n")
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "scripts" / "maintainer" / "rules_by_dataset"
OUTPUT_DIR = REPO_ROOT / "scripts" / "maintainer" / "generated_data_sources"

# Source-of-truth bundled YAML location (we read existing fields[] from here
# when generating, so we keep existing field descriptions/types unless the
# MR/PR lessons demand a refinement).
BUNDLED_DS_DIR = REPO_ROOT / "bundles" / "spark" / "data-sources"

# Categories to process. Anything labeled raw_log_based or raw_json_based
# requires operator-side broker applet/HTTP collector config and doesn't fit
# the CEF auto-route pattern this generator emits.
INCLUDE_CATEGORIES = {"direct_mapped_cef", "direct_mapped_other"}
EXCLUDE_CATEGORIES = {"raw_log_based", "raw_json_based"}

# Known-good CEF header values for packs verified E2E (100% XDM saturation).
# These override heuristic reverse-engineering.
VERIFIED_BROKER_ROUTING: dict[str, dict[str, str]] = {
    "check_point_vpn_1_firewall_1_raw": {
        "cef_header_vendor": "Check Point",
        "cef_header_product": "VPN-1 & FireWall-1",
        "verified_e2e": "true",
        "xdm_saturation": "31/31 (100%)",
    },
    "cisco_firepower_raw": {
        "cef_header_vendor": "Cisco",
        "cef_header_product": "Firepower",
        "verified_e2e": "true",
        "xdm_saturation": "31/31 (100%)",
    },
    "manageengine_adauditplus_raw": {
        "cef_header_vendor": "ManageEngine",
        "cef_header_product": "ADAuditPlus",
        "verified_e2e": "true",
        "xdm_saturation": "25/25 (100%)",
    },
    "trend_micro_deep_security_agent_raw": {
        "cef_header_vendor": "Trend Micro",
        "cef_header_product": "Deep Security Agent",
        "verified_e2e": "raw_lands_mr_not_installed",
    },
    "trend_micro_deep_security_manager_raw": {
        "cef_header_vendor": "Trend Micro",
        "cef_header_product": "Deep Security Manager",
        "verified_e2e": "raw_lands_mr_not_installed",
    },
}


def reverse_engineer_cef_header(dataset: str,
                                 pr_vendor: str | None,
                                 pr_product: str | None,
                                 manifest_vendor: str,
                                 manifest_product: str) -> dict[str, Any]:
    """Determine the CEF header vendor/product strings the operator must emit.

    Preference order:
      1. VERIFIED_BROKER_ROUTING lookup (E2E-verified ground truth)
      2. PR INGEST line vendor/product (operator-installed canonical name)
      3. Heuristic: split dataset on _raw, reverse-engineer from underscores
         using manifest's vendor/product as casing guide
      4. Fallback: manifest vendor/product (may be pack-id, not CEF product)
    """
    # 1. Verified lookup
    if dataset in VERIFIED_BROKER_ROUTING:
        return {
            "cef_header_vendor": VERIFIED_BROKER_ROUTING[dataset]["cef_header_vendor"],
            "cef_header_product": VERIFIED_BROKER_ROUTING[dataset]["cef_header_product"],
            "source": "verified_e2e",
            "verification_status": VERIFIED_BROKER_ROUTING[dataset].get("verified_e2e", "true"),
            "xdm_saturation": VERIFIED_BROKER_ROUTING[dataset].get("xdm_saturation"),
        }

    # 2. PR INGEST line
    if pr_vendor and pr_product:
        # Sanity check: does the PR's combo produce the dataset?
        produced = (
            re.sub(r"[^a-z0-9]+", "_", pr_vendor.lower()).strip("_")
            + "_"
            + re.sub(r"[^a-z0-9]+", "_", pr_product.lower()).strip("_")
            + "_raw"
        )
        if produced == dataset:
            return {
                "cef_header_vendor": pr_vendor,
                "cef_header_product": pr_product,
                "source": "pr_ingest_line",
            }
        # Even if the produced dataset doesn't exactly match (operator may
        # have customized), still use PR line — they're closer to ground
        # truth than the manifest.
        return {
            "cef_header_vendor": pr_vendor,
            "cef_header_product": pr_product,
            "source": "pr_ingest_line",
            "dataset_mismatch_note": (
                f"PR INGEST vendor/product would produce '{produced}' but actual "
                f"dataset is '{dataset}'. Operator may have customized."
            ),
        }

    # 3+4. Fall back to manifest, but mark as inferred
    return {
        "cef_header_vendor": manifest_vendor,
        "cef_header_product": manifest_product,
        "source": "manifest_fallback",
        "warning": (
            "manifest's product field is often the pack-id (e.g. 'CheckpointFirewall') "
            "not the CEF header product (e.g. 'VPN-1 & FireWall-1'). Verify by "
            "sending a probe CEF event and checking dataset routing."
        ),
    }


# Per-lesson type refinements. If a field's name appears here and its current
# type is in the "old_types" set, we upgrade to the new type.
TYPE_REFINEMENTS: dict[str, dict] = {
    "rt": {
        "old_types": {"datetime", "string", "string_short", "timestamp_ms", None},
        "new_type": "timestamp_ms",
        "constraint": "Must be 10+ digit numeric epoch (sec or ms). MR parsing rules regextract `\\d{10}` slice — anything shorter is dropped.",
    },
    "src": {
        "old_types": {"string", "string_short", "ipv4", "ipv6", None},
        "new_type": "ipv4",
        "constraint": "Must match `\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}` regex. Non-IPv4 values fall through to xdm.source.ipv6.",
    },
    "dst": {
        "old_types": {"string", "string_short", "ipv4", "ipv6", None},
        "new_type": "ipv4",
        "constraint": "Must match `\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}` regex. Non-IPv4 values fall through to xdm.target.ipv6.",
    },
    "spt": {
        "old_types": {"string", "integer", "integer_port", None},
        "new_type": "integer_port",
        "constraint": "Bare integer 0-65535. MR coerces via to_integer(spt).",
    },
    "dpt": {
        "old_types": {"string", "integer", "integer_port", None},
        "new_type": "integer_port",
        "constraint": "Bare integer 0-65535. MR coerces via to_integer(dpt).",
    },
    "duration": {
        "old_types": {"string", None},
        "new_type": "integer",
        "constraint": "Bare integer (typically seconds). MR may multiply by 1000 to get ms for xdm.event.duration.",
    },
    "in": {
        "old_types": {"string", None},
        "new_type": "integer_byte_count",
        "constraint": "Bare integer byte count. Note `in` is a SQL reserved word — MR uses backticks: `in`.",
    },
    "out": {
        "old_types": {"string", None},
        "new_type": "integer_byte_count",
        "constraint": "Bare integer byte count.",
    },
    "bytesIn": {
        "old_types": {"string", None},
        "new_type": "integer_byte_count",
        "constraint": "Bare integer byte count (Cisco-style capitalized).",
    },
    "bytesOut": {
        "old_types": {"string", None},
        "new_type": "integer_byte_count",
        "constraint": "Bare integer byte count (Cisco-style capitalized).",
    },
    "cefSeverity": {
        "old_types": {"string", "string_short", None},
        "new_type": "integer",
        "constraint": "Numeric 0-10. CEF spec defines 0=Low, 10=High.",
    },
    "proto": {
        "old_types": {"string", None},
        "new_type": "string_short",
        "constraint": "IANA protocol number (e.g. 6=TCP, 17=UDP, 1=ICMP) OR uppercase name (TCP/UDP/ICMP). MR maps to XDM_CONST.IP_PROTOCOL_*.",
    },
}


# ============================================================
# .xif parsing
# ============================================================

# Strip CEF/XIF comments  /* ... */ and // ...
COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
COMMENT_LINE_RE = re.compile(r"//[^\n]*")


def strip_comments(text: str) -> str:
    text = COMMENT_BLOCK_RE.sub("", text)
    text = COMMENT_LINE_RE.sub("", text)
    return text


# Matches: `[MODEL: dataset="X"]` or `[MODEL:dataset = "X", model=Y]`
MODEL_HEADER_RE = re.compile(
    r'\[\s*MODEL\s*:\s*dataset\s*=\s*"([^"]+)"(?:\s*,\s*model\s*=\s*([A-Za-z]+))?\s*\]'
)

# Matches: `xdm.x.y.z = <expression>,?`
# Captures group 2 = the WHOLE RHS expression up to next `,` or `;`. We then
# parse the RHS separately to handle to_integer(), coalesce(), if(), nested.
XDM_ALTER_RE = re.compile(
    r"(xdm(?:\.[A-Za-z_][A-Za-z_0-9]*)+)"          # xdm.path
    r"\s*=\s*"
    r"((?:[^,;]|coalesce\([^)]*\)|to_\w+\([^)]*\)|if\([^)]*\))+)"
    r"(?=\s*[,;])"
)

# Standard CEF dictionary field names — we treat these as "real source fields"
# when extracting cef_source from RHS expressions. Anything not in this list
# AND not matching `cs[1-6]|cn[1-3]|flexString[12]` is treated as an alter-
# variable (intermediate) and we try to resolve it.
CEF_DICT = {
    "act", "app", "cat", "cn1", "cn2", "cn3", "cnt", "cs1", "cs2", "cs3", "cs4",
    "cs5", "cs6", "cs1Label", "cs2Label", "cs3Label", "cs4Label", "cs5Label",
    "cs6Label", "cn1Label", "cn2Label", "cn3Label", "destinationDnsDomain",
    "destinationServiceName", "deviceCustomDate1", "deviceDirection",
    "deviceFacility", "deviceInboundInterface", "deviceOutboundInterface",
    "deviceProcessName", "deviceExternalId", "deviceTranslatedAddress",
    "dhost", "dmac", "dntdom", "dpid", "dproc", "dpt", "dst", "duid",
    "duser", "dvc", "dvchost", "dvcpid", "externalId", "fileCreateTime",
    "fileHash", "filePath", "fileType", "flexString1", "flexString2",
    "flexString1Label", "flexString2Label", "fname", "fsize", "in",
    "loguid", "msg", "out", "outcome", "proto", "reason", "request",
    "requestClientApplication", "requestContext", "requestCookies",
    "requestMethod", "requestUrl", "rt", "shost", "smac", "sntdom",
    "sourceDnsDomain", "sourceServiceName", "sourceTranslatedAddress",
    "spid", "sproc", "spt", "src", "start", "suid", "suser", "target",
    "targetID", "targetType",
    # CEF header positional → also extension
    "cefDeviceVendor", "cefDeviceProduct", "cefDeviceVersion",
    "cefDeviceEventClassId", "cefName", "cefSeverity", "cefVersion",
    # XSIAM-broker injected
    "TrendMicroDsTenant", "TrendMicroDsTenantId", "TrendMicroDsTags",
}


def extract_leaf_fields(rhs: str) -> list[str]:
    """From an XQL expression RHS, extract the underlying field identifier(s).

    Handles:
      - `to_integer(spt)`           → ['spt']
      - `coalesce(reason, action_reason)` → ['reason', 'action_reason']
      - `if(reason != "", reason, action_reason)` → ['reason', 'action_reason']
      - `to_integer(multiply(to_integer(duration), 1000))` → ['duration']
      - bare identifier `loguid`    → ['loguid']
      - `application` (alter var)   → ['application'] — caller resolves further
    """
    rhs = rhs.strip()

    # Strip enclosing function wrappers iteratively
    fn_wrap = re.compile(r"^(to_\w+|multiply|add|divide|uppercase|lowercase|"
                         r"to_string|to_boolean|to_integer|regextract|arrayindex|"
                         r"arrayfilter|arraydistinct|arraycreate|arrayconcat|"
                         r"parse_timestamp|len|split)\s*\(")
    # Keep peeling layers while the expression starts with a recognized fn call
    while True:
        m = fn_wrap.match(rhs)
        if not m:
            break
        # Find matching paren
        depth = 0
        start = m.end() - 1  # the '(' position
        end = -1
        for i in range(start, len(rhs)):
            if rhs[i] == "(":
                depth += 1
            elif rhs[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            break
        inner = rhs[m.end():end]
        # If function is coalesce/if/arraycreate/arrayconcat, split on top-level commas
        if m.group(1) in ("coalesce", "if", "arraycreate", "arrayconcat"):
            parts = split_top_level_commas(inner)
            results: list[str] = []
            for p in parts:
                p = p.strip()
                if not p or p in ("null",) or p.startswith('"') or p.startswith("'"):
                    continue
                # Skip literal numbers and XDM_CONST refs
                if re.match(r"^-?\d", p) or p.startswith("XDM_CONST."):
                    continue
                # Skip equality checks like `cs2Label = "Rule Name"` — the actual
                # source is the next arg
                if "=" in p and not p.startswith(("!=", "==")) and "==" not in p:
                    # Skip equality test args in if() — not the value-producing branch
                    continue
                results.extend(extract_leaf_fields(p))
            return results
        # Otherwise recurse into inner
        rhs = inner.strip()

    # Bare identifier or backticked
    rhs = rhs.strip("`").strip()
    # Reject XDM_CONST and string literals
    if rhs.startswith("XDM_CONST.") or rhs.startswith('"') or rhs.startswith("'"):
        return []
    # Reject pure numeric
    if re.match(r"^-?\d", rhs):
        return []
    # Single identifier
    m = re.match(r"^([A-Za-z_][A-Za-z_0-9]*)$", rhs)
    if m:
        return [m.group(1)]
    # Identifier with dots (e.g. xdm.x) — not a source field
    if "." in rhs:
        return []
    return []


def split_top_level_commas(s: str) -> list[str]:
    """Split on top-level commas (not nested inside parens)."""
    parts = []
    depth = 0
    cur = ""
    for ch in s:
        if ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return parts

# Matches: `if(csNLabel = "label_value", csN, null)` and variants
LABEL_CONDITIONAL_RE = re.compile(
    r"""if\(\s*
        (cs[1-6]|cn[1-3]|flexString[12])Label
        \s*=\s*"
        ([^"]+)
        "\s*,\s*\1\s*,\s*null\s*\)""",
    re.VERBOSE,
)

# Matches: `coalesce(a, b, c)` — captures comma-separated identifier list
COALESCE_RE = re.compile(r"coalesce\(\s*([A-Za-z_][A-Za-z_0-9,\s`]*)\)")

# Matches: `filter cefDeviceProduct = "X"` (top-level filter)
FILTER_CEF_PRODUCT_RE = re.compile(
    r'filter\s+cefDeviceProduct\s*=\s*"([^"]+)"', re.IGNORECASE
)

# Matches: `filter cat = "X"` (Fortiweb-style category filter)
FILTER_CAT_RE = re.compile(r'filter\s+cat\s*=\s*"([^"]+)"', re.IGNORECASE)

# Matches event_id range filter: `event_id >= N and event_id < M`
EVENT_ID_RANGE_RE = re.compile(
    r"event_id\s*>=\s*(\d+)\s+and\s+event_id\s*<\s*(\d+)"
)
# Matches: `event_id in (N, M, ...)`
EVENT_ID_IN_RE = re.compile(r"event_id\s+in\s*\(([\d,\s]+)\)")

# Matches the IPv4 regex gate. We detect that a field has this constraint.
IPV4_GATE_RE = re.compile(
    r"if\(\s*([A-Za-z_][A-Za-z_0-9]*)\s*~=\s*\"\\d\{1,3\}\\\.\\d\{1,3\}"
)

# Matches INGEST line in parsing rule: vendor + product + target_dataset
INGEST_HEADER_RE = re.compile(
    r'\[\s*INGEST\s*:\s*'
    r'vendor\s*=\s*"([^"]+)"\s*,\s*'
    r'product\s*=\s*"([^"]+)"\s*,\s*'
    r'target_dataset\s*=\s*"([^"]+)"'
)

# Matches PR filter on any timestamp field: `to_string(X) ~= "\d{N}$"` or `~= "\d{N,}"`
PR_TIMESTAMP_FILTER_RE = re.compile(
    r'filter\s+(?:to_string\()?'
    r'([A-Za-z_][A-Za-z_0-9]*)'      # field name
    r'\)?\s*~=\s*"'
    r'\\d\{(\d+)(?:,(\d*))?\}(\$?)'  # digit count + optional max + optional end anchor
    r'"'
)

# Matches PR `replex(FIELD, "\d{N}$", "")` — strips last N digits
PR_REPLEX_STRIP_RE = re.compile(
    r'replex\(\s*([A-Za-z_][A-Za-z_0-9]*)\s*,\s*"\\d\{(\d+)\}\$"\s*,\s*""\s*\)'
)

# Matches PR `| fields X, Y, Z;` directive (final field whitelist)
PR_FIELDS_WHITELIST_RE = re.compile(
    r'\|\s*fields\s+([^;|]+?)(?:;|\s*$)', re.MULTILINE
)

# ============================================================
# MR anomaly detectors — patterns that indicate MR bugs/quirks
# ============================================================

# Detects swapped icmp labels: xdm.network.icmp.code = add(icmp_type_*) and vice versa
ICMP_SWAP_RE_CODE = re.compile(
    r'xdm\.network\.icmp\.code\s*=\s*to_integer\(add\(icmp_type_'
)
ICMP_SWAP_RE_TYPE = re.compile(
    r'xdm\.network\.icmp\.type\s*=\s*to_integer\(add\(icmp_code_'
)

# Detects `if(X = "literal", X)` with no else branch — populates only on literal match
NO_ELSE_IF_LITERAL_RE = re.compile(
    r'xdm(?:\.[A-Za-z_][A-Za-z_0-9]*)+ \s*=\s*'
    r'if\(\s*([A-Za-z_][A-Za-z_0-9]*)\s*=\s*"([^"]+)"\s*,\s*\1\s*\)',
    re.VERBOSE
)

# Detects "unkown" typo (and other common misspellings)
COMMON_TYPOS = {
    "unkown": "unknown",
    "recieved": "received",
    "occured": "occurred",
    "succesful": "successful",
}

# Detects mutually exclusive XDM via filehash length check pattern
FILEHASH_MUTEX_RE = re.compile(
    r'xdm(?:\.[A-Za-z_][A-Za-z_0-9]*)+ \s*=\s*'
    r'if\(\s*(?:filehash_length|len\(\w+\))\s*=\s*(\d+)\s*,',
    re.VERBOSE
)


# ============================================================
# MR/PR parsers
# ============================================================

def parse_modeling_rule(text: str, target_dataset: str) -> dict[str, Any]:
    """Parse a modeling.xif and return a dict of structured info.

    Note: we extract from the LAST [MODEL: dataset="<target>"] block that
    matches the target dataset. Earlier blocks may describe other datasets
    in the same file.
    """
    text = strip_comments(text)

    # Find all [MODEL: dataset="X"] sections — split text by them
    sections: list[tuple[str, str]] = []  # (dataset, block_text)
    last_pos = 0
    last_dataset = None
    for m in MODEL_HEADER_RE.finditer(text):
        if last_dataset is not None:
            sections.append((last_dataset, text[last_pos:m.start()]))
        last_dataset = m.group(1)
        last_pos = m.end()
    if last_dataset is not None:
        sections.append((last_dataset, text[last_pos:]))

    # Pick sections matching our target dataset (may be multi-clause)
    matching = [(ds, block) for ds, block in sections if ds == target_dataset]
    if not matching:
        return {"parse_status": "no_matching_model_block", "target_dataset": target_dataset}

    info: dict[str, Any] = {
        "parse_status": "ok",
        "target_dataset": target_dataset,
        "clauses": [],  # list of per-clause info (multi-clause MRs)
        "label_pairings": {},  # cs2 -> "Rule Name", etc.
        "xdm_mappings": [],    # list of {source, xdm_target}
        "coalesce_groups": [],  # list of {xdm_target, sources[]}
        "ipv4_gated_fields": set(),
        "filter_cefDeviceProduct": None,
        "filter_cat": None,
        "event_id_ranges": [],  # list of (low, high) for in-range
        "event_id_in_set": [],   # list of explicit values
        "intermediate_alters": {},  # alter_var -> rhs_expr (for resolution)
    }

    # Pre-scan: collect all alter assignments — both `alter <var> = <expr>` and
    # comma-continuation assignments like `, <var> = <expr>` within a block.
    # Pattern walks the text char-by-char to find ALTER BLOCKS, then splits
    # each block by top-level commas.
    block_starts = [m.start() for m in re.finditer(r"\balter\s+", text)]
    for start in block_starts:
        # Find the end of the alter block — first top-level `|` or `;`
        depth = 0
        i = start
        end = len(text)
        while i < len(text):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "|" and depth == 0:
                end = i
                break
            elif ch == ";" and depth == 0:
                end = i
                break
            i += 1
        block = text[start:end]
        # Strip leading "alter "
        block = re.sub(r"^\s*alter\s+", "", block, count=1)

        # Split block by TOP-LEVEL commas (depth-0)
        depth = 0
        cur = ""
        pieces = []
        for ch in block:
            if ch == "(":
                depth += 1
                cur += ch
            elif ch == ")":
                depth -= 1
                cur += ch
            elif ch == "," and depth == 0:
                pieces.append(cur)
                cur = ""
            else:
                cur += ch
        if cur.strip():
            pieces.append(cur)

        for piece in pieces:
            piece = piece.strip()
            # Match `<ident> = <expr>` — LHS is a single identifier (not xdm.*)
            m = re.match(r"^([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.+)$", piece, re.DOTALL)
            if not m:
                continue
            var_name = m.group(1)
            rhs = m.group(2).strip()
            # Skip XQL keywords + label-ish names (those are inside if() comparators)
            if var_name in ("if", "filter", "alter", "call", "fields",
                            "null", "true", "false"):
                continue
            # `cs2Label = "Rule Name"` etc. — these appear inside if() blocks
            # but our top-level split keeps them inside. Skip explicitly.
            if var_name.endswith("Label"):
                continue
            # Skip xdm.* assignments — handled separately
            if "." in var_name:
                continue
            if var_name not in info["intermediate_alters"]:
                info["intermediate_alters"][var_name] = rhs

    for ds, block in matching:
        clause_info: dict[str, Any] = {}

        # Top-level filter — cefDeviceProduct
        m = FILTER_CEF_PRODUCT_RE.search(block)
        if m:
            info["filter_cefDeviceProduct"] = m.group(1)
            clause_info["cefDeviceProduct"] = m.group(1)

        # cat filter
        m = FILTER_CAT_RE.search(block)
        if m:
            info["filter_cat"] = m.group(1)
            clause_info["cat"] = m.group(1)

        # event_id ranges
        for m in EVENT_ID_RANGE_RE.finditer(block):
            info["event_id_ranges"].append((int(m.group(1)), int(m.group(2))))
        for m in EVENT_ID_IN_RE.finditer(block):
            vals = [int(v.strip()) for v in m.group(1).split(",")]
            info["event_id_in_set"].extend(vals)

        # Label conditionals
        for m in LABEL_CONDITIONAL_RE.finditer(block):
            slot, label_value = m.group(1), m.group(2)
            info["label_pairings"][slot] = label_value

        # IPv4 gate
        for m in IPV4_GATE_RE.finditer(block):
            info["ipv4_gated_fields"].add(m.group(1))

        # XDM alter mappings — use full RHS extraction + intermediate resolution
        for m in XDM_ALTER_RE.finditer(block):
            xdm_path = m.group(1)
            rhs = m.group(2).strip()

            # Extract leaf field names (peels function wrappers + coalesce branches)
            leaves = extract_leaf_fields(rhs)

            # If multi-source coalesce, record group
            if rhs.startswith("coalesce("):
                inner = rhs[len("coalesce("):]
                # Find matching paren
                depth = 1
                end = -1
                for i, ch in enumerate(inner):
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
                if end >= 0:
                    inner = inner[:end]
                    sources = []
                    for part in split_top_level_commas(inner):
                        sources.extend(extract_leaf_fields(part))
                    if len(sources) > 1:
                        info["coalesce_groups"].append({
                            "xdm_target": xdm_path,
                            "sources": sources,
                        })

            # Resolve intermediate alter vars (1 layer) to their underlying CEF source
            resolved_leaves: list[str] = []
            for leaf in leaves:
                if leaf in CEF_DICT or re.match(r"^cs[1-6]$|^cn[1-3]$|^flexString[12]$", leaf):
                    resolved_leaves.append(leaf)
                elif leaf in info["intermediate_alters"]:
                    # Trace into the intermediate
                    inter_rhs = info["intermediate_alters"][leaf]
                    inter_leaves = extract_leaf_fields(inter_rhs)
                    # Keep CEF dict leaves; recurse one more level for nested intermediates
                    for il in inter_leaves:
                        if il in CEF_DICT or re.match(r"^cs[1-6]$|^cn[1-3]$|^flexString[12]$", il):
                            resolved_leaves.append(il)
                        elif il in info["intermediate_alters"]:
                            # 2nd level
                            il2 = extract_leaf_fields(info["intermediate_alters"][il])
                            resolved_leaves.extend(il2)
                        else:
                            resolved_leaves.append(il)
                else:
                    # Unknown identifier — keep as-is (operator-side custom extension)
                    resolved_leaves.append(leaf)

            for source in resolved_leaves:
                # Skip null literals + function-name false positives
                if source in ("null", "true", "false") or not source:
                    continue
                info["xdm_mappings"].append({
                    "cef_source": source,
                    "xdm_target": xdm_path,
                })

        if clause_info:
            info["clauses"].append(clause_info)

    info["ipv4_gated_fields"] = sorted(info["ipv4_gated_fields"])

    # Dedupe xdm_mappings (same source+target may appear multiple times across clauses)
    seen: set[tuple[str, str]] = set()
    deduped = []
    for x in info["xdm_mappings"]:
        key = (x["cef_source"], x["xdm_target"])
        if key not in seen:
            seen.add(key)
            deduped.append(x)
    info["xdm_mappings"] = deduped

    return info


def parse_parsing_rule(text: str) -> dict[str, Any]:
    """Parse a parsing.xif and return INGEST + filter + timestamp + whitelist info."""
    text = strip_comments(text)
    info: dict[str, Any] = {
        "ingest_vendor": None,
        "ingest_product": None,
        "ingest_target_dataset": None,
        "pr_timestamp_field": None,
        "pr_timestamp_min_digits": None,
        "pr_timestamp_anchored_end": False,
        "pr_timestamp_strip_last_n": None,   # FortiGate-style: replex strips last N digits
        "pr_field_whitelist": [],            # fields surviving the PR's `| fields ...`
        "pr_field_whitelist_has_wildcard": False,  # True if `VENDOR*` or similar
    }

    m = INGEST_HEADER_RE.search(text)
    if m:
        info["ingest_vendor"] = m.group(1)
        info["ingest_product"] = m.group(2)
        info["ingest_target_dataset"] = m.group(3)

    m = PR_TIMESTAMP_FILTER_RE.search(text)
    if m:
        info["pr_timestamp_field"] = m.group(1)
        info["pr_timestamp_min_digits"] = int(m.group(2))
        info["pr_timestamp_anchored_end"] = (m.group(4) == "$")

    m = PR_REPLEX_STRIP_RE.search(text)
    if m:
        info["pr_timestamp_strip_last_n"] = int(m.group(2))

    # Extract the LAST `| fields ...` directive (PR may have multiple — the final
    # one defines the whitelist that reaches the dataset).
    all_fields_matches = PR_FIELDS_WHITELIST_RE.findall(text)
    if all_fields_matches:
        last = all_fields_matches[-1].strip()
        # Parse comma-separated; handle backticks like `in`
        tokens = [t.strip().strip("`") for t in last.split(",")]
        # Detect wildcards
        wildcard = any("*" in t for t in tokens)
        info["pr_field_whitelist_has_wildcard"] = wildcard
        info["pr_field_whitelist"] = [t for t in tokens if t and not t.startswith("-")]

    return info


def detect_mr_anomalies(text: str) -> list[dict[str, Any]]:
    """Detect known MR anomaly patterns: typos, label swaps, no-else if patterns."""
    anomalies = []

    # ICMP label swap (FortiGate-style)
    if ICMP_SWAP_RE_CODE.search(text) and ICMP_SWAP_RE_TYPE.search(text):
        anomalies.append({
            "type": "icmp_label_swap",
            "severity": "warning",
            "description": (
                "xdm.network.icmp.code is fed from icmp_TYPE_lsb/msb (and vice versa) — "
                "looks like the labels are swapped between code and type. "
                "Honor the existing behavior: what the operator sets as type will "
                "land in xdm.network.icmp.code."
            ),
        })

    # No-else if(X = "literal", X) patterns
    for m in NO_ELSE_IF_LITERAL_RE.finditer(text):
        anomalies.append({
            "type": "no_else_if_literal",
            "severity": "warning",
            "field": m.group(1),
            "required_value": m.group(2),
            "description": (
                f"To populate the XDM target, `{m.group(1)}` MUST equal the literal "
                f"string \"{m.group(2)}\". The MR's `if(X = \"...\", X)` has no else "
                "branch — populating with any other value yields null."
            ),
        })

    # Common typos in regex strings (case-insensitive substrings)
    for typo, correct in COMMON_TYPOS.items():
        if typo in text:
            anomalies.append({
                "type": "regex_typo",
                "severity": "info",
                "found": typo,
                "likely_intended": correct,
                "description": (
                    f"MR contains the substring '{typo}'. Likely a typo for "
                    f"'{correct}'. Honor the existing spelling when constructing "
                    "saturating payloads."
                ),
            })

    return anomalies


def detect_xdm_mutual_exclusives(text: str) -> list[dict[str, Any]]:
    """Detect XDM targets that share a source field but bifurcate via length check.

    Two patterns:
      1. `xdm.X = if(filehash_length = N, FTNTFGTfilehash)` — intermediate var
      2. `xdm.X = if(len(Y) = N, Y)` — inline len() call
    """
    branches: dict[str, list[tuple[int, str]]] = {}

    # Pattern 1: filehash_length intermediate
    RE1 = re.compile(
        r"(xdm(?:\.[A-Za-z_]\w*)+)\s*=\s*if\(\s*filehash_length\s*=\s*(\d+)\s*,\s*([A-Za-z_]\w*)"
    )
    for m in RE1.finditer(text):
        xdm = m.group(1)
        n = int(m.group(2))
        src = m.group(3)
        branches.setdefault(src, []).append((n, xdm))

    # Pattern 2: inline len()
    RE2 = re.compile(
        r"(xdm(?:\.[A-Za-z_]\w*)+)\s*=\s*if\(\s*len\(([A-Za-z_]\w*)\)\s*=\s*(\d+)\s*,"
    )
    for m in RE2.finditer(text):
        xdm = m.group(1)
        src = m.group(2)
        n = int(m.group(3))
        branches.setdefault(src, []).append((n, xdm))

    mutex = []
    for src, items in branches.items():
        if len(items) >= 2:
            items_sorted = sorted(items)
            mutex.append({
                "source_field": src,
                "branches": [
                    {"length_required": n, "xdm_target": x}
                    for n, x in items_sorted
                ],
                "description": (
                    f"`{src}` is branched by len(): one event can satisfy ONE "
                    "branch's length check, never multiple. Two events needed for "
                    "full coverage of all XDM targets in this group."
                ),
            })
    return mutex


def estimate_payload_size(mr_info: dict, pr_info: dict) -> dict[str, Any]:
    """Estimate the CEF payload size for a saturating event.

    Counts distinct CEF SOURCE fields the MR references (not XDM targets;
    one XDM target may have multiple sources via coalesce). Includes
    FTNTFG*-style vendor-prefix extensions counted from the MR's actual
    field references when the PR whitelist has a wildcard.
    """
    # Count unique source fields referenced in MR alter clauses
    source_fields = set()
    for mapping in mr_info.get("xdm_mappings", []):
        s = mapping.get("cef_source", "")
        if s and re.match(r"^[A-Za-z_][A-Za-z_0-9]*$", s):
            source_fields.add(s)
    for group in mr_info.get("coalesce_groups", []):
        for s in group.get("sources", []):
            if re.match(r"^[A-Za-z_][A-Za-z_0-9]*$", s):
                source_fields.add(s)

    # If PR whitelist has wildcards, the FTNTFG* universe could be larger than
    # what we tracked via xdm_mappings — add buffer for that.
    whitelist = pr_info.get("pr_field_whitelist", [])
    has_wildcard = pr_info.get("pr_field_whitelist_has_wildcard", False)

    # Heuristic: if wildcard, vendor-prefix extensions can be 100+ in saturated event.
    # Use the larger of {tracked sources} or {whitelist non-wildcard + 80 guess}.
    if has_wildcard:
        estimated_count = max(len(source_fields), 100)
    else:
        estimated_count = max(len(source_fields), len(whitelist))

    # Average k=v ~25 bytes, CEF header ~80 bytes, syslog framing ~20 bytes
    bytes_est = 100 + estimated_count * 25
    mtu_safe = bytes_est <= 1400
    return {
        "tracked_source_field_count": len(source_fields),
        "estimated_kv_count_for_saturation": estimated_count,
        "estimated_bytes": bytes_est,
        "udp_mtu_safe": mtu_safe,
        "recommended_event_split": not mtu_safe,
        "split_note": (
            None if mtu_safe else
            "Single saturating CEF event would exceed ~1400 bytes (UDP MTU). "
            "Broker may silently truncate the tail. Split into 2+ events "
            "sharing the same marker (e.g. msg = '<marker>') — populate "
            "different XDM categories per event, as FortiGate does with its "
            "two-event split."
        ),
    }


# ============================================================
# Field type refinement
# ============================================================

def refine_field_type(
    field: dict[str, Any],
    mr_info: dict[str, Any],
) -> dict[str, Any]:
    """Apply lesson-driven type refinements + add constraint hints."""
    name = field.get("name", "")
    current_type = field.get("type")
    field_out = dict(field)

    # Generic refinement table
    if name in TYPE_REFINEMENTS:
        rule = TYPE_REFINEMENTS[name]
        if current_type in rule["old_types"]:
            field_out["type"] = rule["new_type"]
            constraints = field_out.setdefault("constraints", [])
            if rule["constraint"] not in constraints:
                constraints.append(rule["constraint"])

    # IPv4 gating — if MR has `if(field ~= "\d.\d.\d.\d", ...)`, set ipv4
    if name in mr_info.get("ipv4_gated_fields", []):
        if current_type in {"string", "string_short", None, "ipv4"}:
            field_out["type"] = "ipv4"
            constraints = field_out.setdefault("constraints", [])
            msg = "MR contains IPv4 regex gate — non-IPv4 values fall through to ipv6 branch."
            if msg not in constraints:
                constraints.append(msg)

    # Label requirement — for cs1-cs6, cn1-cn3, flexString1/2
    if name in mr_info.get("label_pairings", {}):
        label_value = mr_info["label_pairings"][name]
        field_out["label_required"] = label_value
        constraints = field_out.setdefault("constraints", [])
        msg = (
            f"Companion field `{name}Label` must equal \"{label_value}\" — "
            f"MR has `if({name}Label = \"{label_value}\", {name}, null)` "
            f"gate. Otherwise {name} is ignored."
        )
        if msg not in constraints:
            constraints.append(msg)

    return field_out


# ============================================================
# Marker field selection
# ============================================================

def select_marker_field(mr_info: dict[str, Any]) -> dict[str, Any] | None:
    """Pick a CEF field whose XDM target is uniquely identifying.

    Preference order:
      1. cs* with label_required (already gated, easy to filter on XDM side)
      2. msg → xdm.alert.description or xdm.event.description
      3. externalId → xdm.event.id
      4. cefName → xdm.alert.name / xdm.event.description
    """
    mappings = mr_info.get("xdm_mappings", [])
    label_pairings = mr_info.get("label_pairings", {})

    # Tier 1: cs* with label
    for slot, label in label_pairings.items():
        # Find what xdm field cs<slot> maps to
        target = next((x["xdm_target"] for x in mappings
                       if x["cef_source"] in (slot, f"{slot}_") or
                          x["cef_source"].startswith(slot + "_")), None)
        # Actually need to follow intermediate alters — for now just look up direct
        if target:
            return {
                "cef_field": slot,
                "xdm_target": target,
                "label": label,
            }

    # Tier 2: msg
    for x in mappings:
        if x["cef_source"] == "msg":
            return {"cef_field": "msg", "xdm_target": x["xdm_target"]}

    # Tier 3: externalId
    for x in mappings:
        if x["cef_source"] == "externalId":
            return {"cef_field": "externalId", "xdm_target": x["xdm_target"]}

    # Tier 4: cefName
    for x in mappings:
        if x["cef_source"] == "cefName":
            return {"cef_field": "cefName", "xdm_target": x["xdm_target"]}

    return None


# ============================================================
# Existing-bundled-YAML lookup
# ============================================================

def find_bundled_yaml(pack_name: str, dataset: str) -> Path | None:
    """Find the existing bundled YAML for this pack+dataset combo, if any."""
    if not BUNDLED_DS_DIR.exists():
        return None
    for entry in BUNDLED_DS_DIR.iterdir():
        if not entry.is_dir():
            continue
        if dataset in entry.name and pack_name in entry.name:
            ds_yaml = entry / "data_source.yaml"
            if ds_yaml.exists():
                return ds_yaml
    return None


def load_bundled_fields(yaml_path: Path) -> tuple[list[dict], dict]:
    """Return (fields[], top-level-meta) from an existing YAML."""
    try:
        with yaml_path.open("r") as f:
            doc = yaml.safe_load(f) or {}
    except Exception:
        return [], {}
    fields = doc.get("fields", []) or []
    meta = {k: doc[k] for k in
            ("id", "pack_name", "rule_name", "dataset_name", "vendor",
             "product", "description", "categories", "version", "logo",
             "formats", "use_cases")
            if k in doc}
    return fields, meta


# ============================================================
# Main per-pack generator
# ============================================================

def generate_for_pack(category: str, pack_dir: Path) -> dict[str, Any]:
    """Read MR + PR + manifest for one pack; write enriched YAML."""
    manifest_path = pack_dir / "manifest.json"
    if not manifest_path.exists():
        return {"status": "skip", "reason": "no manifest.json"}

    with manifest_path.open() as f:
        manifest = json.load(f)

    dataset = manifest["dataset"]
    pack_name = manifest.get("pack_name", "")
    vendor = manifest.get("vendor", "")
    product = manifest.get("product", "")

    # Parse all modeling rule files
    mr_files = sorted(pack_dir.glob("modeling*.xif"))
    mr_info_merged: dict[str, Any] = {
        "parse_status": "no_mr",
        "target_dataset": dataset,
        "clauses": [],
        "label_pairings": {},
        "xdm_mappings": [],
        "coalesce_groups": [],
        "ipv4_gated_fields": [],
        "filter_cefDeviceProduct": None,
        "filter_cat": None,
        "event_id_ranges": [],
        "event_id_in_set": [],
    }
    for mr_path in mr_files:
        with mr_path.open("r") as f:
            text = f.read()
        info = parse_modeling_rule(text, dataset)
        if info.get("parse_status") == "no_matching_model_block":
            continue
        mr_info_merged["parse_status"] = "ok"
        mr_info_merged["clauses"].extend(info.get("clauses", []))
        mr_info_merged["label_pairings"].update(info.get("label_pairings", {}))
        mr_info_merged["xdm_mappings"].extend(info.get("xdm_mappings", []))
        mr_info_merged["coalesce_groups"].extend(info.get("coalesce_groups", []))
        mr_info_merged["ipv4_gated_fields"].extend(info.get("ipv4_gated_fields", []))
        if info.get("filter_cefDeviceProduct"):
            mr_info_merged["filter_cefDeviceProduct"] = info["filter_cefDeviceProduct"]
        if info.get("filter_cat"):
            mr_info_merged["filter_cat"] = info["filter_cat"]
        mr_info_merged["event_id_ranges"].extend(info.get("event_id_ranges", []))
        mr_info_merged["event_id_in_set"].extend(info.get("event_id_in_set", []))

    # Dedupe ipv4_gated + xdm_mappings + coalesce
    mr_info_merged["ipv4_gated_fields"] = sorted(set(mr_info_merged["ipv4_gated_fields"]))
    seen_x = set()
    deduped = []
    for x in mr_info_merged["xdm_mappings"]:
        key = (x["cef_source"], x["xdm_target"])
        if key not in seen_x:
            seen_x.add(key)
            deduped.append(x)
    mr_info_merged["xdm_mappings"] = deduped

    # Parse parsing rule (optional)
    pr_files = sorted(pack_dir.glob("parsing*.xif"))
    pr_info: dict[str, Any] = {}
    if pr_files:
        with pr_files[0].open("r") as f:
            text = f.read()
        pr_info = parse_parsing_rule(text)

    # Detect MR anomalies + mutex pairs (across all MR files for this pack)
    full_mr_text = ""
    for mr_path in mr_files:
        with mr_path.open("r") as f:
            full_mr_text += f.read() + "\n"
    mr_anomalies = detect_mr_anomalies(full_mr_text)
    xdm_mutex = detect_xdm_mutual_exclusives(full_mr_text)

    # Find existing bundled YAML for fields[] + meta
    bundled_yaml_path = find_bundled_yaml(pack_name, dataset)
    bundled_fields, bundled_meta = ([], {})
    if bundled_yaml_path:
        bundled_fields, bundled_meta = load_bundled_fields(bundled_yaml_path)

    # ============================================================
    # Compose enriched YAML
    # ============================================================
    yaml_doc: dict[str, Any] = {}

    # Identity (carry from bundled if present, else from manifest)
    yaml_doc["schema_version"] = 1
    yaml_doc["id"] = bundled_meta.get("id") or pack_name or dataset
    yaml_doc["pack_name"] = bundled_meta.get("pack_name") or pack_name
    yaml_doc["rule_name"] = bundled_meta.get("rule_name") or pack_name
    yaml_doc["dataset_name"] = dataset
    yaml_doc["vendor"] = bundled_meta.get("vendor") or vendor
    yaml_doc["product"] = bundled_meta.get("product") or product
    if bundled_meta.get("description"):
        yaml_doc["description"] = bundled_meta["description"]
    if bundled_meta.get("categories"):
        yaml_doc["categories"] = bundled_meta["categories"]
    if bundled_meta.get("version"):
        yaml_doc["version"] = bundled_meta["version"]
    yaml_doc["origin"] = "bundle"
    yaml_doc["author"] = "phantom-bundle"
    if bundled_meta.get("logo"):
        yaml_doc["logo"] = bundled_meta["logo"]
    yaml_doc["formats"] = bundled_meta.get("formats") or ["CEF", "SYSLOG"]
    yaml_doc["is_rawlog_only"] = False

    # ============================================================
    # NEW: transport_intent
    # ============================================================
    yaml_doc["transport_intent"] = {
        "category": category,
        "wire_format": "CEF over UDP syslog" if category == "direct_mapped_cef"
                       else "CEF over HTTP collector (typed columns)",
        "broker_destination": "udp:<broker-ip>:514",
        "operator_setup_required": category == "direct_mapped_other",
        "notes": (
            "CEF auto-routes via the header's vendor + product slots — "
            "broker constructs `<lower(vendor)>_<lower(product)>_raw` "
            "dataset name. No operator-side applet config needed."
            if category == "direct_mapped_cef" else
            "Operator must configure XSIAM HTTP collector with matching "
            "vendor/product source tag for events to route correctly."
        ),
    }

    # ============================================================
    # NEW: broker_routing — use the helper for verified-lookup + PR fallback
    # ============================================================
    routing = reverse_engineer_cef_header(
        dataset=dataset,
        pr_vendor=pr_info.get("ingest_vendor"),
        pr_product=pr_info.get("ingest_product"),
        manifest_vendor=vendor,
        manifest_product=product,
    )
    yaml_doc["broker_routing"] = {
        "cef_header_vendor": routing["cef_header_vendor"],
        "cef_header_product": routing["cef_header_product"],
        "resulting_dataset": dataset,
        "source": routing["source"],
        "case_sensitivity_note": (
            "The broker matches the PR's INGEST line (vendor + product) "
            "case-sensitively. Send the CEF header positions 2|3 with the "
            "EXACT casing shown above."
        ),
    }
    if routing.get("verification_status"):
        yaml_doc["broker_routing"]["verification_status"] = routing["verification_status"]
    if routing.get("xdm_saturation"):
        yaml_doc["broker_routing"]["xdm_saturation"] = routing["xdm_saturation"]
    if routing.get("warning"):
        yaml_doc["broker_routing"]["warning"] = routing["warning"]
    if routing.get("dataset_mismatch_note"):
        yaml_doc["broker_routing"]["dataset_mismatch_note"] = routing["dataset_mismatch_note"]

    # ============================================================
    # NEW: pr_timestamp_requirement (lessons from FortiGate)
    # ============================================================
    if pr_info.get("pr_timestamp_field"):
        ts_block: dict[str, Any] = {
            "field": pr_info["pr_timestamp_field"],
            "min_digits": pr_info["pr_timestamp_min_digits"],
            "anchored_end": pr_info["pr_timestamp_anchored_end"],
        }
        # Construct an actionable instruction
        n = pr_info["pr_timestamp_min_digits"]
        anchored = pr_info["pr_timestamp_anchored_end"]
        if n == 9 and anchored:
            ts_block["recommended_value"] = "int(time.time() * 1e9)  # 19-digit nanosecond epoch"
        elif n >= 10:
            ts_block["recommended_value"] = "int(time.time() * 1000)  # 13-digit ms epoch"
        else:
            ts_block["recommended_value"] = f"epoch with at least {n} digits"
        if pr_info.get("pr_timestamp_strip_last_n"):
            ts_block["pr_strips_last_n_digits"] = pr_info["pr_timestamp_strip_last_n"]
            ts_block["note"] = (
                f"PR strips the last {pr_info['pr_timestamp_strip_last_n']} digits "
                "(treating them as fractional seconds) before computing _time. Send "
                "the full unstripped value."
            )
        else:
            ts_block["note"] = (
                f"PR filter requires the field to match `\\d{{{n},}}`. Send a "
                f"{n}+ digit numeric epoch."
            )
        yaml_doc["pr_timestamp_requirement"] = ts_block

    # ============================================================
    # NEW: pr_field_whitelist (lessons from FortiGate)
    # ============================================================
    if pr_info.get("pr_field_whitelist"):
        yaml_doc["pr_field_whitelist"] = {
            "fields": pr_info["pr_field_whitelist"],
            "has_wildcard": pr_info["pr_field_whitelist_has_wildcard"],
            "note": (
                "Only fields in this list survive the PR's `| fields ...` directive. "
                "Anything else is dropped before the MR sees the event. Custom "
                "extensions outside this list will NOT propagate to XDM."
                + (" Wildcards (e.g. `VENDOR*`) accept any field with that prefix."
                   if pr_info["pr_field_whitelist_has_wildcard"] else "")
            ),
        }

    # ============================================================
    # NEW: mr_filter
    # ============================================================
    mr_filter: dict[str, Any] = {}
    if mr_info_merged.get("filter_cefDeviceProduct"):
        mr_filter["cefDeviceProduct"] = mr_info_merged["filter_cefDeviceProduct"]
    if mr_info_merged.get("filter_cat"):
        mr_filter["cat"] = mr_info_merged["filter_cat"]
    if mr_info_merged.get("event_id_ranges"):
        mr_filter["cefDeviceEventClassId_ranges"] = [
            {"low": low, "high": high}
            for low, high in mr_info_merged["event_id_ranges"]
        ]
    if mr_info_merged.get("event_id_in_set"):
        mr_filter["cefDeviceEventClassId_in"] = sorted(set(mr_info_merged["event_id_in_set"]))
    if mr_filter:
        yaml_doc["mr_filter"] = mr_filter

    # ============================================================
    # NEW: mr_anomalies (lessons from FortiGate)
    # ============================================================
    if mr_anomalies:
        yaml_doc["mr_anomalies"] = mr_anomalies
        yaml_doc["mr_anomalies_note"] = (
            "Known bugs/quirks in the MR. Honor existing behavior — these are "
            "what the MR ACTUALLY expects, even if the logic looks inverted. "
            "Don't try to 'fix' them in your payload."
        )

    # ============================================================
    # NEW: xdm_mutually_exclusive (lessons from FortiGate filehash mutex)
    # ============================================================
    if xdm_mutex:
        yaml_doc["xdm_mutually_exclusive"] = xdm_mutex

    # ============================================================
    # NEW: payload_estimate (lessons from FortiGate UDP truncation)
    # ============================================================
    yaml_doc["payload_estimate"] = estimate_payload_size(mr_info_merged, pr_info)

    # ============================================================
    # NEW: label_pairings
    # ============================================================
    if mr_info_merged["label_pairings"]:
        yaml_doc["label_pairings"] = mr_info_merged["label_pairings"]
        yaml_doc["label_pairings_note"] = (
            "For each cs*/cn*/flexString* slot listed, the companion "
            "*Label field must equal the shown string for the MR to "
            "consume the value."
        )

    # ============================================================
    # NEW: xdm_mappings
    # ============================================================
    if mr_info_merged["xdm_mappings"]:
        yaml_doc["xdm_mappings"] = mr_info_merged["xdm_mappings"]
        yaml_doc["xdm_field_count"] = len(set(
            x["xdm_target"] for x in mr_info_merged["xdm_mappings"]
        ))

    # ============================================================
    # NEW: coalesce_groups
    # ============================================================
    if mr_info_merged["coalesce_groups"]:
        yaml_doc["coalesce_groups"] = mr_info_merged["coalesce_groups"]
        yaml_doc["coalesce_groups_note"] = (
            "Operator can populate any source in the group; MR picks "
            "first non-null. Populating multiple is safe — the first "
            "non-null wins."
        )

    # ============================================================
    # NEW: marker_field
    # ============================================================
    marker = select_marker_field(mr_info_merged)
    if marker:
        yaml_doc["marker_field"] = marker
        yaml_doc["marker_field_note"] = (
            "Recommended carrier for E2E saturation testing. Set a "
            "unique value in the CEF field; verify XDM via "
            f"`datamodel dataset = {dataset} | filter "
            f"{marker['xdm_target']} contains \"<marker>\" | "
            "fields xdm.* | limit 1`."
        )

    # ============================================================
    # Fields (refined per lessons)
    # ============================================================
    # Walk source fields from bundled YAML, apply refinements
    seen_field_names = set()
    refined_fields = []
    for f in bundled_fields:
        if not isinstance(f, dict):
            continue
        refined = refine_field_type(f, mr_info_merged)
        refined_fields.append(refined)
        seen_field_names.add(refined.get("name", ""))

    # Also: any MR source-fields that are NOT already in bundled[]
    # — add stubs so the wire-format library is complete
    for x in mr_info_merged["xdm_mappings"]:
        cef_name = x["cef_source"]
        if cef_name in seen_field_names or not cef_name:
            continue
        if cef_name in ("if", "to_integer", "to_string", "coalesce", "null"):
            continue  # skip parse artifacts
        if not re.match(r"^[A-Za-z_][A-Za-z_0-9]*$", cef_name):
            continue
        stub = {
            "name": cef_name,
            "type": "string",
            "description": f"Vendor-emitted field '{cef_name}' (auto-added from MR alter clauses).",
            "auto_added": True,
        }
        refined_fields.append(refine_field_type(stub, mr_info_merged))
        seen_field_names.add(cef_name)

    refined_fields.sort(key=lambda x: (x.get("auto_added", False), x.get("name", "")))
    yaml_doc["fields"] = refined_fields

    # use_cases
    if bundled_meta.get("use_cases"):
        yaml_doc["use_cases"] = bundled_meta["use_cases"]

    # ============================================================
    # Write
    # ============================================================
    out_dir = OUTPUT_DIR / dataset
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "data_source.yaml"
    with out_path.open("w") as f:
        yaml.dump(yaml_doc, f, sort_keys=False, default_flow_style=False,
                  allow_unicode=True, width=88)

    return {
        "status": "ok",
        "dataset": dataset,
        "pack_name": pack_name,
        "category": category,
        "xdm_field_count": yaml_doc.get("xdm_field_count", 0),
        "label_pairings_count": len(mr_info_merged["label_pairings"]),
        "coalesce_groups_count": len(mr_info_merged["coalesce_groups"]),
        "mr_filter_present": bool(yaml_doc.get("mr_filter")),
        "marker_field": (marker or {}).get("cef_field"),
        "fields_count": len(refined_fields),
    }


# ============================================================
# Driver
# ============================================================

def main() -> int:
    if not RULES_DIR.exists():
        sys.stderr.write(f"input dir {RULES_DIR} not found — run organize_rules_by_dataset.py first\n")
        return 1

    # Wipe only the per-pack subdirectories (preserve dotfiles like .gitignore
    # and any other top-level files committed alongside the generator).
    if OUTPUT_DIR.exists():
        for entry in OUTPUT_DIR.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry)
            # Skip dotfiles + _manifest.json (regenerated below) — preserve gitignore
    else:
        OUTPUT_DIR.mkdir(parents=True)

    summary: list[dict[str, Any]] = []
    skipped = {"raw_log_based": 0, "raw_json_based": 0, "other": 0}

    for category_dir in RULES_DIR.iterdir():
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        if category in EXCLUDE_CATEGORIES:
            n = sum(1 for _ in category_dir.iterdir() if _.is_dir())
            skipped[category] = n
            continue
        if category not in INCLUDE_CATEGORIES:
            n = sum(1 for _ in category_dir.iterdir() if _.is_dir())
            skipped["other"] += n
            continue

        for pack_dir in sorted(category_dir.iterdir()):
            if not pack_dir.is_dir():
                continue
            try:
                result = generate_for_pack(category, pack_dir)
                summary.append({"dir": pack_dir.name, **result})
            except Exception as e:
                summary.append({
                    "dir": pack_dir.name,
                    "category": category,
                    "status": "error",
                    "error": f"{type(e).__name__}: {e}",
                })

    # Write summary manifest
    ok = [s for s in summary if s.get("status") == "ok"]
    errors = [s for s in summary if s.get("status") == "error"]

    manifest = {
        "_meta": {
            "generator": "scripts/maintainer/generate_data_source_yamls_from_rules.py",
            "output_dir": str(OUTPUT_DIR.relative_to(REPO_ROOT)),
            "input_dir": str(RULES_DIR.relative_to(REPO_ROOT)),
        },
        "counts": {
            "generated_ok": len(ok),
            "errors": len(errors),
            "skipped_raw_log_based": skipped["raw_log_based"],
            "skipped_raw_json_based": skipped["raw_json_based"],
            "skipped_other": skipped["other"],
        },
        "by_category": {
            "direct_mapped_cef": [s for s in ok if s.get("category") == "direct_mapped_cef"],
            "direct_mapped_other": [s for s in ok if s.get("category") == "direct_mapped_other"],
        },
        "errors": errors,
    }
    with (OUTPUT_DIR / "_manifest.json").open("w") as f:
        json.dump(manifest, f, indent=2, sort_keys=False)

    # Console summary
    print(f"Generated {len(ok)} YAMLs into {OUTPUT_DIR.relative_to(REPO_ROOT)}/")
    print(f"  direct_mapped_cef:   {sum(1 for s in ok if s.get('category')=='direct_mapped_cef')}")
    print(f"  direct_mapped_other: {sum(1 for s in ok if s.get('category')=='direct_mapped_other')}")
    print(f"  errors:              {len(errors)}")
    print(f"  skipped raw_log:     {skipped['raw_log_based']}")
    print(f"  skipped raw_json:    {skipped['raw_json_based']}")

    # Quality highlights
    with_filter = sum(1 for s in ok if s.get("mr_filter_present"))
    with_labels = sum(1 for s in ok if s.get("label_pairings_count", 0) > 0)
    with_marker = sum(1 for s in ok if s.get("marker_field"))
    print()
    print("Quality highlights (of OK YAMLs):")
    print(f"  with mr_filter:        {with_filter}")
    print(f"  with label_pairings:   {with_labels}")
    print(f"  with marker_field:     {with_marker}")
    xdm_field_counts = [s.get("xdm_field_count", 0) for s in ok if s.get("xdm_field_count")]
    if xdm_field_counts:
        print(f"  XDM fields per pack:   min={min(xdm_field_counts)}  median={sorted(xdm_field_counts)[len(xdm_field_counts)//2]}  max={max(xdm_field_counts)}")

    if errors:
        print()
        print("Errors (first 5):")
        for e in errors[:5]:
            print(f"  {e['dir']}: {e.get('error', '?')}")

    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
