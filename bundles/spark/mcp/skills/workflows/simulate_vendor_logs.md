---
name: simulate_vendor_logs
displayName: Simulate vendor-faithful logs
category: workflows
description: 'Generate log records whose top-level keys match a vendor''s ACTUAL field schema (FortiGate, Okta, PaloAlto, etc.) extracted from Cortex ModelingRules. The output looks like what the vendor actually emits, so Cortex''s out-of-the-box modeling rule parses it into XDM correctly. Use when the operator says "simulate FortiGate logs", "generate 50 PAN-OS events", or any phrasing that names a specific vendor. Falls back to Rosetta''s generic Phantom-branded output when no matching data source is installed.'
icon: schema
source: platform
loadingMode: on-demand
locked: false
---

# Skill: Simulate vendor-faithful logs

## When this skill applies

The operator names a specific vendor or product in their log-simulation request. Examples:

- "Simulate 50 FortiGate traffic logs"
- "Generate Okta authentication events for the finance team"
- "Create some PaloAlto Networks firewall logs"
- "I need PingFederate audit events for my dashboard"

When the operator's request is GENERIC ("generate 100 syslog messages", "create some incidents", "simulate logs with these observables") — do NOT use this skill. Use `xlog.generate_fake_data_v2` directly with Rosetta's generic universe.

## Why this skill exists

Phantom's default log simulation (`xlog.generate_fake_data_v2`) emits records using Rosetta's predefined field universe. Those records work for generic dashboards but DON'T parse cleanly through Cortex's out-of-the-box ModelingRules — the rule expects FortiGate's `srcip` / `dstip` / `srcport` / `dstport` and gets Rosetta's `local_ip` / `remote_ip`. The XDM mapping silently misses fields.

The Data Sources marketplace solves this. Operators install vendor schemas extracted from Cortex ModelingRule `_schema.json` files. This skill USES those installed schemas — generated records carry the vendor's actual field names, so the matching modeling rule parses them into XDM events correctly. End result: simulated FortiGate traffic shows up in XSIAM's `xdr_data` dataset with proper XDM fields populated.

## Pre-flight: read the organization

The users, hosts and addresses in the simulated logs belong to the active organization, never to an invented company. When the operator names people, a department, a site or a role (*"the finance team"*, *"the CFO"*, *"the Jeddah branch"*, *"the file server"*), resolve them with one `organization_get` call (`section=people filter=department=Finance`, `section=personas`, `section=people filter=site=JED`, `section=hosts filter=role=server`) and pass the returned logins, workstation names and addresses in `observables_dict`, keeping each person's login, workstation and address together. When the operator names none, leave the identity fields unset: xlog binds them from the active organization (`use_organization`, default true) and reports which fields it bound. If the operator supplies addresses of their own, use them as given. If the organization lacks what the operator names, say so and offer `organization_update` instead of inventing it.

## Pre-flight — verify a data source is installed

Step 1: call `data_sources_list` (optionally filtered) to see what schemas the operator has installed.

```
data_sources_list(filter="<vendor name from the operator's prompt>")
```

Decision tree based on the response:

- **Exactly 1 result + names match the operator's intent** → use it.
- **Multiple results** → pick the best match by pack_name then dataset_name. Prefer non-rawlog rows (`is_rawlog_only=false`) — rawlog-only schemas can't be used as schema_override.
- **No results** → tell the operator:
  > "No installed data source matches '<vendor>'. Open /data-sources, click Browse, and install a matching schema — or fall back to Rosetta with `xlog.generate_fake_data_v2` if a generic format is acceptable."
  >
  > Then STOP. Don't auto-install — operator should explicitly opt into the install via the UI or by saying "yes install it".

## Step 1 — Resolve the schema

Once you have the chosen `data_source_id`, fetch the full schema:

```
data_sources_get_schema(data_source_id="<id from list>")
```

Response shape:
```json
{
  "ok": true,
  "data_source": {
    "id": "FortiGate/FortiGate_1_3/fortinet_fortigate_raw",
    "pack_name": "FortiGate",
    "rule_name": "FortiGate_1_3",
    "dataset_name": "fortinet_fortigate_raw",
    "field_count": 176,
    "non_meta_field_count": 172,
    "is_rawlog_only": false,
    "fields": [
      { "name": "_id",    "type": "string",   "is_meta": true,  "is_array": false },
      { "name": "_time",  "type": "datetime", "is_meta": true,  "is_array": false },
      { "name": "srcip",  "type": "string",   "is_meta": false, "is_array": false },
      { "name": "dstip",  "type": "string",   "is_meta": false, "is_array": false },
      { "name": "srcport","type": "int",      "is_meta": false, "is_array": false },
      ...
    ],
    "xdm_mappings": []
  }
}
```

If `is_rawlog_only` is true, STOP and tell the operator:
> "FortiGate's schema is rawlog-only — Phantom can't generate structured vendor-faithful logs for it. Falling back to Rosetta's generic CEF/syslog format."

Then call `xlog.generate_fake_data_v2` with `type="CEF"` and a reasonable vendor/product as a degraded-mode response.

## Step 2 — Call generate_fake_data_v2 with the schema override

Build the `schema_override` parameter from the schema you just loaded. Pass ALL fields including meta (the v2 layer omits meta automatically). Don't transform the field shape — pass each field as `{name, type, is_array, is_meta}` directly.

```
xlog_generate_fake_data_v2(
  request={
    "type": "JSON",
    "count": <operator's count, default 10>,
    "vendor": "<schema.pack_name>",
    "product": "<schema.pack_name>",
    "datetime_iso": "<optional — caller may want a specific time window>",
    "observables_dict": "<optional — caller passes specific IPs/users if the prompt mentions them>"
  },
  schema_override={
    "vendor_fields": [
      { "name": "<f.name>", "type": "<f.type>", "is_array": <f.is_array>, "is_meta": <f.is_meta> }
      for f in schema.fields
    ],
    "dataset_name": "<schema.dataset_name>",
    "pack_name": "<schema.pack_name>",
    "rule_name": "<schema.rule_name>"
  }
)
```

Use `type: "JSON"` regardless of what the operator said unless they explicitly asked for CEF/Syslog/LEEF — the v2 path emits JSON records keyed by vendor field names. Wire-format wrapping is the operator's concern, not the schema's.

## Step 3 — Report back to the operator

When the response comes back:

- `schema_applied: true` → tell the operator which schema was used + the record count:
  > "Generated 50 vendor-faithful logs using the **FortiGate** schema (172 vendor fields from FortiGate_1_3 / fortinet_fortigate_raw). Sample record: `{srcip: "10.20.16.20", dstip: "203.0.113.5", srcport: 41872, dstport: 443, action: "allow", ...}`. Cortex's FortiGate ModelingRule will parse these into XDM events when sent to XSIAM."

- `schema_applied: false` + `fallback_reason` is set → explain what fell back:
  > "Schema override didn't apply (`<fallback_reason>`). Generated logs use Rosetta's generic field universe instead — the FortiGate ModelingRule won't parse them. Investigate via /data-sources."

## End-to-end smoke (operator verification)

The full path to verify this skill end to end:

1. Open `/data-sources`, click Browse, install **FortiGate / FortiGate_1_3** (Install button on the dataset row).
2. In chat, say: *"Simulate 50 FortiGate traffic logs."*
3. Agent should respond with 50 records whose keys include `srcip`, `dstip`, `srcport`, `dstport`, `action`, etc. — NOT Rosetta's `local_ip`/`remote_ip`.
4. (Optional — full XSIAM path): pipe the records into the operator's XSIAM webhook via `create_data_worker` and verify they land in `xdr_data` as XDM events.

## Forbidden under this skill

- **Don't auto-install missing data sources.** When the operator names a vendor with no installed schema, surface the gap + point them at `/data-sources` Browse. Auto-install would burn API quota + commit to a schema the operator hasn't reviewed.
- **Don't transform field names.** Pass them verbatim from `data_sources_get_schema`. The whole point is preserving the vendor's actual naming so the modeling rule's mapping fires.
- **Don't pass observables_dict that doesn't match the schema's field names.** Observables only override when the field name in the schema matches the key in observables_dict. Mismatched keys are silently ignored.

## Related skills + tools

- `xlog.generate_fake_data_v2` — legacy/Rosetta path. Use when operator's request is generic (no vendor name).
- `cortex_extract_vendor_schema` — read a schema without installing it. Useful for preview-only flows.
- `cortex_list_modeling_rules` — discover what schemas exist in a given Cortex pack.
- `/data-sources` UI — install / uninstall / browse schemas.
