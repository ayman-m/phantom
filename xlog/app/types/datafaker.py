import strawberry
from enum import Enum
from typing import Optional, List
from strawberry.scalars import JSON

from app.schema_loader import build_enum, build_input_class, load_supported_fields

@strawberry.enum(description="Enum representing the type of observable to generate.")
class ObservableTypeEnum(Enum):
    IP = "ip"
    URL = "url"
    SHA256 = "sha256"
    CVE = "cve"
    TERMS = "terms"


@strawberry.enum(description="Enum representing whether the observable is known malicious or benign.")
class ObservableKnownEnum(Enum):
    BAD = "bad"
    GOOD = "good"

_SUPPORTED_FIELDS = load_supported_fields()
RequiredFieldEnum = build_enum(
    "RequiredFieldEnum",
    _SUPPORTED_FIELDS,
    description="Enum representing the types of required fields.",
)

@strawberry.enum(description="Enum representing the types of fake data.")
class FakerTypeEnum(Enum):
    SYSLOG = 'syslog'
    CEF = 'cef'
    LEEF = 'leef'
    WINEVENT = 'winevent'
    JSON = 'json'
    Incident = 'incident'
    XSIAM_Parsed = 'xsiam_parsed'
    XSIAM_CEF = 'xsiam_cef'


ObservablesInput = build_input_class(
    "ObservablesInput",
    _SUPPORTED_FIELDS,
    description="Data observables dictionary.",
)

@strawberry.input(description="Input object for generating fake data.")
class DataFakerInput:
    type: FakerTypeEnum
    vendor: Optional[str] = None
    product: Optional[str] = None
    version: Optional[str] = None
    count: Optional[int] = 1
    datetime_iso: Optional[str] = None
    fields: Optional[str] = None
    observables_dict: Optional[ObservablesInput] = None
    required_fields: Optional[List[RequiredFieldEnum]] = None


@strawberry.type(description="Output object containing the generated fake data.")
class DataFakerOutput:
    data: List[JSON]
    type: str
    count: int


# ─── Dynamic schema override ─────────────────────────────────────────
#
# Allows a caller (the simulate_vendor_logs skill) to override
# the Rosetta-bundled field universe with the vendor-faithful schema
# extracted from a Cortex ModelingRule. When schema_override is present,
# generate_fake_data_v2 emits records whose top-level keys match the
# vendor's actual field names rather than Rosetta's generic ones — so
# simulated logs look like what the vendor actually emits AND the
# matching modeling rule parses them into XDM correctly.

@strawberry.input(
    description="One vendor field within a dynamic schema override.",
)
class SchemaOverrideField:
    name: str
    type: Optional[str] = None
    is_array: Optional[bool] = False
    is_meta: Optional[bool] = False
    # A field the parsing/modeling rule FILTERS on. Its `example` is the only
    # value the rule accepts, so the generator pins the field to it rather than
    # synthesizing a token -- a synthesized value is discarded at ingest by
    # no_hit=drop, with no raw row and no error to diagnose.
    #
    # These two MUST be declared here even though only the generator reads them:
    # Strawberry builds the input object from this class, so any key absent from
    # it is silently dropped at the GraphQL boundary. is_gate reached the served
    # schema and the generator knew how to honour it, and pinning still did
    # nothing, because the flag died crossing this line.
    is_gate: Optional[bool] = False
    example: Optional[str] = None
    # Allowed values for a `type: enum` field. Same reasoning as is_gate above:
    # the generator honours it, but it dies here unless declared. Without it an
    # enum field falls through to the random-token branch and populates its XDM
    # target with a meaningless value -- which reads as working.
    enum_values: Optional[List[str]] = None


@strawberry.input(
    description=(
        "Schema override for vendor-faithful log simulation. "
        "When supplied, generate_fake_data_v2 emits records whose "
        "top-level keys match the vendor's actual field names rather "
        "than Rosetta's predefined universe."
    ),
)
class SchemaOverrideInput:
    vendor_fields: List[SchemaOverrideField]
    dataset_name: Optional[str] = None
    pack_name: Optional[str] = None
    rule_name: Optional[str] = None


@strawberry.type(
    description="Output for generate_fake_data_v2 — same data shape as v1 plus a meta block.",
)
class DataFakerOutputV2:
    data: List[JSON]
    type: str
    count: int
    # Diagnostic meta — tells the caller how the override was applied
    # (or whether Rosetta-fallback fired). The simulate_vendor_logs
    # skill echoes these back to the operator: "Generated 50 logs against
    # FortiGate schema (172 vendor fields applied)."
    schema_applied: bool
    schema_dataset: Optional[str] = None
    vendor_field_count: Optional[int] = None
    fallback_reason: Optional[str] = None


@strawberry.input(description="Scenario step object for generating fake scenario data.")
class DetailedScenarioStep:
    tactic: Optional[str] = None
    tactic_id: Optional[str] = None
    technique: Optional[str] = None
    technique_id:Optional[str] = None
    procedure:Optional[str] = None
    type: Optional[str] = None
    logs: List[DataFakerInput]


@strawberry.input(description="Scenario input object for generating fake scenario data.")
class DetailedScenarioInput:
    name: str
    tags:  Optional[List[str]] = None
    steps: List[DetailedScenarioStep]


@strawberry.type(description="Output object containing the generated fake data.")
class DetailedScenarioOutput:
    steps: List[JSON]
    name: str
    tags: Optional[List[str]] = None


@strawberry.input(description="Input object for generating observables from threat intel feeds.")
class GenerateObservablesInput:
    count: int
    observable_type: ObservableTypeEnum
    known: Optional[ObservableKnownEnum] = ObservableKnownEnum.BAD


@strawberry.type(description="Output object containing generated observables.")
class GenerateObservablesOutput:
    observables: List[str]
    observable_type: str
    known: str
    count: int
