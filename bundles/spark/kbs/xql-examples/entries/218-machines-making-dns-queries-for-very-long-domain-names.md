---
id: XQL-218-6ac733a6
title: Machines making DNS queries for very long domain names
category: investigation
dataset: xdr_data
tags:
  - filter
  - fields
  - comp
  - sort
  - xdr_data
  - source:dataset
---

# Machines making DNS queries for very long domain names

**Dataset**: `xdr_data`

```sql
// NOTE: this query requires Palo Alto Networks NGFW data with Enhanced Application Logs enabled
 dataset = xdr_data // Using the xdr dataset
 | filter event_type = ENUM.STORY and len(dns_query_name) > 100 // Filter by DNS queries where the domain name is over 100 characters in length
 | fields action_local_ip, dns_query_name // Get the local IP and the domain name
 | comp count_distinct(dns_query_name) as unique_long_dns by action_local_ip // Count the distinct FQDNs queried by the local IP
 | sort desc unique_long_dns // Sort in descending order
```

## When to use

Display connections to domains with very long names (over 100 chars). This could be an indication of DNS tunneling

## Variations

_(No variations are documented for this entry.)_
