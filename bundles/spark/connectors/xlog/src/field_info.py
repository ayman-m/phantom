"""MCP tools for querying supported fields and observables by log type."""

import logging
from typing import Any, Dict, List, Optional

from fastmcp import Context
from pydantic import BaseModel, Field

from ._graphql_client import PhantomGraphQLClient
from ._xlog_url_resolver import resolve_xlog_url

logger = logging.getLogger("Phantom MCP")


def _snake_to_lower_camel(s: str) -> str:
    """Convert snake_case to lowerCamelCase to match Strawberry's
    auto-camelCase transformation of input-type field names.

    Rosetta exposes fields as `lower_snake_case` (`authentication_method`,
    `bytes_received`). Strawberry's default `auto_camel_case=True` rewrites
    these in the GraphQL schema as `authenticationMethod`, `bytesReceived`.
    The agent has to send the camelCase form when populating
    `observables_dict`. A bare convention string ("camelCase") would leave
    the agent to guess the exact transformation. This helper makes the
    camelCase whitelist explicit so the agent can match against an enumerated list rather
    than infer.
    """
    if not s:
        return s
    parts = s.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


class FieldInfoRequest(BaseModel):
    """Request model for querying field support details."""

    log_type: Optional[str] = Field(
        default=None,
        description=(
            "Optional log type to query. Must be one of: SYSLOG, CEF, LEEF, WINEVENT, JSON, Incident, "
            "XSIAM_Parsed, XSIAM_CEF (case-insensitive). When omitted, only supported types are returned."
        ),
    )
    include_observables: bool = Field(
        default=True,
        description=(
            "Deprecated. Observable catalog is no longer returned."
        ),
    )


async def _get_supported_fields(ctx: Context) -> list[str]:
    client = PhantomGraphQLClient(resolve_xlog_url(ctx))
    query = """
    query GetSupportedFields {
      getSupportedFields
    }
    """
    try:
        data = await client.execute_query(query)
        fields = data.get("getSupportedFields", [])
        if not isinstance(fields, list) or not all(isinstance(item, str) for item in fields):
            logger.warning("Phantom getSupportedFields returned unexpected payload.")
            return []
        return fields
    except Exception as exc:
        logger.warning(f"Failed to fetch supported fields from Phantom: {exc}")
        return []


async def phantom_get_field_info(
    *,
    log_type: Optional[str] = None,
    include_observables: bool = True,
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Get field support by log type.

    Use this tool to discover supported log types and check parameter support for a specific format.

    IMPORTANT DIFFERENCES BY LOG TYPE:

    1. WINEVENT:
       - Does NOT support 'required_fields' parameter
       - ONLY supports: observables_dict, datetime_iso, count
       - Cannot specify vendor, product, version, or fields

    2. SYSLOG:
       - Supports: required_fields, observables_dict, datetime_iso, count
       - Does NOT support: vendor, product, version

    3. CEF, LEEF, JSON:
       - Supports ALL parameters: required_fields, observables_dict, vendor, product, version,
         datetime_iso, count, fields

    4. Incident:
       - Supports ALL parameters including 'fields' for custom incident fields

    5. XSIAM_Parsed:
       - Has predefined mandatory fields (automatically included)
       - Supports: observables_dict, vendor, product, datetime_iso, count

    Args:
        request: Request containing the log type (optional)
        ctx: MCP context (not used, but required by MCP)

    Returns:
        Dictionary containing:
        - naming_convention: how `required_fields` (UPPER_SNAKE_CASE) and
          `observables_dict` (camelCase) keys must be formatted, plus a
          pointer to the matching whitelist below.
        - available_fields: ALWAYS PRESENT. The enumerated rosetta-supported
          field whitelist in both forms:
            - required_fields_enum: list[str] of UPPER_SNAKE_CASE values
              accepted in the `required_fields` argument.
            - observables_dict_keys: list[str] of camelCase keys accepted
              in the `observables_dict` argument.
            - count: number of fields.
          An explicit whitelist (rather than a convention string) eliminates
          retry-storms from the agent inventing close-but-not-quite field names.
        - supported_types: list of supported log type names (when log_type
          is omitted).
        - log_type: the queried log type (when provided).
        - supports_required_fields / supports_observables / supports_vendor
          / supports_product / supports_version / supports_fields /
          supports_datetime: per-format support flags (when log_type is
          provided).
        - description: detailed description of parameter support.
        - usage_notes: important notes about using this log type.

    Example Request:
        {
          "log_type": "WINEVENT",
          "include_observables": false
        }

    Example Response:
        {
          "log_type": "WINEVENT",
          "supports_required_fields": false,
          "supports_observables": true,
          "supports_vendor": false,
          "supports_product": false,
          "supports_version": false,
          "supports_fields": false,
          "supports_datetime": true,
          "description": "Windows Event logs in XML format. Only supports observables injection.",
          "usage_notes": "WINEVENT format does NOT accept required_fields. Use observables_dict to inject specific values like eventId, user, remoteIp, etc."
        }

    Example MCP tool call:
        {
          "method": "tools/call",
          "params": {
            "name": "phantom_get_field_info",
            "arguments": {
              "log_type": "CEF",
              "include_observables": true
            }
          }
        }
    """
    # Signature is flat kwargs (not a single `request: FieldInfoRequest`)
    # so the agent's MCP-proxy layer (which sends FLAT arguments
    # per connector.yaml spec.tools[].args) reaches this tool. The body keeps
    # using `request.X` accessors by rebuilding the model from the kwargs; the
    # Pydantic model still validates types on construction.
    request = FieldInfoRequest(
        log_type=log_type,
        include_observables=include_observables,
    )
    log_type = request.log_type.upper() if request.log_type else None

    supported_fields = await _get_supported_fields(ctx)
    # Surface the enumerated whitelists explicitly. `naming_convention` strings
    # ("UPPER_SNAKE_CASE" / "camelCase") alone, without the actual values, leave
    # the agent to guess the transformation per field, and it occasionally
    # invents fields that are close-but-not-quite (e.g. `sessionState` when
    # rosetta has `session_start`/`session_end`/`service_state`); such
    # hallucinations reject the entire `$steps` call with an opaque error,
    # costing several retries before the agent guesses which field to drop.
    # With the enumerated lists below the agent can match against the
    # whitelist before sending —
    # `sessionState` doesn't appear in `observables_dict_keys`, so the
    # agent declines it before the GraphQL round-trip.
    required_fields_enum: List[str] = sorted({f.upper() for f in supported_fields})
    observables_dict_keys: List[str] = sorted(
        {_snake_to_lower_camel(f) for f in supported_fields}
    )
    available_fields_block: Dict[str, Any] = {
        "count": len(supported_fields),
        "required_fields_enum": required_fields_enum,
        "observables_dict_keys": observables_dict_keys,
    }
    response: Dict[str, Any] = {
        "naming_convention": {
            "required_fields": (
                "UPPER_SNAKE_CASE — must be one of available_fields.required_fields_enum"
            ),
            "observables_dict": (
                "camelCase — must be one of available_fields.observables_dict_keys"
            ),
        },
        "available_fields": available_fields_block,
    }

    # Field support matrix based on Phantom schema.py implementation
    field_info = {
        "SYSLOG": {
            "supports_required_fields": True,
            "supports_observables": True,
            "supports_vendor": False,
            "supports_product": False,
            "supports_version": False,
            "supports_fields": False,
            "supports_datetime": True,
            "description": "Standard syslog format (RFC 3164/5424) for Unix/Linux system logs.",
            "usage_notes": (
                "Supports both required_fields and observables_dict. "
                "Does not support vendor/product/version parameters. "
                "Use required_fields to ensure specific fields are present, and observables_dict to inject specific values."
            ),
        },
        "CEF": {
            "supports_required_fields": True,
            "supports_observables": True,
            "supports_vendor": True,
            "supports_product": True,
            "supports_version": True,
            "supports_fields": False,
            "supports_datetime": True,
            "description": "Common Event Format - structured log format for security events.",
            "usage_notes": (
                "Fully supports all parameters. "
                "Vendor and product can be customized (defaults to 'Phantom' if not specified). "
                "Use required_fields for mandatory fields and observables_dict for specific values."
            ),
        },
        "LEEF": {
            "supports_required_fields": True,
            "supports_observables": True,
            "supports_vendor": True,
            "supports_product": True,
            "supports_version": True,
            "supports_fields": False,
            "supports_datetime": True,
            "description": "Log Event Extended Format - structured log format for security events.",
            "usage_notes": (
                "Fully supports all parameters. "
                "Vendor and product can be customized (defaults to 'Phantom' if not specified). "
                "Use required_fields for mandatory fields and observables_dict for specific values."
            ),
        },
        "WINEVENT": {
            "supports_required_fields": False,
            "supports_observables": True,
            "supports_vendor": False,
            "supports_product": False,
            "supports_version": False,
            "supports_fields": False,
            "supports_datetime": True,
            "description": "Windows Event logs in XML format with security and system events.",
            "usage_notes": (
                "CRITICAL: WINEVENT does NOT support required_fields parameter. "
                "ONLY supports observables_dict and datetime_iso. "
                "Use observables_dict to inject specific values like eventId, user, remoteIp, winProcess, etc. "
                "Cannot customize vendor, product, or version."
            ),
        },
        "JSON": {
            "supports_required_fields": True,
            "supports_observables": True,
            "supports_vendor": True,
            "supports_product": True,
            "supports_version": True,
            "supports_fields": False,
            "supports_datetime": True,
            "description": "Generic JSON-formatted security logs with flexible structure.",
            "usage_notes": (
                "Fully supports all parameters. "
                "Vendor and product can be customized. "
                "Use required_fields for mandatory fields and observables_dict for specific values."
            ),
        },
        "INCIDENT": {
            "supports_required_fields": True,
            "supports_observables": True,
            "supports_vendor": True,
            "supports_product": True,
            "supports_version": True,
            "supports_fields": True,
            "supports_datetime": True,
            "description": "Security incident records with full context including multiple event types.",
            "usage_notes": (
                "Fully supports all parameters including 'fields' for custom incident fields. "
                "Incidents contain multiple event types (syslog, CEF, LEEF, etc.). "
                "Use fields parameter for comma-separated custom incident fields."
            ),
        },
        "XSIAM_PARSED": {
            "supports_required_fields": False,
            "supports_observables": True,
            "supports_vendor": True,
            "supports_product": True,
            "supports_version": False,
            "supports_fields": False,
            "supports_datetime": True,
            "description": "Pre-parsed logs optimized for ingestion with predefined mandatory fields.",
            "usage_notes": (
                "Has predefined mandatory fields that are automatically included. "
                "Does NOT support required_fields parameter (uses predefined ones). "
                "Supports vendor, product, observables_dict, and datetime_iso. "
                "Automatically adds event_timestamp field for compatibility."
            ),
        },
        "XSIAM_CEF": {
            "supports_required_fields": True,
            "supports_observables": True,
            "supports_vendor": True,
            "supports_product": True,
            "supports_version": True,
            "supports_fields": False,
            "supports_datetime": True,
            "description": "CEF format optimized for security platform alert ingestion.",
            "usage_notes": (
                "CEF format specifically designed for security platforms. "
                "Supports all standard CEF parameters. "
                "Use for sending alerts via CEF-based ingestion APIs."
            ),
        },
    }

    if log_type:
        if log_type not in field_info:
            response.update({
                "log_type": log_type,
                "error": f"Unknown log type '{log_type}'. Supported types: {', '.join(field_info.keys())}",
                "supported_types": list(field_info.keys()),
            })
            return response
        info = field_info[log_type].copy()
        info["log_type"] = log_type
        response.update(info)
    else:
        response["supported_types"] = list(field_info.keys())
        response["description"] = "Provide log_type to get parameter support for that format."

    return response
