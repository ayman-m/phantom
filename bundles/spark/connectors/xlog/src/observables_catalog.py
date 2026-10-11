"""MCP tools for generating observables."""

import logging
from typing import Any, Dict

from fastmcp import Context
from pydantic import BaseModel, Field

from ._graphql_client import PhantomGraphQLClient
from ._xlog_url_resolver import resolve_xlog_url

logger = logging.getLogger("Phantom MCP")


class GenerateObservablesRequest(BaseModel):
    """Request model for generating observables from threat intel feeds."""

    count: int = Field(
        default=10,
        description="Number of observables to generate. Example: 10",
        ge=1,
        le=1000,
    )
    observable_type: str = Field(
        description=(
            "Type of observable to generate. Must be one of: IP, URL, SHA256, CVE, TERMS. "
            "- IP: Malicious/benign IP addresses from threat intel feeds\n"
            "- URL: Malicious/benign URLs\n"
            "- SHA256: File hashes (malware samples or known-good files)\n"
            "- CVE: CVE identifiers\n"
            "- TERMS: Security-related search terms (MITRE techniques, threat names)"
        )
    )
    known: str = Field(
        default="BAD",
        description=(
            "Whether to generate known-malicious or known-benign observables. "
            "Must be one of: BAD, GOOD. "
            "- BAD: Known malicious indicators (default)\n"
            "- GOOD: Known benign/safe indicators"
        )
    )


async def phantom_generate_observables(
    *,
    observable_type: str,
    count: int = 10,
    known: str = "BAD",
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Generate observables (IPs, URLs, hashes, CVEs, terms) from threat intelligence feeds.

    This tool leverages rosetta-ce's Observables.generator() to fetch real indicators
    from curated threat intel sources. If sources are unavailable, it falls back to
    generating realistic fake values.

    Use cases:
    - Generate malicious IPs for testing detection rules
    - Create realistic threat scenarios with known-bad URLs
    - Populate test environments with sample IOCs
    - Generate benign indicators for allowlist testing

    Args:
        request: Request containing count, observable_type, and known status
        ctx: MCP context

    Returns:
        Dictionary containing:
        - observables: List of generated observable values
        - observable_type: The type of observables generated
        - known: Whether they are BAD (malicious) or GOOD (benign)
        - count: Number of observables returned

    Example Request:
        {
          "count": 10,
          "observable_type": "IP",
          "known": "BAD"
        }

    Example Response:
        {
          "observables": ["192.168.1.100", "10.0.0.50", ...],
          "observable_type": "ip",
          "known": "bad",
          "count": 10
        }
    """
    # Signature is flat kwargs (not a single `request:
    # GenerateObservablesRequest`) so the agent's MCP-proxy layer
    # (which sends FLAT arguments per connector.yaml spec.tools[].args) reaches
    # this tool. The body keeps using `request.X` accessors by rebuilding the
    # model from the kwargs; the Pydantic model still validates types/bounds on
    # construction.
    request = GenerateObservablesRequest(
        count=count,
        observable_type=observable_type,
        known=known,
    )
    # Validate observable_type
    valid_types = ["IP", "URL", "SHA256", "CVE", "TERMS"]
    observable_type = request.observable_type.upper()
    if observable_type not in valid_types:
        return {
            "error": f"Invalid observable_type '{request.observable_type}'. Must be one of: {', '.join(valid_types)}",
            "valid_types": valid_types,
        }

    # Validate known
    valid_known = ["BAD", "GOOD"]
    known = request.known.upper()
    if known not in valid_known:
        return {
            "error": f"Invalid known value '{request.known}'. Must be one of: {', '.join(valid_known)}",
            "valid_known": valid_known,
        }

    # Build GraphQL query
    query = """
    query GenerateObservables($input: GenerateObservablesInput!) {
        generateObservables(requestInput: $input) {
            observables
            observableType
            known
            count
        }
    }
    """

    variables = {
        "input": {
            "count": request.count,
            "observableType": observable_type,
            "known": known,
        }
    }

    try:
        client = PhantomGraphQLClient(resolve_xlog_url(ctx))
        result = await client.execute_query(query, variables)

        logger.info(
            f"Generated {result.get('generateObservables', {}).get('count', 0)} {observable_type} observables (known={known})"
        )
        return result.get("generateObservables", {})

    except Exception as e:
        logger.error(f"Error generating observables: {e}")
        return {"error": str(e), "query": query, "variables": variables}

