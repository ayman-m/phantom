---
id: XQL-305-e3a8d9bb
title: Agent Auditing Stopped (Last 24 Hours)
category: investigation
dataset: agent_auditing
tags:
  - config
  - filter
  - fields
  - sort
  - agent_auditing
  - source:dataset
---

# Agent Auditing Stopped (Last 24 Hours)

**Dataset**: `agent_auditing`

```sql
config timeframe =24H
| dataset = agent_auditing
| filter agent_auditing_subtype=ENUM.AGENT_AUDIT_STOP
| fields _time, agent_auditing_subtype , endpoint_name , endpoint_id , xdr_agent_version , domain , description,*
| sort desc _time
```

## When to use

Lists the agents that stopped auditing in the last 24 hours, and provides endpoint and version details

## Variations

_(No variations are documented for this entry.)_
