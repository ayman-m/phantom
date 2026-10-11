---
id: XQL-291-b9d2ab81
title: API Keys Failed Authentication
category: investigation
dataset: management_auditing
tags:
  - filter
  - alter
  - fields
  - sort
  - management_auditing
  - source:dataset
---

# API Keys Failed Authentication

**Dataset**: `management_auditing`

```sql
dataset = management_auditing 
| filter subtype = "Authentication failed"
| alter sourceIP=arrayindex(regextract(description , "IP\:\s(.*?)\,"),0), apiKeyID=arrayindex(regextract(description,"ID\:\s(\d+)$"),0)
| fields _time, user_name , subtype , apiKeyID , sourceIP , description,*
| sort desc _time
```

## When to use

Lists the API keys that failed to authenticate, and includes the relevant user information and the IP address from which the authentication attempt was made

## Variations

_(No variations are documented for this entry.)_
