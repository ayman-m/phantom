"""MCP tools for Phantom simulation run state, validation, and reporting."""

import logging
from typing import Any, Dict, List, Optional

from fastmcp import Context
from pydantic import BaseModel, Field

from ._graphql_client import PhantomGraphQLClient
from ._xlog_url_resolver import resolve_xlog_url

logger = logging.getLogger("Phantom MCP")


class DetectionValidationRequest(BaseModel):
    """Record a detection validation result for a Phantom simulation."""

    simulation_id: str = Field(
        description=(
            "Simulation run ID returned by Phantom (NOT a raw ATT&CK technique "
            "id like T1078 — those are not accepted here). Example: "
            "sim_abc123def456. To DISCOVER simulation_ids: call "
            "`phantom_generate_coverage_report` with include_simulations=true; "
            "the returned `simulations[]` array carries each run's id and "
            "ATT&CK mapping. To validate a SPECIFIC technique, filter that "
            "list by its `attack.technique_id` field and pass the matching "
            "sim id here."
        )
    )
    status: str = Field(
        default="review",
        description="Validation status: pass, detected, fail, missed, noisy, or review.",
    )
    query: Optional[str] = Field(
        default=None,
        description="Detection query used to validate the simulation, such as XQL.",
    )
    expected: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Expected detection details, alert names, counts, or ATT&CK mapping.",
    )
    observed: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Observed XSIAM results, alert counts, case IDs, or evidence.",
    )
    missed: Optional[List[str]] = Field(
        default=None,
        description="Missed detections or missing ATT&CK techniques.",
    )
    noisy_fields: Optional[List[str]] = Field(
        default=None,
        description="Fields that were noisy, low-quality, or created parsing friction.",
    )
    recommended_rules: Optional[List[str]] = Field(
        default=None,
        description="Detection or parsing rules recommended after validation.",
    )
    notes: Optional[str] = Field(default=None, description="Analyst notes.")


class SimulationResultRequest(BaseModel):
    """Fetch a persisted Phantom simulation result."""

    simulation_id: str = Field(
        description="Simulation run ID returned by Phantom. Example: sim_abc123def456"
    )


class CoverageReportRequest(BaseModel):
    """Generate a SOC coverage report from stored simulation validations."""

    include_simulations: bool = Field(
        default=False,
        description="When true, include the latest simulation runs alongside the aggregate report.",
    )
    limit: int = Field(default=50, ge=1, le=250, description="Maximum simulations to include.")


async def phantom_run_detection_validation(
    *,
    simulation_id: str,
    status: str = "review",
    query: Optional[str] = None,
    expected: Optional[Dict[str, Any]] = None,
    observed: Optional[Dict[str, Any]] = None,
    missed: Optional[List[str]] = None,
    noisy_fields: Optional[List[str]] = None,
    recommended_rules: Optional[List[str]] = None,
    notes: Optional[str] = None,
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Record a detection validation result for a completed or running Phantom simulation.

    Use this after running XSIAM queries or reviewing generated alerts. The result is
    persisted in Phantom and contributes to the coverage report.

    REQUIRED PARAMETER: `simulation_id` (a Phantom run id like `sim_abc123def456`).
    This tool does NOT accept ATT&CK technique ids directly. If the operator asks to
    validate "T1078" (or any technique), call `phantom_generate_coverage_report` first
    with `include_simulations=true`, find the most recent run whose
    `attack.technique_id` matches, and pass its `id` here.

    TYPICAL WORKFLOW:
      1. phantom_generate_coverage_report(include_simulations=true) → list of sim runs
      2. Pick the relevant simulation_id from the returned list
      3. phantom_run_detection_validation(
             simulation_id=<picked id>,
             expected={"alert": "<rule name>", "technique_id": "T1078"},
             status="review")
      4. memory_store(key="validated:<technique>:<sim_id>", value=<summary>)
    """
    # Signature is flat kwargs (not a single `request: DetectionValidationRequest`) so the agent's MCP-proxy layer
    # (which sends FLAT arguments per connector.yaml spec.tools[].args) reaches
    # this tool. The body keeps using `request.X` accessors by rebuilding the
    # model from the kwargs; the Pydantic model still validates types.
    request = DetectionValidationRequest(
        simulation_id=simulation_id,
        status=status,
        query=query,
        expected=expected,
        observed=observed,
        missed=missed,
        noisy_fields=noisy_fields,
        recommended_rules=recommended_rules,
        notes=notes,
    )
    client = PhantomGraphQLClient(resolve_xlog_url(ctx))
    payload = request.dict(exclude={"simulation_id"}, exclude_none=True)
    return await client.post_json(
        f"/api/v1/simulations/{request.simulation_id}/validations",
        payload,
    )


async def phantom_get_simulation_result(
    *,
    simulation_id: str,
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Get a persisted simulation run, including worker IDs, ATT&CK mapping, Caldera linkage,
    metadata, and validation results.
    """
    # Signature is flat kwargs (not a single `request: SimulationResultRequest`) so the agent's MCP-proxy layer
    # (which sends FLAT arguments per connector.yaml spec.tools[].args) reaches
    # this tool. The body keeps using `request.X` accessors by rebuilding the
    # model from the kwargs; the Pydantic model still validates types.
    request = SimulationResultRequest(simulation_id=simulation_id)
    client = PhantomGraphQLClient(resolve_xlog_url(ctx))
    return await client.get_json(f"/api/v1/simulations/{request.simulation_id}")


async def phantom_generate_coverage_report(
    *,
    include_simulations: bool = False,
    limit: int = 50,
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Generate an aggregate SOC coverage report from Phantom's stored simulation and
    detection validation results.
    """
    # Signature is flat kwargs (not a single `request: CoverageReportRequest`) so the agent's MCP-proxy layer
    # (which sends FLAT arguments per connector.yaml spec.tools[].args) reaches
    # this tool. The body keeps using `request.X` accessors by rebuilding the
    # model from the kwargs; the Pydantic model still validates types/bounds.
    request = CoverageReportRequest(include_simulations=include_simulations, limit=limit)
    client = PhantomGraphQLClient(resolve_xlog_url(ctx))
    report = await client.get_json("/api/v1/coverage-report")
    if request.include_simulations:
        report["simulations"] = (await client.get_json("/api/v1/simulations", params={"limit": request.limit})).get(
            "simulations",
            [],
        )
    return report
