"""Dynamic-schema log generation.

When a caller supplies a `SchemaOverrideInput` to `generate_fake_data_v2`,
this module emits records whose top-level keys match the vendor's actual
field names rather than Rosetta's generic universe. The vendor-faithful
output is what makes Cortex's stock ModelingRules parse the simulated
logs into XDM correctly — that's the point of this module.

# Value-generation strategy

Values come from a simple field-name + type heuristic. Each vendor field
gets a plausible value selected by:

  1. Type hint from the override (e.g., type="ipv4" → random IPv4)
  2. Field-name pattern matching when type is generic (string) — e.g.,
     a field named "srcip" / "src_ip" / "source_ip" gets an IP regardless
     of declared type
  3. Observables passed by the caller take precedence over heuristics so
     scenarios with specific bad/good IPs are honored
  4. Fallback: short random string

Value quality is improved by the caller:
  - the simulate_vendor_logs skill provides observables + a pinned
    datetime range so generated logs land in a consistent investigative
    window
  - value constraints (allowed enum values, port range, etc.) are not
    extracted from the .xif modeling rule; see below

# What this module deliberately doesn't do

  - Does NOT parse the .xif modeling rule.
  - Does NOT generate raw_log strings for rawlog-only schemas (those
    need regex-template extraction).
  - Does NOT do server-side observable lookups or threat-intel queries.
"""

from __future__ import annotations

import re
import datetime as _dt
import logging
import random
import string
from typing import Any, List, Optional

logger = logging.getLogger("phantom-xlog")


# ── Field-name → value-strategy heuristics ─────────────────────────
#
# Substring matches against the lowercased field name. First match wins.
# When generating values, we use the strategy from the matched bucket
# regardless of the declared `type` (heuristic > declared type because
# many ModelingRule schemas declare everything as `string` — the field
# NAME often carries more semantic info than the type).

# Reserved observables_dict key holding a list of field-maps that must vary
# TOGETHER. One entry is drawn per record and applied as a unit, so
# a host, its IP and its user stay bound to the same simulated machine instead
# of being drawn independently into a cross-product. Not a vendor field name —
# stripped before generation so it can never reach the wire.
ENTITY_GROUP_KEY = "__entities__"

_IP_PATTERNS = ("srcip", "dstip", "src_ip", "dst_ip", "ipaddr", "ipv4", "ip_addr", "address",
                "clientip", "client_ip", "socketip", "socket_ip", "originip", "origin_ip",
                "callerip", "caller_ip", "remoteip", "remote_ip", "localip", "serverip",
                "ipaddress")
_PORT_PATTERNS = ("srcport", "dstport", "src_port", "dst_port", "port")
_USER_PATTERNS = ("user", "username", "account", "principal")
_HOST_PATTERNS = ("host", "hostname", "device", "endpoint")
_BYTES_PATTERNS = ("byte", "size", "length", "duration", "count", "_num", "_int")
_TIME_PATTERNS = ("time", "timestamp", "datetime", "_ts")
_ACTION_PATTERNS = ("action", "verb", "operation", "status", "result", "outcome")
_PROTOCOL_PATTERNS = ("protocol", "proto", "service")
_URL_PATTERNS = ("url", "uri", "path", "href")
_DOMAIN_PATTERNS = ("domain", "hostname", "fqdn")
_MAC_PATTERNS = ("mac", "macaddr", "mac_addr")
_HASH_PATTERNS = ("hash", "sha1", "sha256", "md5", "digest")
# Avoid "to" / "from" alone — they match too many unrelated names
# (e.g., "protocol" contains "to"). Stick to email-specific tokens.
_EMAIL_PATTERNS = ("email", "mailto", "sender", "recipient", "from_addr", "to_addr")
_FILE_PATTERNS = ("file", "filename", "filepath", "process_name", "image")
# Checked BEFORE _BYTES_PATTERNS: "country" contains "count", so a country
# field would otherwise be mis-typed as a byte-count integer (the Azure WAF
# clientCountry_s → 3638 bug). Country must win.
_COUNTRY_PATTERNS = ("country", "countrycode", "geo_country", "src_country", "dst_country")
_METHOD_PATTERNS = ("httpmethod", "http_method", "requestmethod", "request_method")

_ACTION_VOCAB = ["allow", "deny", "block", "pass", "drop", "accept", "reject"]
_PROTOCOL_VOCAB = ["TCP", "UDP", "ICMP", "HTTP", "HTTPS"]
_COUNTRY_VOCAB = ["US", "DE", "JP", "GB", "FR", "CA", "AU", "BR", "IN", "NL", "SG", "SE"]
_HTTP_METHOD_VOCAB = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]


def _rand_ip() -> str:
    return ".".join(str(random.randint(1, 254)) for _ in range(4))


def _rand_port() -> int:
    return random.randint(1024, 65535)


def _rand_string(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def _rand_user() -> str:
    return random.choice(["alice", "bob", "carol", "dave", "eve", "frank"])


def _rand_host() -> str:
    return random.choice(["host-a", "host-b", "host-c", "server-1", "endpoint-7"])


def _rand_mac() -> str:
    return ":".join(f"{random.randint(0, 255):02x}" for _ in range(6))


def _rand_hash(length: int = 64) -> str:
    return "".join(random.choices("0123456789abcdef", k=length))


def _rand_email() -> str:
    return f"{_rand_user()}@example.com"


def _rand_url() -> str:
    return f"https://example.com/{_rand_string(6)}"


def _rand_domain() -> str:
    return random.choice(["example.com", "corp.local", "internal.test"])


def _rand_file() -> str:
    return random.choice(["explorer.exe", "powershell.exe", "/usr/bin/curl", "/tmp/payload.sh"])


def _rand_datetime(base: Optional[_dt.datetime] = None) -> str:
    if base is None:
        base = _dt.datetime.utcnow()
    jitter = random.randint(-3600, 0)  # last hour
    return (base + _dt.timedelta(seconds=jitter)).isoformat() + "Z"


def _rand_epoch_ms(base: Optional[_dt.datetime] = None) -> int:
    if base is None:
        base = _dt.datetime.utcnow()
    dt = base + _dt.timedelta(seconds=random.randint(-3600, 0))
    epoch = _dt.datetime(1970, 1, 1)
    return int((dt - epoch).total_seconds() * 1000)


def _rand_ipv6() -> str:
    return ":".join(f"{random.randint(0, 65535):x}" for _ in range(8))


def _rand_country() -> str:
    return random.choice(_COUNTRY_VOCAB)


def _rand_http_method() -> str:
    return random.choice(_HTTP_METHOD_VOCAB)


def _matches(name_lc: str, patterns: tuple[str, ...]) -> bool:
    return any(p in name_lc for p in patterns)


# A vendor's native log line usually carries its own timestamp, and the
# parsing rule derives `_time` from THAT, not from ingestion. A frozen example
# date therefore stamps every generated event in the past, where normal query
# windows never find it -- the failure looks like "nothing landed" and is not.
# `{{now:<strftime>}}` inside an example is rendered at emit time so the line
# is self-dating. Example: `{{now:%-m/%-d/%Y %-I:%M:%S %p}}` -> 9/2/2026 2:21:39 PM
_PLACEHOLDER_RE = re.compile(r"\{\{now:([^}]+)\}\}")


def _render_placeholders(value: Any, base: Optional[_dt.datetime] = None) -> Any:
    """Substitute {{now:FMT}} tokens in a string value. Non-strings pass through."""
    if not isinstance(value, str) or "{{now:" not in value:
        return value
    now = base or _dt.datetime.now(_dt.timezone.utc)

    def _sub(m):
        try:
            return now.strftime(m.group(1))
        except Exception:
            # A bad format string must not take the whole worker down; leave
            # the token visible so it is obvious in the emitted event.
            return m.group(0)

    return _PLACEHOLDER_RE.sub(_sub, value)


def _generate_value(
    field_name: str,
    field_type: Optional[str],
    is_array: bool,
    base_datetime: Optional[_dt.datetime],
    observable_overrides: dict[str, Any],
) -> Any:
    """Generate one value for one field. Honors observable_overrides first."""
    if field_name in observable_overrides:
        ov = observable_overrides[field_name]
        # `observables_dict` conventionally maps a field to a LIST of
        # candidate values (rosetta semantics — pick one). Unwrap so a
        # single-element discriminator list yields the scalar the modeling-
        # rule PR filter expects (e.g. eventType=user.authentication.sso),
        # NOT the bracketed ["user.authentication.sso"] that would
        # json-serialize on the CEF wire and never match the PR filter.
        if isinstance(ov, (list, tuple)):
            picked = random.choice(list(ov)) if ov else _rand_string()
        else:
            picked = ov
        # An observables_dict value may carry {{now:...}} too -- a caller
        # pinning a raw line needs it to self-date exactly as an example does.
        return _render_placeholders(picked, base_datetime)

    name_lc = field_name.lower()

    # Declared semantic type wins — the cortex extractor emits a precise type
    # vocabulary (ipv4/ipv6/user/host/integer_port/url/email/file_path/mac/
    # domain/integer_byte_count/hash_*/country_code/…). Honoring it produces a
    # value the modeling rule's regex / typed reads actually accept, instead of
    # a random token that defeats `regextract`, enum gates, and HTTP-method
    # lookups. ~2,000+ fields across the bundle carry one of these types.
    if field_type:
        t = field_type.lower()
        # numeric / temporal
        if t in ("int", "integer"):
            if _matches(name_lc, _PORT_PATTERNS):
                return _rand_port()
            return random.randint(0, 10_000)
        if t in ("integer_port", "port"):
            return _rand_port()
        if t in ("integer_byte_count", "byte_count", "bytes"):
            return random.randint(0, 10_000_000)
        if t in ("float", "double", "decimal"):
            return round(random.uniform(0, 1000), 2)
        if t in ("boolean", "bool"):
            return random.choice([True, False])
        if t in ("datetime", "timestamp"):
            return _rand_datetime(base_datetime)
        if t in ("timestamp_ms", "epoch_ms"):
            return _rand_epoch_ms(base_datetime)
        # network / host / identity / web
        if t in ("ipv4", "ip"):
            return _rand_ip()
        if t == "ipv6":
            return _rand_ipv6()
        if t in ("mac", "mac_address"):
            return _rand_mac()
        if t in ("url", "uri"):
            return _rand_url()
        if t in ("host", "fqdn", "hostname"):
            return _rand_host()
        if t == "domain":
            return _rand_domain()
        if t == "email":
            return _rand_email()
        if t in ("user", "username"):
            return _rand_user()
        if t in ("file_path", "filepath", "file"):
            return _rand_file()
        if t == "country_code":
            return _rand_country()
        if t in ("hash_md5", "md5"):
            return _rand_hash(32)
        if t in ("hash_sha1", "sha1"):
            return _rand_hash(40)
        if t in ("hash_sha256", "sha256", "hash"):
            return _rand_hash(64)

    # Name-pattern heuristics (in priority order — most specific first)
    if _matches(name_lc, _MAC_PATTERNS):
        return _rand_mac()
    if _matches(name_lc, _IP_PATTERNS):
        return _rand_ip()
    if _matches(name_lc, _PORT_PATTERNS):
        return _rand_port()
    if _matches(name_lc, _HASH_PATTERNS):
        return _rand_hash()
    if _matches(name_lc, _EMAIL_PATTERNS):
        return _rand_email()
    if _matches(name_lc, _URL_PATTERNS):
        return _rand_url()
    if _matches(name_lc, _FILE_PATTERNS):
        return _rand_file()
    if _matches(name_lc, _TIME_PATTERNS):
        return _rand_datetime(base_datetime)
    if _matches(name_lc, _USER_PATTERNS):
        return _rand_user()
    if _matches(name_lc, _DOMAIN_PATTERNS):
        return _rand_domain()
    if _matches(name_lc, _HOST_PATTERNS):
        return _rand_host()
    if _matches(name_lc, _METHOD_PATTERNS):
        return _rand_http_method()
    if _matches(name_lc, _COUNTRY_PATTERNS):  # before _BYTES — "country" contains "count"
        return _rand_country()
    if _matches(name_lc, _BYTES_PATTERNS):
        return random.randint(0, 10_000)
    if _matches(name_lc, _ACTION_PATTERNS):
        return random.choice(_ACTION_VOCAB)
    if _matches(name_lc, _PROTOCOL_PATTERNS):
        return random.choice(_PROTOCOL_VOCAB)

    # Default fallback — short random string
    return _rand_string()


def _build_nested(
    leaves: List[tuple],
    base_datetime: Optional[_dt.datetime],
    observable_overrides: dict[str, Any],
    parent: str = "",
) -> dict[str, Any]:
    """Build a nested dict for a composite (`type: json`) field from its
    dotted-leaf children.

    `leaves` is a list of (relative_dotted_path, field_type, is_array) where
    the path is RELATIVE to the composite (e.g. for composite `actor` the
    leaf `actor.id` contributes `("id", "string_short", False)`; deeper
    `authenticationContext.issuer.id` contributes `("issuer.id", …)`).

    `[]` array markers in a path segment are stripped (the segment becomes a
    nested object key; arrays-of-objects are approximated as a single object).
    Each leaf value is generated by `_generate_value` so the synthesized JSON
    carries vendor-faithful, type-appropriate values — which is what lets the
    modeling rule's `json_extract_scalar(<composite>, "$.<leaf>")` resolve.
    """
    obj: dict[str, Any] = {}
    for _leaf in leaves:
        # 5-tuples since gate pinning landed; tolerate legacy 3-tuples so a
        # stale caller (or an old test) does not explode.
        rel_path, ftype, is_arr = _leaf[0], _leaf[1], _leaf[2]
        is_gate = _leaf[3] if len(_leaf) > 3 else False
        example = _leaf[4] if len(_leaf) > 4 else None
        enum_vals = _leaf[5] if len(_leaf) > 5 else None
        parts = [p.replace("[]", "") for p in rel_path.split(".") if p.replace("[]", "")]
        if not parts:
            continue
        cur = obj
        for seg in parts[:-1]:
            nxt = cur.get(seg)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[seg] = nxt
            cur = nxt
        leaf = parts[-1]
        # Resolve an override by the field's FULL declared name first
        # (`access_device.ip`), then by the bare leaf (`ip`). The schema
        # declares nested fields dotted and `observables_dict` is documented as
        # field-name -> value, so keying by the declared name MUST work; before
        # this, only the leaf was consulted, making every nested field
        # unpinnable — including the threat-intel IP injection this parameter
        # exists for. The bare leaf still works but is ambiguous across
        # composites (`access_device.ip` and `auth_device.ip` share leaf `ip`),
        # so the full name wins. Aliasing onto the leaf rather than passing the
        # dotted name through keeps the pattern heuristics matching.
        _ov = observable_overrides or {}
        _full = f"{parent}.{rel_path}" if parent else rel_path
        _local = {**_ov, leaf: _ov[_full]} if _full in _ov else _ov
        overridden = _full in _ov or leaf in _ov
        # Same precedence as flat fields: override -> gate example -> enum -> type.
        # The enum step matters here: without it an unpinned
        # `event_data.LogonType` would come out as a random token.
        if is_gate and example is not None and not overridden:
            val = example
        elif str(ftype or "").lower() == "enum" and enum_vals and not overridden:
            val = random.choice(enum_vals)
        else:
            val = _generate_value(leaf, ftype, False, base_datetime, _local)
        cur[leaf] = [val] if is_arr else val
    return obj


def generate_records_with_override(
    count: int,
    vendor_fields: List[Any],
    base_datetime: Optional[_dt.datetime] = None,
    observable_overrides: Optional[dict[str, Any]] = None,
    omit_meta: bool = True,
) -> List[dict[str, Any]]:
    """Generate `count` records using the supplied vendor field schema.

    Args:
        count: how many records to generate.
        vendor_fields: list of SchemaOverrideField (one per vendor field).
        base_datetime: anchor datetime for any time-typed fields. None
            means use UTC now ± random jitter.
        observable_overrides: dict of field_name -> value to FORCE for
            that field (e.g., the simulate_vendor_logs skill passes specific bad
            IPs from threat intel).
        omit_meta: when True (default), meta fields (is_meta=True) are
            omitted from the output. The modeling rule's XDM mapping
            populates _id / _time / _vendor / etc. at ingestion time;
            including them in simulated logs would conflict.

    Returns:
        List of dicts, one per record. Each dict has vendor-field names
        as keys with heuristically-generated values.
    """
    observable_overrides = observable_overrides or {}
    records: List[dict[str, Any]] = []
    if not vendor_fields:
        # No schema → empty objects for `count` records (defensive).
        return [{} for _ in range(count)]

    # Field accessors — tolerate BOTH strawberry-input instances (attribute
    # access) and plain dicts (unit tests / JSON). Explicit, not chained-or
    # (operator precedence bit us once: `a or b if c else d` parses wrong).
    def _name(f):
        return f.get("name") if isinstance(f, dict) else getattr(f, "name", None)

    def _type(f):
        return f.get("type") if isinstance(f, dict) else getattr(f, "type", None)

    def _arr(f):
        return bool(f.get("is_array", False) if isinstance(f, dict) else getattr(f, "is_array", False))

    def _meta(f):
        return bool(f.get("is_meta", False) if isinstance(f, dict) else getattr(f, "is_meta", False))

    def _gate(f):
        return bool(f.get("is_gate", False) if isinstance(f, dict) else getattr(f, "is_gate", False))

    def _example(f):
        return f.get("example") if isinstance(f, dict) else getattr(f, "example", None)

    def _enum(f):
        """Allowed values for a `type: enum` field.

        Without this the type is decorative: an enum field falls through to the
        random-token branch, so `act` on a firewall emits 'PWnpgWwN' and
        xdm.observer.action populates with a meaningless value -- which reads as
        working, and is therefore worse than null.
        """
        v = f.get("enum_values") if isinstance(f, dict) else getattr(f, "enum_values", None)
        if isinstance(v, (list, tuple)) and v:
            return [str(x) for x in v if x is not None]
        return None

    # Composite-JSON grouping (type:json synthesis).
    # A "composite parent" is a top-level field that EITHER has dotted-leaf
    # children (e.g. `actor` ← `actor.id`, `actor.alternateId`) OR is declared
    # `type: json`. Leaves are folded into the parent's nested JSON object so
    # the modeling rule's `json_extract_scalar(parent, "$.leaf")` resolves —
    # a `type: json` field must not fall through to a random string, which
    # would starve XDM.
    all_names = [n for n in (_name(f) for f in vendor_fields) if n]
    composite_parents = {n.split(".")[0] for n in all_names if "." in n}
    composite_parents |= {
        _name(f) for f in vendor_fields
        if _name(f) and "." not in _name(f) and (_type(f) or "").lower() == "json"
    }
    leaves_by_parent: dict[str, list] = {}
    composite_is_array: dict[str, bool] = {}
    for f in vendor_fields:
        n = _name(f)
        if not n:
            continue
        if "." in n:
            top = n.split(".", 1)[0]
            leaves_by_parent.setdefault(top, []).append(
                (n.split(".", 1)[1], _type(f), _arr(f), _gate(f), _example(f), _enum(f))
            )
        elif n in composite_parents:
            composite_is_array[n] = _arr(f)

    # ── Correlated entity groups ───────────────────────────
    # Every field resolves independently, so `observables_dict` of
    # {shost: [a, b], src: [ip1, ip2]} emits the CROSS-PRODUCT: host `a` gets
    # ip1 on one event and ip2 on the next. Nothing could express "these fields
    # belong to the same machine".
    #
    # That is not cosmetic. Cortex analytics are ENTITY-PROFILING detectors —
    # they learn what is normal for an endpoint and alert on deviation — and the
    # Analytics Engine's own activation prerequisite is network logs from >=30
    # ENDPOINTS over >=2 weeks. On a Cortex tenant, uncorrelated output shows
    # 40 hosts present, ZERO with a stable identity (one `shost` claimed 25,273 distinct
    # `src` values), 3 analytics alerts in 60 days and all of them pattern-
    # matching BIOCs. The workaround — one worker per endpoint — is capped by
    # WORKERS_NUMBER (25 install-wide, shared with every other feed), so it
    # cannot reach 30 endpoints while any other source runs.
    #
    # Fix: a reserved `__entities__` key holding a list of field-maps. One
    # entity is drawn per RECORD and its fields applied together, so a host,
    # its IP and its user stay bound. Everything else keeps the existing
    # independent-draw semantics, so this is backward compatible, and it needs
    # no GraphQL change because observablesDict is already a JSON scalar.
    #
    #   observablesDict = {
    #     "app": ["HTTP", "HTTPS"],                      # independent, as before
    #     "__entities__": [{"shost": "wks-001", "src": "10.20.5.1", "suser": "ahmed"},
    #                      {"shost": "wks-002", "src": "10.20.5.2", "suser": "sameh"}]
    #   }
    _entity_pool = observable_overrides.get(ENTITY_GROUP_KEY) or None
    if _entity_pool is not None and not isinstance(_entity_pool, (list, tuple)):
        _entity_pool = None          # malformed → ignore rather than crash a run
    _base_overrides = {k: v for k, v in observable_overrides.items() if k != ENTITY_GROUP_KEY}

    for _ in range(count):
        if _entity_pool:
            entity = random.choice(list(_entity_pool))
            observable_overrides = (
                {**_base_overrides, **entity} if isinstance(entity, dict) else _base_overrides
            )
        else:
            observable_overrides = _base_overrides
        rec: dict[str, Any] = {}
        for f in vendor_fields:
            name = _name(f)
            if not name:
                continue
            if omit_meta and _meta(f):
                continue

            # Dotted leaf whose top-level prefix is a composite → folded into
            # the parent's JSON object (don't emit as a separate flat key).
            if "." in name and name.split(".", 1)[0] in composite_parents:
                continue

            # Composite parent → synthesize a nested JSON object from its leaves.
            if name in composite_parents:
                obj = _build_nested(
                    leaves_by_parent.get(name, []), base_datetime, observable_overrides,
                    parent=name,
                )
                if not obj:
                    # Declared type:json but no leaves in the schema → a small
                    # generic object so it's valid JSON, never a random string.
                    obj = {"value": _generate_value(name, "string", False, base_datetime, observable_overrides)}
                rec[name] = [obj] if composite_is_array.get(name) else obj
                continue

            # Flat field.
            field_type = _type(f)
            is_array = _arr(f)
            # A GATE field is one the parsing/modeling rule filters on. Its
            # schema `example` is not illustrative -- it is the only value the
            # rule accepts, so a synthesized token means the event is dropped
            # at ingest (no_hit=drop) with NO raw row and NO error to diagnose.
            # Pin it. Everything else keeps its randomness, because pinning
            # every field would make all generated events identical.
            # `observables_dict` still wins: an explicit caller overrides.
            # `_raw_log` is the vendor's native log line, not a synthesizable
            # value -- for a raw-syslog source it IS the payload, and the
            # modeling rule regexes straight into it. Pin it like a gate.
            pinned = (
                (_gate(f) or name in ("_raw_log", "raw_log"))
                and name not in (observable_overrides or {})
            )
            enum_vals = _enum(f)
            use_enum = (
                str(field_type or "").lower() == "enum"
                and enum_vals
                and name not in (observable_overrides or {})
            )
            if pinned and _example(f) is not None:
                value = _render_placeholders(_example(f), base_datetime)
            elif use_enum:
                value = random.choice(enum_vals)
            else:
                value = _generate_value(
                    name, field_type, is_array, base_datetime, observable_overrides
                )
            if is_array and not pinned:
                if use_enum:
                    value = [random.choice(enum_vals)
                             for _ in range(random.randint(1, 3))]
                else:
                    value = [
                        _generate_value(name, field_type, False, base_datetime, observable_overrides)
                        for _ in range(random.randint(1, 3))
                    ]
            rec[name] = value

        # Emit any composite parent that had dotted leaves but NO explicit
        # top-level field declaring it (leaf-only composites still materialize
        # as a nested object rather than vanishing).
        for parent in composite_parents:
            if parent not in rec and leaves_by_parent.get(parent):
                obj = _build_nested(
                    leaves_by_parent[parent], base_datetime, observable_overrides,
                    parent=parent,
                )
                if obj:
                    rec[parent] = [obj] if composite_is_array.get(parent) else obj

        records.append(rec)
    return records
