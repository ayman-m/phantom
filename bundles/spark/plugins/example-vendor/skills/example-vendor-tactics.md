---
title: Example vendor tactics quick-reference
category: foundation
description: |
  Reference skill from the example-vendor plugin. Demonstrates how a
  plugin contributes a skill markdown that the bundled skill loader
  picks up after the plugin's contributions land in
  /app/skills/plugins/example-vendor/.

# Round-15 / Phase L — keywords for conditional activation. Operators
# whose recent prompts mention any of these terms will see this skill
# in `load_simulation_skills` responses (or have it injected into the
# system prompt on relevant turns).
when:
  keywords:
    - fortigate
    - auth
    - spray
    - okta
    - coverage
    - validation
    - tactics
---

# Example vendor tactics

Quick-reference for SOC tactics you'll often combine across the
xlog + caldera + xsiam stack.

## Common scenarios

- **Auth spray**: `xlog.create_scenario_worker` with scenario
  `fortigate-auth-spray` or `okta-credential-stuffing`. Drives
  repeated failed-then-successful logins from a single source IP.

- **Lateral movement**: `caldera.start_operation` with the
  `discovery + execution` adversary. Pairs naturally with an
  XSIAM XQL query for `process_name in (psexec.exe, wmiexec.py)`.

- **Data exfiltration**: chain a `xlog.create_worker` (DNS
  beaconing pattern) with `xsiam.execute_xql_query` against
  the dns_logs dataset to confirm beacon detection latency.

## Validation pattern

After every scenario:

1. Wait ~120 seconds for log ingestion.
2. Run an XQL query against the relevant dataset to confirm
   events arrived.
3. Pull the rule firings: `xsiam.list_rules` → for each
   referenced rule, query alerts in the scenario's window.
4. Compute coverage: alerted_events / total_events.

## Common mistakes

- Using the wrong destination. Production tenants reject most
  synthetic events; always run against the `playground` tenant
  configured in PLAYGROUND_ID.

- Forgetting the time-window. Without `_time >= ago(5m)` your
  XQL pulls historic data and inflates the false-positive count.

- Not stopping the worker. Long-running workers accumulate
  hundreds of thousands of events. Always `xlog.delete_worker`
  or use `/tasks abort <id>` after validation.
