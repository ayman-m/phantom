---
id: XQL-601-fb8f1e12
title: Azure Outpot Cost
category: investigation
dataset: azure_outpost_cost
tags:
  - fields
  - azure_outpost_cost
  - source:dataset
---

# Azure Outpot Cost

**Dataset**: `azure_outpost_cost`

```sql
dataset = azure_outpost_cost | fields ResourceID,ResourceType,ResourceLocation,ResourceGroupName,SubscriptionName,ServiceName,Meter,Tags,Cost
```

## When to use

Azure Outpot Cost. Queries the `azure_outpost_cost` dataset directly. Uses stages: `fields`.

## Variations

_(No variations are documented for this entry.)_
