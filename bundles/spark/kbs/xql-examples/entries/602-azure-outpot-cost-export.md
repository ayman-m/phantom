---
id: XQL-602-baea7cd4
title: Azure Outpot Cost Export
category: investigation
dataset: azure_outpost_cost
tags:
  - fields
  - filter
  - azure_outpost_cost
  - source:dataset
---

# Azure Outpot Cost Export

**Dataset**: `azure_outpost_cost`

```sql
dataset = azure_outpost_cost | fields ResourceID,ResourceType,ResourceLocation,ResourceGroupName,SubscriptionName,ServiceName,Meter,Tags,Cost | filter SubscriptionName = "CortexCloud"
```

## When to use

Azure Outpot Cost Export. Queries the `azure_outpost_cost` dataset directly, filtered on `SubscriptionName = "CortexCloud"`. Uses stages: `fields`, `filter`.

## Variations

_(No variations are documented for this entry.)_
