"""Xlog connector — aggregator module.

The xlog connector covers a wider surface than caldera/xsiam (workers,
scenarios, simulation runs, observables, field metadata, data-faker
helpers) so its source is split across one module per concern. This
file re-exports the public tool functions under one namespace so the
embedded MCP and `connector.yaml.source.entrypoint` can both point at
a single import target.

When the standalone embedded MCP loads this connector, it imports
`bundles.spark.connectors.xlog.src.connector` (or, in the legacy
phantom-mcp shim, this module is referenced via `connector_loader.py`).
The module-level names below MUST stay in sync with
`bundles/spark/connectors/xlog/connector.yaml:spec.tools[].name` (with
the legacy `phantom_` prefix preserved on the function names since the
connector_loader maps `xlog.<tool>` → `phantom_<tool>` callable).
"""

from .field_info import phantom_get_field_info
from .observables_catalog import phantom_generate_observables
from .scenarios import (
    phantom_create_scenario_worker,
    phantom_generate_scenario_fake_data,
)
from .simulation_runs import (
    phantom_generate_coverage_report,
    phantom_get_simulation_result,
    phantom_run_detection_validation,
)
from .workers import (
    phantom_create_data_worker,
    phantom_kill_worker,
    phantom_list_workers,
)
# vendor-faithful log simulation via dynamic schema
from .data_faker import phantom_generate_fake_data_v2

__all__ = [
    "phantom_create_data_worker",
    "phantom_list_workers",
    "phantom_kill_worker",
    "phantom_create_scenario_worker",
    "phantom_generate_scenario_fake_data",
    "phantom_generate_observables",
    "phantom_get_field_info",
    "phantom_run_detection_validation",
    "phantom_get_simulation_result",
    "phantom_generate_coverage_report",
    # vendor-faithful log simulation
    "phantom_generate_fake_data_v2",
]
