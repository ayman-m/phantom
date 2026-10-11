#!/usr/bin/env python3
"""polish_long_tail_fields.py — one-shot mass polish of generic stubs.

Many fields across long-tail packs carry the generic `Vendor-emitted field 'X'` description. Those
fields' names follow well-known patterns from CEF / common security
log shapes (src/dst, user/host/port, action/severity/category, …).

This script applies a name-pattern semantic library to those fields:
infers a vendor-faithful concept from the name, layers the wire-shape
sentence per type, and generates a type-aware example.

Per scripts/CLAUDE.md: one-shot research migration; runtime never
invokes this; output is the committed YAMLs.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
import yaml
from jsonschema import Draft7Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE = REPO_ROOT / 'bundles/spark/data-sources'
SCHEMA = json.loads((BASE / 'data_source.schema.json').read_text())
V = Draft7Validator(SCHEMA)

STUB_RE = re.compile(r"^Vendor-emitted field '[^']+'")

# ─── Wire-shape sentence per type ────────────────────────────────────
WIRE = {
    'string': 'Free-form text; may contain whitespace and punctuation.',
    'string_short': 'Short opaque token, typically without whitespace; max ~64 chars.',
    'string_long': 'Free-form text; may span multiple lines or contain large payloads.',
    'ipv4': 'Dotted-quad IPv4 literal (e.g., 192.0.2.45); no port suffix, no surrounding brackets or quotes.',
    'ipv6': 'Colon-separated hexadecimal IPv6 literal (RFC 4291); no zone suffix, no surrounding brackets.',
    'integer': 'Signed decimal integer; bare digits, optional leading minus.',
    'integer_port': 'Unsigned integer 0-65535 representing a TCP/UDP port; bare digits, no quotes.',
    'integer_byte_count': 'Unsigned decimal byte count; bare digits, no unit suffix.',
    'float': 'Decimal number with optional fractional part.',
    'boolean': "Literal 'true' or 'false' (case-insensitive); not '1'/'0'.",
    'datetime': 'ISO-8601 timestamp with timezone (e.g., 2026-05-26T14:23:01Z).',
    'timestamp_ms': 'Unsigned epoch milliseconds since 1970-01-01 UTC; bare digits.',
    'email': 'RFC 5322 `local@domain`; one address only.',
    'host': 'Hostname or fully-qualified domain name (RFC 1035 dotted labels); no protocol prefix.',
    'url': 'Full URL with scheme (http/https/ftp); percent-encoded if non-ASCII.',
    'domain': 'Bare DNS domain name; no scheme, no path, no port.',
    'mac': 'MAC address in colon-separated lowercase hex (aa:bb:cc:dd:ee:ff).',
    'hash_md5': '32-character lowercase hex MD5 digest.',
    'hash_sha1': '40-character lowercase hex SHA-1 digest.',
    'hash_sha256': '64-character lowercase hex SHA-256 digest.',
    'user': 'Account name as the vendor reports it — login name, UPN, or sAMAccountName; no domain prefix unless vendor emits one.',
    'country_code': 'ISO 3166-1 alpha-2 uppercase country code (e.g., US, DE, JP).',
    'file_path': 'Absolute filesystem path; vendor-native separator.',
    'json': 'JSON object or array; structured payload — see dotted-path leaves below.',
}

# Type-aware example synthesis
EX = {
    'ipv4': '192.0.2.45', 'ipv6': '2001:db8::1',
    'integer_port': '443', 'integer': '42', 'integer_byte_count': '1024',
    'float': '3.14', 'boolean': 'true',
    'datetime': '2026-05-26T14:23:01Z', 'timestamp_ms': '1748263381000',
    'email': 'user@example.com', 'host': 'host01.example.com',
    'url': 'https://example.com/path?q=1', 'domain': 'example.com',
    'mac': 'aa:bb:cc:dd:ee:ff',
    'hash_md5': '5d41402abc4b2a76b9719d911017c592',
    'hash_sha1': 'aaf4c61ddcc5e8a2dabede0f3b482cd9aea9434d',
    'hash_sha256': '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824',
    'user': 'jdoe', 'country_code': 'US', 'file_path': '/var/log/app.log',
}

# ─── Name-pattern semantic library ───────────────────────────────────
# Ordered: more-specific patterns first. Each entry: (regex, concept_template, type)
# `concept_template` may use {vendor} (vendor name) + {name} (field name).
PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # CEF-standard fields (ArcSight schema vocabulary)
    (re.compile(r'^cefseverity$', re.I),       "CEF severity score (0-10) as classified by {vendor}", 'integer'),
    (re.compile(r'^cefdeviceeventclassid$', re.I), "CEF device-event class ID — vendor-specific event-type identifier", 'string_short'),
    (re.compile(r'^cefname$', re.I),           "CEF event name — short human-readable label for the event class", 'string_short'),
    (re.compile(r'^cefdeviceversion$', re.I),  "CEF device-version field — version of the {vendor} product emitting this event", 'string_short'),
    (re.compile(r'^cefdeviceproduct$', re.I),  "CEF device-product field — product name as registered by {vendor}", 'string_short'),
    (re.compile(r'^cefdevicevendor$', re.I),   "CEF device-vendor field — vendor name", 'string_short'),
    (re.compile(r'^cefversion$', re.I),        "CEF specification version — typically `0` for CEF 1.x", 'string_short'),
    (re.compile(r'^suser$', re.I),             "CEF source user — username of the actor initiating the event", 'user'),
    (re.compile(r'^duser$', re.I),             "CEF destination user — username of the target/recipient", 'user'),
    (re.compile(r'^shost$', re.I),             "CEF source host — hostname or FQDN of the source endpoint", 'host'),
    (re.compile(r'^dhost$', re.I),             "CEF destination host — hostname or FQDN of the target endpoint", 'host'),
    (re.compile(r'^spt$', re.I),               "CEF source port — TCP/UDP port on the source side", 'integer_port'),
    (re.compile(r'^dpt$', re.I),               "CEF destination port — TCP/UDP port on the target side", 'integer_port'),
    (re.compile(r'^src$', re.I),               "CEF source IP — IPv4/IPv6 address of the source endpoint", 'string'),
    (re.compile(r'^dst$', re.I),               "CEF destination IP — IPv4/IPv6 address of the target endpoint", 'string'),
    (re.compile(r'^smac$', re.I),              "CEF source MAC address", 'mac'),
    (re.compile(r'^dmac$', re.I),              "CEF destination MAC address", 'mac'),
    (re.compile(r'^act$', re.I),               "CEF action — what {vendor} did with the event (allow/block/quarantine/etc.)", 'string_short'),
    (re.compile(r'^msg$', re.I),               "Human-readable event message emitted by {vendor}", 'string_long'),
    (re.compile(r'^request$', re.I),           "HTTP request line or full request payload as captured by {vendor}", 'string'),
    (re.compile(r'^requestmethod$', re.I),     "HTTP request method (GET/POST/PUT/DELETE/etc.)", 'string_short'),
    (re.compile(r'^cs_user_agent$|^useragent$|^user_agent$', re.I), "Client User-Agent header value as received by {vendor}", 'string_long'),
    # Generic identity fields
    (re.compile(r'^(.*?_)?(uuid|guid|event_?id|alert_?id|incident_?id|log_?id|transaction_?id|trace_?id|correlation_?id|session_?id|request_?id|token_?id)$', re.I),
                                               "Unique identifier — assigned by {vendor} per event", 'string_short'),
    (re.compile(r'^id$|\.id$|_id$', re.I),     "Opaque identifier emitted by {vendor}", 'string_short'),
    (re.compile(r'^(host)?name$|\.name$|_name$', re.I), "Human-readable name as displayed by {vendor}", 'string'),
    (re.compile(r'^(event_)?type$|\.type$|_type$', re.I), "Type/category classifier emitted by {vendor}", 'string_short'),
    (re.compile(r'^category$|\.category$|_category$', re.I), "{vendor}'s category classifier for the event", 'string_short'),
    (re.compile(r'^subcategory$|_subcategory$', re.I), "{vendor}'s subcategory classifier (refines `category`)", 'string_short'),
    # Network identity
    (re.compile(r'(src|source)[_.]?(ip|address|addr)$', re.I),         "Source IPv4/IPv6 address of the initiator", 'string'),
    (re.compile(r'(dst|dest|destination)[_.]?(ip|address|addr)$', re.I), "Destination IPv4/IPv6 address of the target", 'string'),
    (re.compile(r'^ip(_?address|addr)?$|^ipaddress$', re.I),  "IPv4/IPv6 address — vendor-emitted, no version split", 'string'),
    (re.compile(r'(src|source)[_.]?port$', re.I),     "TCP/UDP source port", 'integer_port'),
    (re.compile(r'(dst|dest|destination)[_.]?port$', re.I), "TCP/UDP destination port", 'integer_port'),
    (re.compile(r'^port$|\.port$|_port$', re.I),      "TCP/UDP port", 'integer_port'),
    (re.compile(r'^proto(col)?$', re.I),              "Network protocol name or numeric IANA assignment (tcp/udp/icmp)", 'string_short'),
    (re.compile(r'(src|source)[_.]?(host|hostname|fqdn)$', re.I), "Source hostname or FQDN", 'host'),
    (re.compile(r'(dst|dest|destination)[_.]?(host|hostname|fqdn)$', re.I), "Destination hostname or FQDN", 'host'),
    (re.compile(r'(\.hostname|_hostname|^hostname|^host$)$', re.I), "Hostname or FQDN as reported by {vendor}", 'host'),
    (re.compile(r'(\.domain|_domain|^domain$)$', re.I), "DNS domain reported by {vendor} — bare domain, no scheme/path/port", 'domain'),
    (re.compile(r'(\.fqdn|_fqdn|^fqdn$)$', re.I), "Fully-qualified domain name (dotted labels per RFC 1035)", 'host'),
    (re.compile(r'(\.mac|_mac|^mac$)$', re.I),  "MAC address (colon-separated lowercase hex)", 'mac'),
    # User identity
    (re.compile(r'(\.username|_username|^username$)', re.I), "Account name (login name or UPN) of the user", 'user'),
    (re.compile(r'(src|source)[_.]?user$', re.I), "Source user — actor initiating the event", 'user'),
    (re.compile(r'(dst|target|destination)[_.]?user$', re.I), "Destination/target user — recipient or affected account", 'user'),
    (re.compile(r'^user$|^uid$|\.user$|_user$', re.I), "User account associated with the event", 'user'),
    (re.compile(r'(\.email|_email|^email$)$', re.I), "Email address — RFC 5322 `local@domain`", 'email'),
    # Hashes
    (re.compile(r'(\.md5|_md5|^md5$)$', re.I),     "MD5 digest of the artifact", 'hash_md5'),
    (re.compile(r'(\.sha1|_sha1|^sha1$)$', re.I),   "SHA-1 digest of the artifact", 'hash_sha1'),
    (re.compile(r'(\.sha256|_sha256|^sha256$)$', re.I), "SHA-256 digest of the artifact", 'hash_sha256'),
    # File/process
    (re.compile(r'(\.file_?path|_file_?path|^file_?path$|^path$|\.path$|_path$)', re.I), "Filesystem path", 'file_path'),
    (re.compile(r'(\.file_?name|_file_?name|^file_?name$|^filename$)', re.I), "File name (basename without directory)", 'string'),
    (re.compile(r'(\.process_?name|_process_?name|^process_?name$|^procname$)', re.I), "Process name (executable basename)", 'string'),
    (re.compile(r'(\.process_?id|_process_?id|^pid$)', re.I), "Operating-system process identifier", 'integer'),
    (re.compile(r'(\.command_?line|_command_?line|^command_?line$|^cmdline$)', re.I), "Process command-line as launched (executable + arguments)", 'string_long'),
    # Time
    (re.compile(r'\.timestamp$|_timestamp$|^timestamp$|\.ts$|_ts$|^ts$', re.I), "Timestamp emitted by {vendor}", 'datetime'),
    (re.compile(r'\.time$|_time$|^time$', re.I), "Time-of-day emitted by {vendor}", 'string_short'),
    (re.compile(r'\.date$|_date$|^date$', re.I), "Date in `YYYY-MM-DD` form", 'string_short'),
    (re.compile(r'_at$', re.I), "ISO-8601 timestamp marking when this state was recorded", 'datetime'),
    # Web/URL
    (re.compile(r'(\.url|_url|^url$)$', re.I), "Full URL with scheme — as {vendor} captured it", 'url'),
    (re.compile(r'(\.uri|_uri|^uri$)$', re.I), "URI path component (no scheme/host) — as {vendor} captured it", 'string'),
    (re.compile(r'\.referer$|_referer$|^referer$|^referrer$', re.I), "HTTP Referer header value", 'url'),
    # Severity / status / action
    (re.compile(r'^severity$|\.severity$|_severity$', re.I), "Event severity as classified by {vendor}", 'string_short'),
    (re.compile(r'^level$|\.level$|_level$', re.I), "Severity level (string label, e.g., info/warn/error)", 'string_short'),
    (re.compile(r'^priority$|\.priority$|_priority$', re.I), "Priority level as classified by {vendor}", 'string_short'),
    (re.compile(r'^action$|\.action$|_action$', re.I), "Action taken by {vendor}'s enforcement engine (allow/block/quarantine/etc.)", 'string_short'),
    (re.compile(r'^outcome$|\.outcome$|_outcome$', re.I), "Event outcome (success/failure/partial) as reported by {vendor}", 'string_short'),
    (re.compile(r'^status(_?code)?$|\.status$|_status$', re.I), "Status code returned by {vendor}", 'string_short'),
    (re.compile(r'^result$|\.result$|_result$', re.I), "Result string emitted by {vendor}", 'string_short'),
    (re.compile(r'^reason$|\.reason$|_reason$', re.I), "Reason/explanation accompanying the action or outcome", 'string'),
    # Counts / sizes / durations
    (re.compile(r'(_count|_num)$|^count$|^num$', re.I), "Unsigned count of items as recorded by {vendor}", 'integer'),
    (re.compile(r'(\.size|_size)$|^size$', re.I), "Size in bytes of the payload/object", 'integer_byte_count'),
    (re.compile(r'(_bytes)$|^bytes$', re.I), "Byte count", 'integer_byte_count'),
    (re.compile(r'(_duration|duration_?ms)$', re.I), "Duration (typically milliseconds) of the operation", 'integer'),
    # App / location / version
    (re.compile(r'^app$|\.app$|_app$|\.application$|_application$|^application$', re.I), "Application name emitted by {vendor}", 'string_short'),
    (re.compile(r'^version$|\.version$|_version$', re.I), "Version string of the emitting component", 'string_short'),
    (re.compile(r'^country$|\.country$|_country$', re.I), "Country (ISO 3166-1 alpha-2 code or descriptive label)", 'string_short'),
    (re.compile(r'^region$|\.region$|_region$', re.I), "Cloud region or geographic region label", 'string_short'),
    (re.compile(r'^location$|\.location$|_location$', re.I), "Location label (region/site/zone) emitted by {vendor}", 'string'),
    (re.compile(r'^title$|\.title$|_title$', re.I), "Title/headline of the event or item", 'string'),
    (re.compile(r'^subject$|\.subject$|_subject$', re.I), "Subject line — typically email subject or event summary", 'string'),
    (re.compile(r'^description$|\.description$|_description$', re.I), "Free-form human-readable description from {vendor}", 'string_long'),
    (re.compile(r'^details$|\.details$|_details$', re.I), "Additional details payload emitted by {vendor}", 'string_long'),
    (re.compile(r'^message$|\.message$|_message$', re.I), "Human-readable event message", 'string_long'),
]


def vendor_for_pack(pack_id: str, data: dict) -> str:
    """Best-guess vendor display name from YAML."""
    return (data.get('vendor') or data.get('pack_name') or '').strip() or 'the vendor'


def infer(name: str, vendor: str) -> tuple[str, str] | None:
    """Apply PATTERNS in order; return (concept, type) on first match."""
    for pat, concept_tmpl, ftype in PATTERNS:
        if pat.search(name):
            concept = concept_tmpl.format(vendor=vendor, name=name)
            return concept, ftype
    return None


def good_example(ex, ftype: str) -> bool:
    """Same heuristic as T4 batch — preserve real-looking existing examples."""
    if not isinstance(ex, str) or not ex: return False
    if ex in ('example_value', 'token', 'sample message', 'sample'): return False
    if ftype == 'email': return '@' in ex
    if ftype == 'url': return ex.startswith(('http', 'ftp'))
    if ftype == 'ipv4': return re.match(r'^\d+\.\d+\.\d+\.\d+$', ex) is not None
    if ftype == 'ipv6': return ':' in ex
    if ftype.startswith('hash_'): return re.match(r'^[0-9a-f]+$', ex.lower()) is not None
    if ftype in ('integer', 'integer_port', 'integer_byte_count'): return ex.lstrip('-').isdigit()
    if ftype == 'mac': return re.match(r'^[0-9a-f:.-]+$', ex.lower()) is not None
    return len(ex) > 3


def polish_one(yaml_path: Path) -> tuple[int, int]:
    """Return (fields_polished, fields_total)."""
    try: data = yaml.safe_load(yaml_path.read_text())
    except Exception: return 0, 0
    if not isinstance(data, dict): return 0, 0
    vendor = vendor_for_pack(yaml_path.parent.name, data)
    polished = 0
    total = 0
    fields = data.get('fields') or []
    for f in fields:
        if not isinstance(f, dict): continue
        total += 1
        desc = (f.get('description') or '').strip()
        if not STUB_RE.match(desc): continue  # only touch generic stubs
        n = f.get('name', '')
        current_type = f.get('type', 'string')

        # Skip dotted-path leaves with `[]` markers — those are array-of-objects
        # leaves where the iter3 leaf-shape logic should have handled them.
        # Just apply the pattern based on the last segment.
        result = infer(n, vendor)
        if not result:
            continue
        concept, new_type = result
        # Don't downgrade composite json
        if current_type == 'json' and new_type != 'json':
            new_type = 'json'
        # Don't upgrade if name was caught by a generic pattern but existing
        # type is specific (e.g. enum). Trust existing if it's specific.
        SPECIFIC = {'enum', 'regex', 'json', 'hash_md5', 'hash_sha1', 'hash_sha256',
                    'email', 'ipv4', 'ipv6', 'mac', 'url', 'domain', 'host', 'user',
                    'datetime', 'timestamp_ms', 'integer_port', 'integer_byte_count',
                    'country_code', 'file_path'}
        if current_type in SPECIFIC and new_type not in SPECIFIC:
            new_type = current_type
        f['type'] = new_type
        wire = WIRE.get(new_type, WIRE['string'])
        f['description'] = f"{concept}. {wire}"
        # Example
        if not good_example(f.get('example'), new_type):
            f['example'] = EX.get(new_type, 'example_value')
        polished += 1
    if polished:
        errs = list(V.iter_errors(data))
        if errs:
            return -1, total  # signal validation failure
        yaml_path.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))
    return polished, total


def main():
    total_polished = 0
    total_packs_touched = 0
    failed = []
    for d in sorted(BASE.iterdir()):
        if not d.is_dir(): continue
        y = d / 'data_source.yaml'
        if not y.exists(): continue
        polished, total = polish_one(y)
        if polished == -1:
            failed.append(d.name)
            continue
        if polished > 0:
            total_polished += polished
            total_packs_touched += 1
    print(f"Polished {total_polished} fields across {total_packs_touched} packs.")
    if failed:
        print(f"Schema-validation failures: {len(failed)}")
        for f in failed[:5]: print(f"  {f}")


if __name__ == '__main__':
    main()
