"""Tools temporarily removed from MCP registration.

NOTE: This module is documentation-only — it isn't imported by main.py
or registered with the MCP server. The underlying tool
source lives in `bundles/spark/connectors/<id>/src/`, so the imports below
point at the bundle paths. Many of the tools listed here are in fact
registered (the spec.tools[] in each connector.yaml is broader than the
"disabled" list); treat the connector.yaml files as the source of truth.
"""

from connectors.caldera.src import connector as caldera_tools
from connectors.xlog.src import data_faker, scenarios

# Phantom tools
phantom_generate_fake_data = data_faker.phantom_generate_fake_data
phantom_generate_scenario_fake_data = scenarios.phantom_generate_scenario_fake_data

# Caldera tools
caldera_health_check = caldera_tools.caldera_health_check
caldera_get_ability_by_id = caldera_tools.caldera_get_ability_by_id
caldera_get_adversary_by_ability_id = caldera_tools.caldera_get_adversary_by_ability_id
caldera_get_adversary_by_id = caldera_tools.caldera_get_adversary_by_id
caldera_get_agent_by_paw = caldera_tools.caldera_get_agent_by_paw
caldera_get_operation_links = caldera_tools.caldera_get_operation_links
caldera_get_operation_link = caldera_tools.caldera_get_operation_link
caldera_get_planner_by_id = caldera_tools.caldera_get_planner_by_id
caldera_get_plugin_by_name = caldera_tools.caldera_get_plugin_by_name
caldera_get_operation_potential_links_by_paw = caldera_tools.caldera_get_operation_potential_links_by_paw
caldera_get_schedule_by_id = caldera_tools.caldera_get_schedule_by_id
