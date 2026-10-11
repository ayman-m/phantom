---
id: XQL-306-3c86ff3e
title: Agent Audit Quota Exceeded
category: investigation
dataset: agent_auditing
tags:
  - filter
  - fields
  - sort
  - agent_auditing
  - source:dataset
---

# Agent Audit Quota Exceeded

**Dataset**: `agent_auditing`

```sql
dataset = agent_auditing
| filter agent_auditing_subtype=ENUM.AGENT_AUDIT_QUOTA_EXCEEDED
| fields _time, agent_auditing_subtype , endpoint_name , endpoint_id ,xdr_agent_version , domain, description,*
| sort desc _time
```

## When to use

Lists the agents that exceeded their audit quota, and includes endpoint information and version details

## Variations

_(No variations are documented for this entry.)_
