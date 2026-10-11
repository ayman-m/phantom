import strawberry
from enum import Enum
from typing import Optional, List
from strawberry.scalars import JSON

from app.schema_loader import build_enum, build_input_class, load_supported_fields
# DataWorkerCreateInput re-uses the SchemaOverrideInput
# already declared in datafaker.py for generate_fake_data_v2. Importing
# vs duplicating keeps Strawberry's type-deduplication happy (one input
# class, one GraphQL type).
from app.types.datafaker import SchemaOverrideInput


_SUPPORTED_FIELDS = load_supported_fields()
WorkerObservablesInput = build_input_class(
    "WorkerObservablesInput",
    _SUPPORTED_FIELDS,
    description="Data observables dictionary.",
)

WorkerRequiredFieldEnum = build_enum(
    "WorkerRequiredFieldEnum",
    _SUPPORTED_FIELDS,
    description="Enum representing the types of required fields.",
)

@strawberry.enum(description="Enum representing the types of workers.")
class WorkerTypeEnum(Enum):
    SYSLOG = 'syslog'
    CEF = 'cef'
    LEEF = 'leef'
    WINEVENT = 'winevent'
    JSON = 'json'
    Incident = 'incident'
    XSIAM_Parsed = 'xsiam_parsed'
    XSIAM_CEF = 'xsiam_cef'
    # RAW ships the vendor's OWN log line verbatim, syslog-framed, for the 88
    # data sources whose Cortex rules regex `_raw_log` (a CEF event leaves
    # `_raw_log` EMPTY, so those rules map nothing over CEF). Only meaningful
    # with a schema_override carrying a `_raw_log` field and a udp:/tcp:
    # destination -- OverrideSender.format_record() is what dispatches it.
    # The enum member is what makes `type: "RAW"` reachable at the GraphQL boundary.
    RAW = 'raw'


@strawberry.enum(description="Enum representing the actions for a worker.")
class WorkerActionEnum(Enum):
    STOP = 'stop'
    STATUS = 'status'


@strawberry.input(description="Input object for creating a data worker. Destination supports XSIAM_WEBHOOK.")
class DataWorkerCreateInput:
    type: WorkerTypeEnum
    count: int = 1
    interval: int = 2
    destination: str
    # Declaring EITHER of these marks the worker as a bounded BURST, which is
    # priced against the (much higher) burst rate ceiling instead of the
    # sustained one — see app/worker_registry.py. This is how a caller opts
    # into a high rate: by promising the run is finite. Leave both unset for
    # ordinary sustained generation.
    duration_seconds: Optional[int] = None
    max_events: Optional[int] = None
    fields: Optional[str] = None
    vendor: Optional[str] = None
    product: Optional[str] = None
    version: Optional[str] = None
    observables_dict: Optional[JSON] = None
    required_fields: Optional[str] = None
    datetime_iso: Optional[str] = None
    verify_ssl: Optional[bool] = False
    # When supplied, the resolver routes through
    # OverrideSender for UDP/TCP destinations and emits records whose
    # top-level keys match the vendor's actual field names (extracted
    # from a Cortex ModelingRule via the agent's marketplace), rather
    # than Rosetta's generic observable universe. Same input class
    # already accepted by generate_fake_data_v2. For XSIAM /
    # XSIAM_WEBHOOK destinations this field is ignored (those
    # paths have their own format normalization).
    schema_override: Optional[SchemaOverrideInput] = None
    # Store-driven log-destination resolution. When the
    # destination is XSIAM_WEBHOOK, the MCP resolver injects the
    # webhook endpoint + auth key resolved from a configured
    # log-destination (type xsiam_http) here, so generation routes to
    # the operator's chosen destination instead of the container-wide
    # WEBHOOK_ENDPOINT / WEBHOOK_KEY env defaults. Both optional: when
    # omitted the XSIAM_WEBHOOK branch falls back to the env values
    # (the default behavior). GraphQL: webhookUrl / webhookKey.
    webhook_url: Optional[str] = None
    webhook_key: Optional[str] = None


@strawberry.input(description="Input object for creating a scenario worker. Destination supports XSIAM_WEBHOOK.")
class ScenarioWorkerCreateInput:
    count: int = 1
    interval: int = 2
    scenario: str
    destination: str
    vendor: Optional[str] = None
    datetime_iso: Optional[str] = None
    verify_ssl: Optional[bool] = False


@strawberry.input(description="Input object for performing an action on a data worker.")
class DataWorkerActionInput:
    worker: str
    action: WorkerActionEnum


@strawberry.type(description="Output object containing information about a data worker.")
class WorkerOutput:
    type: str
    worker: str
    status: str
    count: str
    interval: str
    verifySsl: str
    destination: str
    createdAt: str


@strawberry.type(description="Output object containing status information about a data worker.")
class WorkerStatusOutput:
    worker: str
    status: str

@strawberry.input(description="Input object for generating fake data.")
class WorkerFakerInput:
    type: WorkerTypeEnum
    vendor: Optional[str] = None
    product: Optional[str] = None
    version: Optional[str] = None
    count: int = 1
    interval: int = 2
    datetime_iso: Optional[str] = None
    fields: Optional[str] = None
    observables_dict: Optional[WorkerObservablesInput] = None
    required_fields: Optional[List[WorkerRequiredFieldEnum]] = None
    verify_ssl: Optional[bool] = False

@strawberry.input(description="Scenario step object for generating fake scenario data.")
class DetailedQueryScenarioStep:
    tactic: Optional[str] = None
    tactic_id: Optional[str] = None
    technique: Optional[str] = None
    technique_id:Optional[str] = None
    procedure:Optional[str] = None
    type: Optional[str] = None
    logs: List[WorkerFakerInput]


@strawberry.input(description="Input object for creating a scenario worker from a query. Destination supports XSIAM_WEBHOOK.")
class ScenarioQueryWorkerCreateInput:
    name: str
    destination: str
    steps: List[DetailedQueryScenarioStep]
    tags:  Optional[List[str]] = None
    # Store-driven log-destination resolution — same role as on
    # DataWorkerCreateInput. createDataWorker (schema_override path) and
    # this query-scenario path are the two routes phantom_create_data_worker
    # takes, so both honor the MCP-resolved xsiam_http endpoint + key.
    # GraphQL: webhookUrl / webhookKey. Both optional → env fallback.
    webhook_url: Optional[str] = None
    webhook_key: Optional[str] = None
