"""MCP tools for managing Phantom workers."""

import ast
import functools
import json
import logging
from typing import Any, Dict, List, Optional, Union

from fastmcp import Context
from pydantic import BaseModel, Field

from ._graphql_client import PhantomGraphQLClient
from ._xlog_url_resolver import resolve_xlog_url

logger = logging.getLogger("Phantom MCP")


class CreateDataWorkerRequest(BaseModel):
    """Request model for creating a data worker."""

    type: str = Field(
        description=(
            "Worker log type (SYSLOG, CEF, LEEF and JSON ). "
            "Example: 'CEF'"
        )
    )
    destination: str = Field(
        default="XSIAM_WEBHOOK",
        description=(
            "Where to send the generated logs. Three accepted forms:\n\n"

            "1. STORE REFERENCE (PREFERRED) — 'logdest:<id>', where <id> is the "
            "`id` of a configured log destination returned by `log_destinations_list`. "
            "The platform resolves the reference server-side BEFORE the worker is "
            "created: a syslog destination becomes '<protocol>:<host>:<port>', and an "
            "xsiam_http destination becomes the XSIAM webhook with its endpoint + auth "
            "key injected automatically. You NEVER read, format, or pass a "
            "destination's credentials yourself — pass the reference, the platform "
            "does the rest (so secrets never cross the agent surface).\n"
            "   Choosing the <id>: call `log_destinations_list`, then —\n"
            "     - exactly one destination matches the transport the operator asked "
            "for (e.g. one syslog when they say 'syslog') → use it without asking;\n"
            "     - several match → ask the operator which one (by name or host);\n"
            "     - none match → offer to create a secretless syslog destination with "
            "`log_destinations_create`, or guide the operator to add a credentialed "
            "one on the /log-destinations page (you cannot create credentialed ones).\n"
            "   (webhook / splunk_hec destination types are not wired into log "
            "generation yet — tell the operator and ask for a syslog/xsiam_http one.)\n\n"

            "2. RAW ADDRESS — 'udp:10.0.0.8:514' or 'tcp:host:port', for an ad-hoc "
            "one-shot to a target the operator names explicitly and won't reuse.\n\n"

            "3. 'XSIAM_WEBHOOK' (default) — legacy: posts to the WEBHOOK_ENDPOINT / "
            "WEBHOOK_KEY env vars configured on the Phantom service. Prefer a "
            "'logdest:<id>' xsiam_http destination for anything the operator reuses.\n\n"

            "## Where records LAND in XSIAM\n\n"
            "Knowing the dataset routing is critical when the operator asks "
            "to 'verify the records arrived' — the agent should query the "
            "RIGHT dataset, not guess.\n\n"
            "  • destination='XSIAM_WEBHOOK' or any xsiam_http destination:\n"
            "    → dataset = `phantom_logs_raw` (ALWAYS, regardless of\n"
            "      source/vendor/product tags). XSIAM wraps each batch in\n"
            "      one row with an 'events' JSON-array column.\n"
            "      Verify XQL:\n"
            "        dataset = phantom_logs_raw\n"
            "        | filter to_string(events) contains '<your-marker>'\n"
            "        | limit 20\n\n"
            "  • destination=udp/tcp string pointing at an XSIAM broker VM,\n"
            "    type='CEF', vendor + product set:\n"
            "    → dataset = `<vendor>_<product>_raw` (lowercased,\n"
            "      non-alphanumerics → '_'). E.g. vendor='Fortinet',\n"
            "      product='FortiGate' lands in `fortinet_fortigate_raw`.\n"
            "      Each CEF extension key (act, src, dst, spt, ...) becomes\n"
            "      its own typed column. NO modeling-rule unflattening needed.\n"
            "      Verify XQL:\n"
            "        dataset = fortinet_fortigate_raw\n"
            "        | filter src ~= '<your-test-ip-prefix>.*'\n"
            "        | sort desc _time | limit 20\n\n"
            "  • destination=udp/tcp pointing at any OTHER syslog target\n"
            "    (rsyslog, syslog-ng, on-prem SIEM): records land wherever\n"
            "    the operator's collector routes them — the agent should\n"
            "    ASK the operator for the dataset/index name rather than\n"
            "    guess.\n\n"
            "When the operator asks the agent to 'send X logs and verify\n"
            "they arrive in XSIAM', the agent should: (a) compose the\n"
            "phantom_create_data_worker call with the right type + vendor +\n"
            "product + destination, (b) wait ~60-120s for ingestion,\n"
            "(c) call the xsiam connector's run_xql_query with the dataset\n"
            "name from the table above + a filter on the operator-chosen\n"
            "marker (an unusual IP, a smoke_run_id field, etc.)."
        ),
    )
    count: int = Field(
        default=1,
        ge=1,
        description=(
            "Events per BATCH TICK — NOT a total. Combined with `interval` this "
            "is a SUSTAINED RATE of count/interval events per second, and the "
            "worker runs until you stop it. count=200, interval=1 is therefore "
            "200 events/SECOND (~17 million/day), not '200 events'. "
            "The server REJECTS anything above 10 events/sec as a sustained "
            "rate. For ordinary generation keep count small and interval >= 2 "
            "(e.g. count=1, interval=5 = 0.2/sec). To send a lot of data "
            "quickly, do NOT raise count — declare a bounded burst with "
            "duration_seconds or max_events instead."
        ),
    )
    interval: int = Field(
        default=2,
        ge=1,
        description=(
            "Seconds between batch ticks. Must be >= 1: an interval of 0 or "
            "less does not throttle at all and is rejected. Raising interval "
            "is the simplest way to lower the sustained rate."
        ),
    )
    duration_seconds: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Declare a BOUNDED BURST of this many seconds. Setting this (or "
            "max_events) lets the worker run far faster than the sustained "
            "ceiling — up to 500 events/sec, capped at 50,000 events total, "
            "one burst at a time. Use it when the operator wants a large "
            "volume QUICKLY (seeding a dataset, a load test), or simply to say "
            "how long a worker lives. When neither this nor max_events is set, "
            "the worker stops by itself after 900 seconds; pass "
            "continuous=true only when the operator asked for a worker that "
            "runs until it is stopped."
        ),
    )
    max_events: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Declare a BOUNDED BURST of at most this many events. Same effect "
            "as duration_seconds — it promises the run is finite, which is "
            "what buys the higher rate ceiling."
        ),
    )
    vendor: Optional[str] = Field(
        default=None,
        description=(
            "EXACT CEF vendor LITERAL — use the `vendor` value from data_sources_get_schema "
            "(or its how_to_use 'Required CEF header'), NOT a prettified/display name. "
            "Drives broker → <vendor>_<product>_raw routing."
        ),
    )
    product: Optional[str] = Field(
        default=None,
        description=(
            "EXACT CEF product LITERAL — use the `product` value from data_sources_get_schema, "
            "NOT a friendly/expanded name. TRAP: the 'Okta — SSO' source's product is `Okta` "
            "(NOT `Okta SSO`); the SSO dataset split comes from the eventType discriminator in "
            "observables_dict, not the product string."
        ),
    )
    version: Optional[str] = Field(default=None, description="Version. Example: '1.0'")
    fields: Optional[Union[str, List[str]]] = Field(
        default=None,
        description=(
            "Custom fields to include. Accepts a comma-separated string or JSON list. "
            "Example: 'custom1,custom2' or [\"custom1\", \"custom2\"]"
        ),
    )
    datetime_iso: Optional[str] = Field(
        default=None,
        description="Timestamp in ISO format. Example: '2024-01-02 08:00:00'",
    )
    # Dict[str, Any], not Dict[str, List[str]]: the reserved `__entities__` key
    # holds a list of field-MAPS. Same annotation as data_faker.py.
    observables_dict: Optional[Union[Dict[str, Any], str]] = Field(
        default=None,
        description=(
            "Observables dictionary (camelCase keys) , you can use phantom_get_field_info to retrieve the full observable catalog. "
            "Example: {'srcHost': ['192.168.10.15'], 'remotePort': ['443']}. "
            "With schema_override, the reserved key '__entities__' takes a list of field-maps; one map is drawn per "
            "record and applied together, so e.g. a host, its IP and its user stay bound."
        ),
    )
    required_fields: Optional[Union[List[str], str]] = Field(
        default=None,
        description=(
            "Required field enums as list , you can use phantom_get_field_info to retrieve the required fields for each log type. "
            "Example: ['SRC_HOST', 'DST_HOST', 'REMOTE_PORT']"
        ),
    )
    verify_ssl: bool = Field(
        default=False,
        description="Verify SSL certificates for HTTPS destinations (ignored in scenario worker mode).",
    )
    name: Optional[str] = Field(
        default=None,
        description="Scenario name (used to create the worker). Example: 'Single Worker Scenario'",
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Scenario tags. Example: ['worker', 'single-step']",
    )
    tactic: Optional[str] = Field(default=None, description="MITRE ATT&CK tactic. Example: 'discovery'")
    technique: Optional[str] = Field(default=None, description="MITRE ATT&CK technique. Example: 'T1046'")
    procedure: Optional[str] = Field(default=None, description="Procedure description. Example: 'Port Scan'")
    # Vendor-faithful streaming. Pass an installed data
    # source's schema here to make the worker emit records whose top-
    # level keys match the vendor's actual field names rather than
    # Rosetta's generic observables. Get the field list by calling
    # `data_sources_get_schema(pack_name, rule_name, dataset_name)` on
    # an installed data source and pass its `fields` array verbatim.
    #
    # Set this when the operator says "stream FortiGate logs" or
    # similar — the agent should look up FortiGate in the installed
    # data sources, fetch the schema, and pass the fields here so the
    # streamed records carry FTNTFGT* field names that Cortex's
    # FortiGate ModelingRule parses cleanly into XDM.
    #
    # The override path routes through xlog's OverrideSender
    # for UDP/TCP destinations. XSIAM and XSIAM_WEBHOOK destinations
    # ignore this field (those paths have their own format
    # normalization).
    schema_override: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description=(
            "Optional vendor-faithful schema override. List of "
            "{name, type?, is_array?, is_meta?} dicts (each from a "
            "data_sources_get_schema response's `fields` array). When "
            "supplied with a udp:/tcp: destination, the worker emits "
            "records whose top-level keys match the vendor's actual "
            "field names instead of Rosetta's generic observables."
        ),
    )
    # Store-driven log-destination resolution — PLATFORM-INJECTED.
    # The agent never sets these: when `destination='logdest:<id>'`, the
    # MCP-side resolver (pkg.connector_proxy) rewrites destination to the
    # concrete address and, for an xsiam_http destination, injects the
    # endpoint URL + auth key HERE before the call reaches this container.
    # The agent therefore never handles the webhook secret (credential
    # guardrail). When absent, the XSIAM_WEBHOOK path falls back to the
    # WEBHOOK_ENDPOINT / WEBHOOK_KEY env defaults. Forwarded to xlog as
    # webhookUrl / webhookKey.
    webhook_url: Optional[str] = Field(
        default=None,
        description="Platform-injected webhook endpoint (store xsiam_http). Do not set manually.",
    )
    webhook_key: Optional[str] = Field(
        default=None,
        description="Platform-injected webhook auth key (store xsiam_http). Do not set manually.",
    )


_OBSERVABLE_SNAKE_KEYS = [
    "local_ip",
    "remote_ip",
    "local_ip_v6",
    "remote_ip_v6",
    "source_port",
    "remote_port",
    "protocol",
    "src_host",
    "dst_host",
    "src_domain",
    "dst_domain",
    "sender_email",
    "recipient_email",
    "email_subject",
    "email_body",
    "url",
    "inbound_bytes",
    "outbound_bytes",
    "app",
    "os",
    "user",
    "cve",
    "file_name",
    "file_hash",
    "win_cmd",
    "unix_cmd",
    "win_process",
    "win_child_process",
    "unix_process",
    "unix_child_process",
    "technique",
    "entry_type",
    "severity",
    "sensor",
    "action",
    "event_id",
    "error_code",
    "terms",
    "incident_types",
    "analysts",
    "alert_types",
    "alert_name",
    "action_status",
    "query_type",
    "database_name",
    "query",
]


def _snake_to_camel(value: str, upper_ip: bool) -> str:
    parts = value.split("_")
    if not parts:
        return value
    converted = [parts[0]]
    for token in parts[1:]:
        if token == "ip":
            converted.append("IP" if upper_ip else "Ip")
        elif token in {"v6", "v4"}:
            converted.append(token.upper())
        else:
            converted.append(token.capitalize())
    return "".join(converted)


_OBSERVABLE_KEY_MAP = {key: _snake_to_camel(key, upper_ip=True) for key in _OBSERVABLE_SNAKE_KEYS}
_OBSERVABLE_KEY_MAP.update(
    {key: _snake_to_camel(key, upper_ip=False) for key in _OBSERVABLE_SNAKE_KEYS}
)
_OBSERVABLE_KEY_MAP["remorePort"] = "remotePort"


def _normalize_observable_keys(values: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in values.items():
        mapped_key = _OBSERVABLE_KEY_MAP.get(key, key)
        normalized[mapped_key] = value
    return normalized


def _load_string_value(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value


def _parse_required_fields(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    if isinstance(value, str):
        loaded = _load_string_value(value)
        if loaded is None:
            return None
        if isinstance(loaded, list):
            return [str(item).strip().upper() for item in loaded if str(item).strip()]
        if isinstance(loaded, str):
            parts = [item.strip().upper() for item in loaded.split(",") if item.strip()]
            return parts or None
    return None


def _parse_fields(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ",".join(parts) if parts else None
    if isinstance(value, str):
        loaded = _load_string_value(value)
        if loaded is None:
            return None
        if isinstance(loaded, list):
            parts = [str(item).strip() for item in loaded if str(item).strip()]
            return ",".join(parts) if parts else None
        if isinstance(loaded, str):
            return loaded.strip() or None
    return None


def _parse_observables_dict(
    value: Any, normalize: bool = True
) -> Optional[Dict[str, Any]]:
    """Coerce observables_dict to a plain dict.

    `normalize` maps legacy snake_case observable aliases onto the camelCase
    names the faker vocabulary uses (`event_id` -> `eventId`). That is correct
    for the SCENARIO/faker paths, whose namespace IS that 46-key vocabulary.

    It is WRONG on the schema_override path, where the namespace is the
    VENDOR SCHEMA. There, a field genuinely named `event_id` (Windows Event
    Log, AMSI) got silently renamed to `eventId`, matched no schema field, and
    fell through to a random value -- so the pin vanished with no error. That
    breaks any Windows Event ID scenario outright, since `event_id` is what
    selects 4624 vs 4769. Same hazard for `query`/`query_type` (DNS), `action`,
    `os`, `user`, `severity` and the rest of the 46.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return _normalize_observable_keys(value) if normalize else dict(value)
    if isinstance(value, str):
        loaded = _load_string_value(value)
        if loaded is None:
            return None
        if isinstance(loaded, dict):
            return _normalize_observable_keys(loaded) if normalize else dict(loaded)
    return None


DEFAULT_WORKER_SECONDS = 900  # a worker given no bound stops after this long, unless the caller asks for a continuous one


def _bound_by_default(fn):
    """Give every worker a lifetime. A model asked for a one-off simulation leaves `duration_seconds` and `max_events` unset
    in most runs (even with the guidance in the tool text), and the
    worker then streams until someone stops it. So a worker created with neither gets `duration_seconds=900` and the result
    says so; `continuous=True` is the explicit way to ask for one that runs until it is stopped. A slow finite worker does
    not take the single burst slot (the registry only grants one to a bounded run faster than the sustained ceiling)."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        continuous = bool(kwargs.pop("continuous", False))
        defaulted = not continuous and not (kwargs.get("duration_seconds") or kwargs.get("max_events"))
        if defaulted:
            kwargs["duration_seconds"] = DEFAULT_WORKER_SECONDS
        result = await fn(*args, **kwargs)
        if isinstance(result, list) and result and isinstance(result[0], dict):
            if defaulted:
                result[0] = {**result[0], "bounded_by_default": {
                    "duration_seconds": DEFAULT_WORKER_SECONDS,
                    "why": "no duration_seconds or max_events was given, so the worker stops by itself after this long. "
                           "Pass duration_seconds or max_events to choose the bound, or continuous=true when the operator "
                           "asked for a worker that runs until it is stopped."}}
            elif continuous and not (kwargs.get("duration_seconds") or kwargs.get("max_events")):
                result[0] = {**result[0], "warning": "This worker is continuous: it runs until it is stopped with kill_worker "
                                                    "(or the host's worker lifetime guard reaps it)."}
        return result
    return wrapper


@_bound_by_default
async def phantom_create_data_worker(
    type: str,
    *,
    destination: str = "XSIAM_WEBHOOK",
    count: int = 1,
    interval: int = 2,
    duration_seconds: Optional[int] = None,
    max_events: Optional[int] = None,
    continuous: bool = False,
    vendor: Optional[str] = None,
    product: Optional[str] = None,
    version: Optional[str] = None,
    fields: Optional[Union[str, List[str]]] = None,
    datetime_iso: Optional[str] = None,
    observables_dict: Optional[Union[Dict[str, Any], str]] = None,
    required_fields: Optional[Union[List[str], str]] = None,
    verify_ssl: bool = False,
    name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    tactic: Optional[str] = None,
    technique: Optional[str] = None,
    procedure: Optional[str] = None,
    schema_override: Optional[List[Dict[str, Any]]] = None,
    webhook_url: Optional[str] = None,
    webhook_key: Optional[str] = None,
    ctx: Context = None,
) -> List[Dict[str, Any]]:
    """
    Create a data worker to continuously send fake logs to a destination.

    EVERY WORKER HAS A LIFETIME. Pass `duration_seconds` (for example 120) or `max_events` to choose it. When you pass neither,
    the worker stops by itself after 900 seconds and the result carries `bounded_by_default`. Only when the operator
    explicitly asks for a worker that keeps running until it is stopped ("keep streaming", "continuously") pass
    `continuous=true`; that worker runs until you stop it with kill_worker.

    This tool creates a worker that generates and sends fake log data at regular intervals
    to a specified destination. Supports UDP Syslog, TCP Syslog  and XSIAM Webhook.

    This tool uses the Phantom API to start a data worker. You can get the supported log types,
    required fields, and observable catalog using the phantom_get_field_info tool.
    Observables must use camelCase keys (e.g., 'srcHost', 'remotePort').

    PREFERRED destination: pass `destination='logdest:<id>'` referencing a
    configured destination from `log_destinations_list` (see the `destination`
    arg for the full selection rule — one match: use it; several: ask; none:
    create a secretless syslog or guide). The platform resolves the reference
    (and injects any credentials) server-side, so you never handle destination
    secrets. 'XSIAM_WEBHOOK' (default) remains the legacy path that posts to
    the WEBHOOK_ENDPOINT/WEBHOOK_KEY env vars on the Phantom service.

    Vendor-faithful streaming (set `schema_override`):
    When the operator says "stream FortiGate logs to udp:host:port",
    look up FortiGate via `data_sources_list(filter='fortigate')` →
    fetch its schema via `data_sources_get_schema(pack, rule, dataset)`
    → pass the resulting `fields` array verbatim as `schema_override`.
    The worker then emits records whose top-level keys match the
    vendor's actual field names (FTNTFGT* for Fortinet, srcip / dstip
    for many firewalls, accountId / arn / region for AWS), so Cortex's
    out-of-the-box ModelingRule for the corresponding pack parses them
    cleanly into XDM. Without `schema_override`, the worker streams
    generic Rosetta observables (works for dashboards, doesn't parse
    through vendor-specific modeling rules).

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "phantom_create_data_worker",
        "arguments": {
          "request": {
            "type": "CEF",
            "destination": "XSIAM_WEBHOOK",
            "_comment": "count is per TICK. 2/4 = 0.5 events/sec, sustained.",
            "count": 2,
            "interval": 4,
            "vendor": "Phantom",
            "product": "EDR",
            "datetime_iso": "2024-01-02 08:00:00",
            "observables_dict": {
              "srcHost": ["192.168.10.15"],
              "dstHost": ["192.168.10.1"],
              "remotePort": ["80", "445"],
              "protocol": ["TCP"]
            },
            "required_fields": ["SRC_HOST", "DST_HOST", "REMOTE_PORT", "PROTOCOL"],
            "name": "Single Worker Scenario",
            "tags": ["worker", "single-step"],
            "tactic": "discovery",
            "technique": "T1046",
            "procedure": "Internal Network Port Scan"
          }
        }
      }
    }

    Example MCP tool call with schema_override (vendor-faithful streaming):
    {
      "method": "tools/call",
      "params": {
        "name": "phantom_create_data_worker",
        "arguments": {
          "request": {
            "type": "SYSLOG",
            "destination": "udp:10.0.0.8:514",
            "count": 5,
            "interval": 2,
            "vendor": "Fortinet",
            "product": "FortiGate",
            "schema_override": [
              {"name": "srcip", "type": "string"},
              {"name": "dstip", "type": "string"},
              {"name": "srcport", "type": "integer"},
              {"name": "dstport", "type": "integer"},
              {"name": "action", "type": "string"}
            ]
          }
        }
      }
    }
    (The fields list comes from data_sources_get_schema's response — paste it verbatim.)

    Keeping identities consistent (`__entities__`, schema_override path only):
    every observables_dict field is otherwise sampled independently per record,
    so a pool of hosts and a pool of users mix freely. To keep a host, its IP
    and its user together — the stable endpoint identity that entity-profiling
    analytics learn from — put them in the reserved `__entities__` key as a list
    of field-maps. One map is drawn per record and all its fields are applied
    together; other keys keep independent sampling. Keys inside each map are
    schema field names; values are plain scalars, not lists.
      "observables_dict": {
        "app": ["ssl"],
        "__entities__": [
          {"source_device_host": "WS-1001", "source_ip": "10.20.14.11", "source_user": "ahmed.alharbi"},
          {"source_device_host": "WS-1002", "source_ip": "10.20.14.12", "source_user": "fatima.alqahtani"}
        ]
      }
    Set it when the operator asks for "consistent users/endpoints", "the same
    people on the same machines", or a fixed persona population. Without
    schema_override the call is rejected — only the vendor-schema generator
    implements the binding.

    Returns:
        List of worker information dictionaries (worker ID, type, status, count, interval, etc.)
    """
    # The signature is individual keyword args (not a single
    # `request: CreateDataWorkerRequest`) so the agent's MCP-proxy layer
    # (which sends FLAT arguments per the connector.yaml spec.tools[].args
    # list) can reach this tool end-to-end. A nested {"request": {...}} shape
    # does not work at the agent's chat path — only via direct connector
    # access where the caller crafts the nested dict by hand.
    #
    # The function body uses `request.X` accessors by rebuilding a
    # CreateDataWorkerRequest from the flat kwargs below. The Pydantic model
    # still validates field types on construction.
    request = CreateDataWorkerRequest(
        type=type,
        destination=destination,
        count=count,
        interval=interval,
        duration_seconds=duration_seconds,
        max_events=max_events,
        vendor=vendor,
        product=product,
        version=version,
        fields=fields,
        datetime_iso=datetime_iso,
        observables_dict=observables_dict,
        required_fields=required_fields,
        verify_ssl=verify_ssl,
        name=name,
        tags=tags,
        tactic=tactic,
        technique=technique,
        procedure=procedure,
        schema_override=schema_override,
        webhook_url=webhook_url,
        webhook_key=webhook_key,
    )
    client = PhantomGraphQLClient(resolve_xlog_url(ctx))

    # Short-circuit to xlog's createDataWorker mutation
    # when a vendor-faithful schema override is supplied. The scenario
    # worker path doesn't carry schema_override; the simpler
    # createDataWorker resolver routes through OverrideSender for
    # udp:/tcp: destinations.
    if request.schema_override and isinstance(request.schema_override, list) and request.schema_override:
        override_query = """
        query CreateDataWorker($input: DataWorkerCreateInput!) {
          createDataWorker(requestInput: $input) {
            worker
            type
            status
            count
            interval
            destination
            createdAt
          }
        }
        """
        # Normalize the field-list shape that data_sources_get_schema
        # returns into the SchemaOverrideInput.vendor_fields shape xlog
        # expects (camelCase per Strawberry's GraphQL convention).
        vendor_fields_input = []
        for f in request.schema_override:
            if not isinstance(f, dict):
                continue
            name = f.get("name")
            if not name:
                continue
            vendor_fields_input.append({
                "name": name,
                "type": f.get("type"),
                "isArray": bool(f.get("is_array", False)),
                "isMeta": bool(f.get("is_meta", False)),
                # See data_faker: gate keys must survive every projection hop.
                "isGate": bool(f.get("is_gate", False)),
                "enumValues": f.get("enum_values"),
                "example": f.get("example"),
            })
        override_variables = {
            "input": {
                "type": request.type.upper(),
                "count": request.count,
                "interval": request.interval,
                # Forwarded so the server can price this as a bounded burst
                # rather than as sustained generation. Omitted when unset.
                **({"durationSeconds": request.duration_seconds}
                   if request.duration_seconds else {}),
                **({"maxEvents": request.max_events}
                   if request.max_events else {}),
                "destination": request.destination,
                "vendor": request.vendor,
                "product": request.product,
                "schemaOverride": {
                    "vendorFields": vendor_fields_input,
                    # Optional metadata hints — useful in /observability
                    # to identify which pack the worker is streaming for.
                    "datasetName": None,
                    "packName": None,
                    "ruleName": None,
                },
                # Forward observables_dict on the schema_override path too.
                # Multi-dataset / classifier discriminators (eventType,
                # Workload, category, Operation, auditCode) ride here so the
                # modeling rule's `filter <field> in (...)` matches and
                # shared-CEF-header siblings (okta_sso) route. Pre-this-fix
                # this branch dropped observablesDict entirely, capping XDM at
                # 0 for every enum-classified vendor. xlog's createDataWorker
                # resolver reads observables_dict → OverrideSender.
                # normalize=False: on this path the observable namespace is the
                # vendor schema supplied in schema_override, NOT the legacy
                # 46-key faker vocabulary, so alias-renaming would destroy pins
                # on fields like `event_id`.
                "observablesDict": _parse_observables_dict(
                    request.observables_dict, normalize=False
                ),
                # Store-driven xsiam_http: MCP-resolved endpoint + key.
                # None when the worker uses a syslog/raw destination or the env
                # default; stripped below so the GraphQL request stays clean.
                "webhookUrl": request.webhook_url,
                "webhookKey": request.webhook_key,
            }
        }
        # Strip None values inside input to keep the GraphQL request clean
        override_variables["input"] = {k: v for k, v in override_variables["input"].items() if v is not None}
        result = await client.execute_query(override_query, override_variables)
        out = result.get("createDataWorker") or {}
        # Match the existing return shape (list of one dict) so the
        # agent's downstream logic stays compatible with the scenario
        # path's output.
        return [out] if out else []

    # Only the override generator (xlog dynamic_schema.py) implements entity
    # binding; the legacy path's typed WorkerObservablesInput would reject the
    # key with an opaque GraphQL error. Fail here, naming the fix.
    if "__entities__" in (_parse_observables_dict(request.observables_dict, normalize=False) or {}):
        raise ValueError(
            "observables_dict['__entities__'] requires schema_override: entity binding is only "
            "implemented by the vendor-schema generator. Fetch the source's fields with "
            "data_sources_get_schema(compact=True) and pass them as schema_override."
        )

    query = """
    query CreateScenarioWorkerFromQuery($name: String!, $tags: [String!], $destination: String!,
                                        $steps: [DetailedQueryScenarioStep!]!,
                                        $webhookUrl: String, $webhookKey: String) {
      createScenarioWorkerFromQuery(requestInput: {
        name: $name
        tags: $tags
        destination: $destination
        steps: $steps
        webhookUrl: $webhookUrl
        webhookKey: $webhookKey
      }) {
        worker
        type
        status
        count
        interval
        destination
        createdAt
      }
    }
    """

    required_fields = _parse_required_fields(request.required_fields)
    observables_dict = _parse_observables_dict(request.observables_dict)
    fields = _parse_fields(request.fields)

    # DEBUG LOGGING: Track observable mapping
    logger.info(f"[MCP-DEBUG] Raw request.observables_dict: {request.observables_dict}")
    logger.info(f"[MCP-DEBUG] Normalized observables_dict: {observables_dict}")
    logger.info(f"[MCP-DEBUG] Required fields: {required_fields}")

    log_entry: Dict[str, Any] = {
        "type": request.type.upper(),
        "vendor": request.vendor,
        "product": request.product,
        "version": request.version,
        "count": request.count,
        "interval": request.interval,
        # Forwarded so the server can price this as a bounded burst rather
        # than as sustained generation. Omitted when unset.
        **({"durationSeconds": request.duration_seconds}
           if request.duration_seconds else {}),
        **({"maxEvents": request.max_events} if request.max_events else {}),
        "datetimeIso": request.datetime_iso,
        "fields": fields,
        "observablesDict": observables_dict,
        "requiredFields": required_fields,
    }
    log_entry = {k: v for k, v in log_entry.items() if v is not None}

    step_payload = {
        "tactic": request.tactic,
        "technique": request.technique,
        "procedure": request.procedure,
        "logs": [log_entry],
    }
    step_payload = {k: v for k, v in step_payload.items() if v is not None}

    variables = {
        "name": request.name or "Single Worker Scenario",
        "tags": request.tags,
        "destination": request.destination,
        "steps": [step_payload],
        # Store-driven xsiam_http (MCP-resolved); None → stripped →
        # GraphQL null → xlog env fallback.
        "webhookUrl": request.webhook_url,
        "webhookKey": request.webhook_key,
    }

    # Remove None values
    variables = {k: v for k, v in variables.items() if v is not None}

    result = await client.execute_query(query, variables)
    return result.get("createScenarioWorkerFromQuery", [])


async def phantom_list_workers(ctx: Context) -> List[Dict[str, Any]]:
    """
    List all active workers.

    This tool retrieves information about all currently running workers.

    Example MCP tool call:
    {
      "method": "tools/call",
      "params": {
        "name": "phantom_list_workers",
        "arguments": {}
      }
    }

    Args:
        ctx: MCP context containing Phantom URL

    Returns:
        List of worker information dictionaries
    """
    client = PhantomGraphQLClient(resolve_xlog_url(ctx))

    query = """
    query ListWorkers {
      listWorkers {
        destination
        status
        type
        count
        interval
        worker
        createdAt
      }
    }
    """

    result = await client.execute_query(query)
    return result.get("listWorkers", [])


class KillWorkerRequest(BaseModel):
    """Request model for killing a running worker."""

    worker_id: str = Field(
        description=(
            "Worker UUID to stop. Get this from phantom_list_workers — "
            "the field is `worker` in the list response. Example: "
            "'7c3b9a52-5b6e-4e1a-8b0c-fd5b9b4b9a2e'."
        )
    )


async def phantom_kill_worker(
    worker_id: str, ctx: Context
) -> Dict[str, Any]:
    """
    Stop a running synthetic-log worker.

    The worker transitions to 'stopped' immediately. In-flight events
    that were already dispatched to the destination keep flying; events
    that hadn't yet been emitted are dropped.

    Repeat-safe but not strictly idempotent: xlog evicts the worker
    from its in-memory registry on stop. A second kill on the same
    worker_id returns status='Worker not found.' (still a 200, no
    exception). Treat the absence as success — if the worker isn't
    there, it isn't running. The agent can ignore the difference.

    Use this when:
      - A worker created with `duration_seconds=0` is running forever
        and you want to stop it without restarting xlog.
      - A misconfigured worker is sending logs to the wrong destination
        and you need to halt it before re-creating with the right
        config.
      - Running workers are filling up the destination and the operator
        wants to clear the deck before the next test.

    Workflow:
      1. phantom_list_workers to find the worker_id (`worker` field).
      2. phantom_kill_worker(worker_id=<that UUID>).
      3. phantom_list_workers to confirm status changed to 'stopped'.

    Example MCP tool call (a bare `worker_id: str` parameter, not a
    nested `request` envelope: the agent's flat-arg-schema dispatch can't
    compose a Pydantic wrapper):
    {
      "method": "tools/call",
      "params": {
        "name": "phantom_kill_worker",
        "arguments": {
          "worker_id": "7c3b9a52-5b6e-4e1a-8b0c-fd5b9b4b9a2e"
        }
      }
    }

    Returns:
        Dict with the worker_id and post-action status. Shape:
        {"worker_id": "<uuid>", "status": "stopped"}.
    """
    client = PhantomGraphQLClient(resolve_xlog_url(ctx))

    # The xlog GraphQL exposes actionWorker(requestInput: {worker, action})
    # → {worker, status}. We hardcode action=STOP because the only sensible
    # remote action is termination (STATUS is achievable via list_workers
    # with less ceremony).
    #
    # Note: actionWorker is a Strawberry @field on the Query class (not
    # @mutation_field), so this is sent as a `query` operation, not
    # `mutation`. The xlog server doesn't accept it as a mutation —
    # GraphQL would error with "Cannot query field 'actionWorker' on
    # type 'Mutation'." This is unusual schema design (state-mutating
    # query) but stable; the connector matches what the server exposes.
    query = """
    query ActionWorker($worker: String!) {
      actionWorker(requestInput: {worker: $worker, action: STOP}) {
        worker
        status
      }
    }
    """

    variables = {"worker": worker_id}

    result = await client.execute_query(query, variables)
    payload = result.get("actionWorker") or {}
    # Normalize the response shape so the agent sees a stable schema
    # regardless of any future schema rename on the xlog side.
    return {
        # The default must be the flat `worker_id` argument, not a
        # `request.worker_id` attribute: Python evaluates the `.get()` default
        # eagerly, so referencing a dropped `request` model would raise
        # `NameError: name 'request' is not defined` on EVERY call (the kill
        # would succeed but the tool would return an error → leaked-worker
        # risk). The validator catches this class
        # (check_connector_tool_args_flat body scan).
        "worker_id": payload.get("worker", worker_id),
        "status": payload.get("status", "unknown"),
    }
