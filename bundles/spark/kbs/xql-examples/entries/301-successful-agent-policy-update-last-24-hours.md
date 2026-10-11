---
id: XQL-301-71d22955
title: Successful Agent Policy Update (Last 24 Hours)
category: investigation
dataset: agent_auditing
tags:
  - config
  - filter
  - fields
  - agent_auditing
  - source:dataset
---

# Successful Agent Policy Update (Last 24 Hours)

**Dataset**: `agent_auditing`

```sql
config timeframe =24H
|dataset = agent_auditing
| filter agent_auditing_subtype=ENUM.AGENT_AUDIT_POLICY_UPDATE and agent_auditing_result=ENUM.AGENT_AUDIT_SUCCESS
| fields _time, agent_auditing_subtype , endpoint_name , endpoint_id ,xdr_agent_version , domain , agent_auditing_result , description,*
```

## When to use

Lists the agents that had a successful policy update in the last 24 hours, and provides the endpoint information and version details.

## Variations

_(No variations are documented for this entry.)_
