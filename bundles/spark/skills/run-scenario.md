# Run Scenario

Use this skill for scenario packages that generate coordinated
multi-event telemetry.

Procedure:

1. Select a bundled scenario package or ask the operator to choose one.
2. Summarize ATT&CK techniques, expected observables, and target log
   sources before execution.
3. Call `phantom_create_scenario_worker` with the scenario name.
4. Poll or inspect with `phantom_get_simulation_result` when available.
5. Return simulation ID, worker IDs, scenario name, and next validation
   steps.

## Destination

Bundled scenario packages ship to the platform's default destination.
When the operator wants the telemetry to land at a SPECIFIC configured
Log Destination, resolve it exactly as in the **generate-logs** skill
(`log_destinations_list` → one matches: use it; several: ask; none:
create a secretless syslog or guide) and start the stream with
`phantom_create_data_worker` passing `destination="logdest:<id>"` — the
platform resolves the address and injects any credentials server-side.
Never hardcode a destination when a configured one exists.

