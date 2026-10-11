#!/usr/bin/env python3
"""
scrub_descriptions_examples.py — one-shot consistency pass across the
342 bundled data_source.yaml files.

For every field entry, this script enforces a vendor-neutral 2-sentence
description shape:

    <vendor concept (semantic role)>. <wire-shape constraint per type>.

and populates an example value when one is missing. The wire-shape
sentence is what teaches Phantom (and any downstream modeling rule —
Cortex, Splunk, Elastic) what form the value must take so parsers
succeed. The vendor concept stays as-is when the existing description
already provides it; otherwise the script infers from the field name.

Hard rule: NO mention of `xdm.*`, "Drives xdm", "XDM", or modeling-rule
jargon in any description. The data_source.yaml describes the wire
format the vendor emits — neutral to whichever SIEM consumes it.

Per scripts/CLAUDE.md, this is a one-shot research migration. Output
is the committed YAML. Customer runtime never invokes it.

Usage
-----
    python3 scripts/scrub_descriptions_examples.py             # all packs
    python3 scripts/scrub_descriptions_examples.py --pack <id> # one pack
    python3 scripts/scrub_descriptions_examples.py --dry-run   # no writes
    python3 scripts/scrub_descriptions_examples.py --audit     # report only
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_SOURCES_DIR = REPO_ROOT / "bundles/spark/data-sources"


# ─── Wire-shape templates per type ──────────────────────────────────

# Second sentence of every description. Vendor-neutral, format-explicit.
# These tell Phantom (and any modeling rule) what shape the value must
# take so parsers succeed.
WIRE_SHAPE: dict[str, str] = {
    'string': "Free-form text; may contain whitespace and punctuation.",
    'string_short': "Short opaque token, typically without whitespace; max ~64 chars.",
    'string_long': "Free-form text; may span multiple lines or contain large payloads.",
    'ipv4': "Dotted-quad IPv4 literal (e.g., 192.0.2.45); no port suffix, no surrounding brackets or quotes.",
    'ipv6': "Colon-separated hexadecimal IPv6 literal (RFC 4291); no zone suffix, no surrounding brackets.",
    'integer': "Signed decimal integer; bare digits, optional leading minus.",
    'integer_port': "Unsigned integer 0-65535 representing a TCP/UDP port; bare digits, no quotes.",
    'integer_byte_count': "Unsigned decimal byte count; bare digits, no unit suffix.",
    'float': "Decimal number with optional fractional part; bare digits with optional minus and decimal point.",
    'boolean': "Literal 'true' or 'false' (case-insensitive); not '1'/'0'.",
    'datetime': "ISO-8601 timestamp with timezone (e.g., 2026-05-26T14:23:01Z).",
    'timestamp_ms': "Unsigned epoch milliseconds since 1970-01-01 UTC; bare digits.",
    'email': "RFC 5322 'local@domain' address; one address only — use an array field for multiple addresses.",
    'host': "Hostname or fully-qualified domain name (RFC 1035 dotted labels); no protocol prefix.",
    'url': "Full URL with scheme (http/https/ftp); percent-encoded if it contains non-ASCII characters.",
    'domain': "Bare DNS domain name; no scheme, no path, no port.",
    'mac': "MAC address in colon-separated lowercase hex (aa:bb:cc:dd:ee:ff).",
    'hash_md5': "32-character lowercase hex MD5 digest.",
    'hash_sha1': "40-character lowercase hex SHA-1 digest.",
    'hash_sha256': "64-character lowercase hex SHA-256 digest.",
    'user': "Account name as the vendor reports it — login name, UPN, or sAMAccountName depending on the source; no domain prefix unless the vendor emits one.",
    'country_code': "ISO 3166-1 alpha-2 uppercase country code (e.g., US, DE, JP).",
    'file_path': "Absolute filesystem path; vendor-native separator (forward slash on POSIX, backslash on Windows).",
}


# ─── Synthetic-but-realistic examples per type ──────────────────────

# RFC-reserved or documentation-safe placeholder values. Used when the
# existing entry has no example. For enums + composite json fields, see
# the type-specific synthesis below.
SYNTHETIC_EXAMPLES: dict[str, str] = {
    'string': 'example_value',
    'string_short': 'token',
    'string_long': 'Free-form vendor-emitted message describing the event.',
    'ipv4': '192.0.2.45',
    'ipv6': '2001:db8::1',
    'integer': '42',
    'integer_port': '443',
    'integer_byte_count': '1024',
    'float': '3.14',
    'boolean': 'true',
    'datetime': '2026-05-26T14:23:01Z',
    'timestamp_ms': '1748263381000',
    'email': 'user@example.com',
    'host': 'host01.example.com',
    'url': 'https://example.com/path?q=1',
    'domain': 'example.com',
    'mac': 'aa:bb:cc:dd:ee:ff',
    'hash_md5': '5d41402abc4b2a76b9719d911017c592',
    'hash_sha1': 'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d',
    'hash_sha256': '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824',
    'user': 'jdoe',
    'country_code': 'US',
    'file_path': '/var/log/app.log',
    'regex': 'pattern-match-sample',
}


# ─── XDM-leakage scrubbing ──────────────────────────────────────────

# Patterns that mark a description as XDM-leaky (modeling-rule jargon
# leaking into vendor-neutral spec). All matches get removed.
XDM_LEAK_PATTERNS = [
    # Entire phrases anchored on "Maps to xdm.X" / "Mapped to xdm.X" /
    # "Drives xdm.X" / "Also drives xdm.X" — including a chained list
    # "xdm.A, xdm.B, xdm.C" up to the next period. Strip the full phrase
    # so no "Maps to." stub is left behind.
    re.compile(
        r'\s*(?:Also drives|Drives|Maps?(?:ped)?\s+to|Mapped\s+to|See\s+leaf\s+entries?\s+\S+\s+for\s+per-path\s+type\s+metadata|See\s+per-leaf)'
        r'\s+(?:xdm|XDM)\.[a-zA-Z0-9_.,\s]*\.?',
        re.IGNORECASE,
    ),
    # Stand-alone "Maps to <bare-target>." with no xdm prefix (defensive)
    re.compile(r'\s*(?:Maps to|Mapped to|Drives)\s*\.\s*', re.IGNORECASE),
    # "See leaf entries field.* for per-path type metadata." stub
    re.compile(
        r'\s*See\s+leaf\s+entries?\s+[\w.*]+\s+for\s+per-path\s+type\s+metadata\.?\s*',
        re.IGNORECASE,
    ),
    # "Leaf path under `field`. ", "Leaf under `field`. "
    re.compile(r'\s*Leaf\s+(?:path\s+)?under\s+`[^`]+`\.?\s*', re.IGNORECASE),
    # "Composite object …", "Array of objects …" stub markers
    re.compile(r'\s*Composite\s+object\.?\s*', re.IGNORECASE),
    re.compile(r'\s*Array\s+of\s+objects\.?\s*', re.IGNORECASE),
    # "TODO: write description." / "TODO: …"
    re.compile(r'\s*TODO:[^.]*\.?\s*', re.IGNORECASE),
    # Bare "xdm.X" or "xdm.X.Y.Z" tokens (catch-all, run LAST so the
    # anchored phrases above can consume their context first).
    re.compile(r'\b(?:xdm|XDM)\.[a-zA-Z0-9_.]+\b'),
    # "XDM_CONST.IP_PROTOCOL_*" etc. — Cortex constants leaking from
    # modeling-rule text.
    re.compile(r'\b(?:XDM_CONST|XDM)\.[A-Z][A-Z0-9_]*(?:\*)?\b'),
    # "mapped to XDM_CONST.X constants" / "mapped to XDM_CONST.X"
    # phrases that may dangle after constant removal.
    re.compile(r'\s*(?:—\s*)?mapped\s+to(?:\s+constants)?\b', re.IGNORECASE),
    # "XDM target", "XDM mapping", "XDM field" references
    re.compile(r'\bXDM\s+(?:target|targets|mapping|mappings|field|fields)\b', re.IGNORECASE),
    # Parenthesized arrow fragments left stranded by XDM-target removal,
    # e.g. "(→ )", "(→ /ipv6)", "(→ and )", "(... → )". Strip the
    # entire parenthesis pair if `→` appears and the content after the
    # arrow is empty or punctuation-only.
    re.compile(r'\s*\([^()]*→[^()]*\)'),
    # Bare "→ <leftover>" (no parens) at sentence boundaries.
    re.compile(r'\s*→\s*[^.,]*(?=[.,]|$)'),
]


def scrub_xdm(text: str) -> str:
    """Remove every XDM/modeling-rule reference. Returns cleaned text
    (may be empty)."""
    if not text:
        return ''
    out = text
    for pat in XDM_LEAK_PATTERNS:
        out = pat.sub(' ', out)
    out = re.sub(r'\s+', ' ', out).strip()
    out = re.sub(r'\s+([.,;:])', r'\1', out)
    # Collapse leftover trailing punctuation/whitespace
    out = out.rstrip(' ,;:').strip()
    return out


# ─── Vendor-concept inference from field name ───────────────────────

# Maps name prefixes/suffixes to a vendor-concept sentence fragment.
# Used when the existing description is missing or too thin (< 20 chars
# after XDM scrub).
NAME_HEURISTICS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'^(src|source)[_.]?(ip|addr|address)', re.I), "Source address of the connection initiator"),
    (re.compile(r'^(dst|dest|destination)[_.]?(ip|addr|address)', re.I), "Destination address of the connection target"),
    (re.compile(r'^(src|source)[_.]?(host|hostname|fqdn)', re.I), "Source hostname or FQDN reported by the vendor"),
    (re.compile(r'^(dst|dest|destination)[_.]?(host|hostname|fqdn)', re.I), "Destination hostname or FQDN reported by the vendor"),
    (re.compile(r'^(src|source)[_.]?port', re.I), "Source TCP/UDP port"),
    (re.compile(r'^(dst|dest|destination)[_.]?port', re.I), "Destination TCP/UDP port"),
    (re.compile(r'^(src|source)[_.]?(user|username|name)', re.I), "Source/initiating user account name"),
    (re.compile(r'^(dst|dest|destination|target)[_.]?(user|username|name)', re.I), "Destination/target user account name"),
    (re.compile(r'^(src|source)[_.]?mac', re.I), "Source MAC address"),
    (re.compile(r'^(dst|dest|destination)[_.]?mac', re.I), "Destination MAC address"),
    (re.compile(r'(event|log)[_.]?id$', re.I), "Unique identifier for this event as assigned by the vendor"),
    (re.compile(r'(event|log)[_.]?type$', re.I), "Event type or category as the vendor classifies it"),
    (re.compile(r'(event|log)[_.]?(time|ts|timestamp|date)', re.I), "Event timestamp as reported by the vendor"),
    (re.compile(r'^action$', re.I), "Action taken by the vendor's enforcement engine"),
    (re.compile(r'^outcome$', re.I), "Event outcome reported by the vendor"),
    (re.compile(r'^severity$', re.I), "Event severity as classified by the vendor"),
    (re.compile(r'^message$|^msg$', re.I), "Human-readable event message"),
    (re.compile(r'^user(_?id|name)?$', re.I), "User account associated with the event"),
    (re.compile(r'^proto(col)?$', re.I), "Network protocol name or numeric IANA assignment"),
    (re.compile(r'^method$', re.I), "Operation method as reported by the vendor (e.g., HTTP verb, RPC name)"),
    (re.compile(r'^status(_?code)?$', re.I), "Status code returned by the vendor"),
    (re.compile(r'(file|process)[_.]?path', re.I), "Filesystem path reported by the vendor"),
    (re.compile(r'(file|process)[_.]?name', re.I), "File or process name reported by the vendor"),
    (re.compile(r'^_raw_log$', re.I), "Raw log line as the vendor emits it before any parsing or normalization"),
    (re.compile(r'\.md5$|^md5$', re.I), "MD5 digest as reported by the vendor"),
    (re.compile(r'\.sha1$|^sha1$', re.I), "SHA-1 digest as reported by the vendor"),
    (re.compile(r'\.sha256$|^sha256$', re.I), "SHA-256 digest as reported by the vendor"),
]


def infer_concept(name: str) -> str:
    """Guess a vendor-concept sentence for a field whose existing
    description is empty or unusable. Falls back to a generic
    name-based hint."""
    for pat, concept in NAME_HEURISTICS:
        if pat.search(name):
            return concept
    # Generic fallback: humanize the field name
    pretty = name.replace('_', ' ').replace('.', ' › ')
    pretty = pretty[0].upper() + pretty[1:] if pretty else ''
    return f"Vendor-emitted field '{pretty}'"


# ─── Description merger ─────────────────────────────────────────────

def _sentence_one(existing: str, name: str) -> str:
    """Return the vendor-concept sentence (first half of every
    description). Preserves any non-empty existing content after XDM
    scrub; falls back to name-based inference only when the existing
    description is empty or was 100% XDM jargon."""
    cleaned = scrub_xdm(existing)
    if cleaned:
        # Preserve verbatim — operator-faithful content stays as-is.
        if not cleaned.endswith('.'):
            cleaned += '.'
        return cleaned
    # Empty after scrub → infer from name.
    return infer_concept(name) + '.'


def _wire_shape_sentence(field_type: str, *, enum_values=None,
                         regex_pattern=None, json_keys=None,
                         is_array=False, parent_field=None) -> str:
    """Return the wire-shape sentence (second half) for a given type."""
    if enum_values:
        # Full enumeration per operator directive
        joined = ', '.join(str(v) for v in enum_values)
        return f"One of: {joined} (case-sensitive)."
    if regex_pattern:
        return f"Must match the pattern: {regex_pattern}."
    if field_type == 'json':
        if is_array and json_keys:
            return (f"JSON array; each element is an object with keys: "
                    f"{', '.join(json_keys)} (each key defined as a "
                    f"dotted-path leaf below).")
        if is_array:
            return ("JSON array; each element is an object — see the "
                    "dotted-path leaves below for element shape.")
        if json_keys and len(json_keys) <= 40:
            return (f"JSON object with keys: {', '.join(json_keys)} "
                    f"(each key defined as a dotted-path leaf below).")
        if json_keys:
            return (f"JSON object with {len(json_keys)} keys; full key "
                    f"list defined as dotted-path leaves below.")
        return ("JSON object or array; structured payload — see dotted-"
                "path leaves below for full shape.")
    shape = WIRE_SHAPE.get(field_type, "Free-form vendor-emitted value.")
    if parent_field:
        # Dotted-path leaf — annotate parent
        shape = (f"Leaf of the '{parent_field}' composite. " + shape)
    return shape


def merge_description(existing: str, name: str, field_type: str,
                      enum_values=None, regex_pattern=None,
                      json_keys=None, is_array=False,
                      parent_field=None) -> str:
    """Produce the final 2-sentence description for a field."""
    s1 = _sentence_one(existing, name)
    s2 = _wire_shape_sentence(field_type, enum_values=enum_values,
                              regex_pattern=regex_pattern,
                              json_keys=json_keys, is_array=is_array,
                              parent_field=parent_field)
    return f"{s1} {s2}"


# ─── Example synthesizer ────────────────────────────────────────────

def synth_example(field_type: str, name: str, *, enum_values=None,
                  json_keys=None, is_array=False,
                  existing_example=None) -> str:
    """Return a synthetic-but-realistic example value.

    Preserves the existing example if it's a real vendor-shape value
    (anything containing digits, dots, colons, slashes, JSON braces, …
    — i.e. richer than a placeholder word)."""
    if existing_example is not None and existing_example not in ('', 'sample', 'null', None):
        ex_str = str(existing_example)
        # Looks like a real value? Preserve.
        if re.search(r'[\d.:/@\-{}\[\]]', ex_str):
            return ex_str
        # Short non-rich string — preserve only if explicitly meaningful
        if len(ex_str) > 3 and ex_str != 'sample':
            return ex_str
    if enum_values:
        return str(enum_values[0])
    if field_type == 'json':
        if is_array and json_keys:
            inner = '{' + ','.join(f'"{k}":"…"' for k in json_keys[:3]) + '}'
            return f'[{inner}]'
        if is_array:
            return '[]'
        if json_keys:
            inner = ','.join(f'"{k}":"…"' for k in json_keys[:5])
            return '{' + inner + '}'
        return '{}'
    return SYNTHETIC_EXAMPLES.get(field_type, 'example_value')


# ─── Composite-leaf discovery ───────────────────────────────────────

# Given a flat list of field entries, group dotted-path leaves under
# their parent's wire field. Returns:
#   parent_to_keys: {parent_name: [leaf_key, ...]}
#   parent_is_array: {parent_name: bool}
#   name_to_parent: {leaf_name: parent_name}
def index_composites(fields: list[dict]) -> tuple[dict, dict, dict]:
    parent_to_keys: dict = {}
    parent_is_array: dict = {}
    name_to_parent: dict = {}
    for f in fields:
        if not isinstance(f, dict):
            continue
        name = f.get('name', '')
        if '.' not in name and '[]' not in name:
            continue  # not a leaf
        # The parent is everything up to the first '.' or '['
        parent = re.split(r'[.\[]', name, maxsplit=1)[0]
        # Leaf key (the part after parent.)
        rest = name[len(parent):]
        rest = rest.lstrip('.').replace('[]', '')
        key = rest.split('.')[0] if rest else rest
        if not key:
            continue
        parent_to_keys.setdefault(parent, [])
        if key not in parent_to_keys[parent]:
            parent_to_keys[parent].append(key)
        if '[]' in name:
            parent_is_array[parent] = True
        name_to_parent[name] = parent
    return parent_to_keys, parent_is_array, name_to_parent


# ─── Per-pack scrub ─────────────────────────────────────────────────

def scrub_pack(yaml_path: Path) -> tuple[int, int, list]:
    """Scrub one pack's data_source.yaml in place.

    Returns (fields_total, fields_mutated, sample_mutations).
    sample_mutations is a list of (name, old_desc, new_desc, old_ex,
    new_ex) for the first few mutated fields — used for audit
    reporting.
    """
    try:
        data = yaml.safe_load(yaml_path.read_text())
    except Exception as e:
        return 0, 0, [(yaml_path.name, str(e), '', '', '')]
    if not data:
        return 0, 0, []

    fields = data.get('fields') or []
    parent_to_keys, parent_is_array, name_to_parent = index_composites(fields)

    mutated = 0
    samples = []
    for f in fields:
        if not isinstance(f, dict):
            continue
        name = f.get('name', '')
        ftype = f.get('type', 'string')
        # Intrinsic-property forces
        enum_values = f.get('enum_values')
        regex_pattern = f.get('regex_pattern')
        if enum_values:
            ftype = 'enum'
            f['type'] = 'enum'
        elif regex_pattern:
            ftype = 'regex'
            f['type'] = 'regex'

        # Composite-leaf annotation
        json_keys = parent_to_keys.get(name) if ftype == 'json' else None
        is_array = bool(parent_is_array.get(name)) if ftype == 'json' else False
        parent_field = name_to_parent.get(name)

        old_desc = f.get('description', '')
        old_ex = f.get('example')

        new_desc = merge_description(
            old_desc, name, ftype,
            enum_values=enum_values,
            regex_pattern=regex_pattern,
            json_keys=json_keys,
            is_array=is_array,
            parent_field=parent_field,
        )
        new_ex = synth_example(
            ftype, name,
            enum_values=enum_values,
            json_keys=json_keys,
            is_array=is_array,
            existing_example=old_ex,
        )

        changed = (new_desc != old_desc) or (new_ex != old_ex)
        if changed:
            mutated += 1
            if len(samples) < 3:
                samples.append((name, old_desc, new_desc, old_ex, new_ex))
        f['description'] = new_desc
        f['example'] = new_ex

    data['fields'] = fields
    yaml_path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))
    return len(fields), mutated, samples


# ─── Audit mode ─────────────────────────────────────────────────────

def audit() -> dict:
    """Walk every pack, report what would change without writing."""
    counters = {
        'packs': 0,
        'fields': 0,
        'desc_xdm_leak': 0,
        'desc_short': 0,        # < 30 chars
        'desc_empty': 0,
        'example_missing': 0,
        'example_sample': 0,
    }
    XDM_RE = re.compile(r'(?i)\bxdm\.|\bxDM target|Drives xdm|Leaf path under|TODO:|Composite object|Array of objects')
    for d in sorted(DATA_SOURCES_DIR.iterdir()):
        if not d.is_dir():
            continue
        y = d / 'data_source.yaml'
        if not y.exists():
            continue
        try:
            data = yaml.safe_load(y.read_text())
        except Exception:
            continue
        if not data:
            continue
        counters['packs'] += 1
        for f in (data.get('fields') or []):
            if not isinstance(f, dict):
                continue
            counters['fields'] += 1
            desc = (f.get('description') or '').strip()
            ex = f.get('example')
            if XDM_RE.search(desc):
                counters['desc_xdm_leak'] += 1
            if not desc:
                counters['desc_empty'] += 1
            elif len(desc) < 30:
                counters['desc_short'] += 1
            if ex is None or ex == '':
                counters['example_missing'] += 1
            if ex == 'sample':
                counters['example_sample'] += 1
    return counters


# ─── Main ───────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pack', help='Process a single pack id')
    p.add_argument('--dry-run', action='store_true', help='No writes; show stats')
    p.add_argument('--audit', action='store_true', help='Report scope; no writes')
    p.add_argument('--show-samples', type=int, default=0,
                   help='Print N before/after samples after scrubbing')
    args = p.parse_args()

    if args.audit:
        c = audit()
        print(f"Packs: {c['packs']}  Fields: {c['fields']}")
        print(f"  XDM-leaky descriptions    : {c['desc_xdm_leak']}")
        print(f"  Empty descriptions        : {c['desc_empty']}")
        print(f"  Descriptions < 30 chars   : {c['desc_short']}")
        print(f"  Missing/empty examples    : {c['example_missing']}")
        print(f"  Examples == 'sample'      : {c['example_sample']}")
        return

    if args.pack:
        targets = [DATA_SOURCES_DIR / args.pack]
    else:
        targets = sorted(d for d in DATA_SOURCES_DIR.iterdir() if d.is_dir())

    total_fields = total_mutated = 0
    sample_buf = []
    for d in targets:
        y = d / 'data_source.yaml'
        if not y.exists():
            continue
        if args.dry_run:
            # Round-trip without writing
            data = yaml.safe_load(y.read_text())
            saved = y.read_text()
            n, m, samples = scrub_pack(y)
            y.write_text(saved)  # restore
        else:
            n, m, samples = scrub_pack(y)
        total_fields += n
        total_mutated += m
        if args.show_samples and len(sample_buf) < args.show_samples:
            sample_buf.extend([(d.name, *s) for s in samples])

    print(f"Scrubbed: {total_mutated}/{total_fields} fields across "
          f"{len(targets)} packs"
          + (" (dry-run)" if args.dry_run else ""))

    for pack, name, od, nd, oe, ne in sample_buf[:args.show_samples]:
        print(f"\n  [{pack}] {name}")
        print(f"    OLD desc: {od!r}")
        print(f"    NEW desc: {nd!r}")
        print(f"    OLD ex  : {oe!r}")
        print(f"    NEW ex  : {ne!r}")


if __name__ == '__main__':
    main()
