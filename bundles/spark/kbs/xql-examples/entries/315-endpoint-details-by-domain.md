---
id: XQL-315-8a25fa6a
title: Endpoint Details by Domain
category: investigation
dataset: endpoints
tags:
  - filter
  - fields
  - endpoints
  - source:dataset
---

# Endpoint Details by Domain

**Dataset**: `endpoints`

```sql
dataset = endpoints
| filter domain in($domain)
| fields endpoint_name, agent_version, content_version, assigned_prevention_policy,*
```

## When to use

Provides detailed information about the endpoints in a specific domain, which includes their name, agent version, content version, and assigned prevention policy, and offers a complete view of the endpoint configurations

## Variations

_(No variations are documented for this entry.)_
