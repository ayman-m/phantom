#!/usr/bin/env python3
"""Enhance validated-vendor data_source.yaml files with `how_to_use` field.

Adds operator-facing simulation guidance — multi-dataset handling, CEF-wrap
wire format, MR-specific quirks, saturation strategy — based on the L1-L20
lessons from the first five validated packs.

Idempotent: writes `how_to_use` between `description` and `categories`. If
the field already exists it's REPLACED, not appended.

Targets: 22 validated-via-CEF-wrap vendors from batches 1-12.
PANW NGFW × 6 are handled separately via scripts/maintainer/build_panw_ngfw_packs.py
(they live under scripts/maintainer/generated_data_sources/, not bundles/).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ROOT = REPO_ROOT / "bundles" / "spark" / "data-sources"

# ----------------------------------------------------------------------
# Shared header for every entry. Keeps the per-vendor sections short
# while ensuring the operator gets the universal background once.
# ----------------------------------------------------------------------
# Single merged section, fully generic broker — NO hardcoded IP
# and NO port number. Kept in sync with scripts/maintainer/clean_how_to_use.py
# (the canonical cleaner for already-generated YAMLs). A two-section
# format (a separate "## Simulating this data source" header that hardcoded
# an IP and port) is deliberately not used.
MERGED_HEADER = """## Sending these logs to Cortex XSIAM

Phantom emits this vendor's wire format as CEF over UDP — point a data worker
at your XSIAM broker's syslog destination and these records flow straight in.
The schema below describes the vendor's fields independent of destination, so
the same records also work for Splunk, Elastic, or any syslog receiver.

The CEF header's **vendor** + **product** drive XSIAM's parsing-rule routing:
the broker normalizes them to `<lowercased-vendor>_<lowercased-product>_raw`
(non-alphanumerics -> `_`) and matches your installed parsing rule. The PR/MR
rules read NAMED COLUMNS, so the transport is invisible to them — pack the
vendor's field names as CEF extension `key=value` pairs."""

VERIFY_BLOCK_TEMPLATE = """**Verify**:

```xql
datamodel dataset = {dataset}
| filter {filter_field} contains "<your-marker>"
| fields xdm.*
| limit 1
```
"""


# The routing explanation + `udp:<broker-host>:514` reference live in
# MERGED_HEADER above (which carries no hardcoded IP or port).


def vendor_entry(
    *,
    dataset: str,
    sibling_datasets: list[str] | None = None,
    cef_vendor: str,
    cef_product: str,
    routing_notes: str = "",
    mr_pattern: str,
    composite_notes: str,
    sentinel_notes: str = "None.",
    pr_filter_notes: str = "Standard CEF — vendor + product in header, timestamp via `rt=<epoch_ms>`.",
    saturation_notes: str,
    xdm_ceiling: str,
    filter_field: str = "xdm.event.id",
    extra_notes: str = "",
) -> str:
    """Compose a per-vendor `how_to_use` markdown body.

    One merged section. `sibling_datasets` is accepted for API
    compatibility but no longer emitted as a generic line — the per-vendor
    `routing_notes` carries the specific discriminator guidance that
    multi-dataset packs actually need.
    """
    _ = sibling_datasets  # retained for call-site compatibility; see docstring
    body = [MERGED_HEADER, ""]
    body.append("**Required CEF header for XSIAM**:")
    body.append("")
    body.append(f"- **vendor**: `{cef_vendor}`")
    body.append(f"- **product**: `{cef_product}`")
    body.append("")
    body.append(
        f"Broker derives → `{cef_vendor.lower().replace(' ', '_').replace('-', '_')}"
        f"_{cef_product.lower().replace(' ', '_').replace('-', '_')}_raw`."
    )
    if routing_notes:
        body.append("")
        body.append(routing_notes)
    body.append("")

    body.append("**MR pattern**: " + mr_pattern)
    body.append("")
    body.append("**Composite (nested-JSON) fields**: " + composite_notes)
    body.append("")
    body.append("**Sentinel values**: " + sentinel_notes)
    body.append("")
    body.append("**PR filter quirks**: " + pr_filter_notes)
    body.append("")
    body.append("**Saturation strategy**: " + saturation_notes)
    body.append("")
    body.append(f"**Single-event XDM ceiling**: {xdm_ceiling}")
    body.append("")
    body.append(VERIFY_BLOCK_TEMPLATE.format(dataset=dataset, filter_field=filter_field).rstrip())

    if extra_notes:
        body.append("")
        body.append("**Notes**: " + extra_notes)

    return "\n".join(body)


# ----------------------------------------------------------------------
# Per-vendor entries. Key is the directory name under
# bundles/spark/data-sources/. Value is the how_to_use markdown.
# ----------------------------------------------------------------------
ENTRIES: dict[str, str] = {
    # ─── Okta (multi-dataset: okta_okta_raw + okta_sso_raw) ───────────
    "Okta__OktaModelingRules__okta_okta_raw": vendor_entry(
        dataset="okta_okta_raw",
        sibling_datasets=["okta_sso_raw"],
        cef_vendor="Okta",
        cef_product="Okta",
        routing_notes=(
            "Both `okta_okta_raw` and `okta_sso_raw` share the same broker route — XSIAM's "
            "operator-installed PR splits them inside the tenant by reading the `eventType` "
            "raw field. For events to land here (`okta_okta_raw`), set `eventType` to any "
            "non-SSO Okta event (e.g. `user.account.update_password`, `policy.evaluate_sign_on`)."
        ),
        mr_pattern=(
            "Nested-JSON. The MR uses `json_extract_scalar(actor, \"$.alternateId\")` style "
            "lookups against composite fields (`actor`, `client`, `outcome`, `target`, "
            "`securityContext`, `debugContext`, `authenticationContext`)."
        ),
        composite_notes=(
            "Pack each composite as a single CEF extension whose value is the JSON-string "
            "of the inner object. Example: "
            "`actor={\"id\":\"00uA\",\"type\":\"User\",\"alternateId\":\"a@example.com\"}`. "
            "L15 confirms this survives CEF-extension wrapping; the MR's `json_extract_scalar` "
            "parses at query time."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "`uuid` must be present + unique; `published` must be RFC-3339 (`2026-05-28T05:00:00Z`)."
        ),
        saturation_notes=(
            "Keep single event under 1500 bytes to avoid UDP MTU truncation (L18). For >10 XDM "
            "fields, split into 2 events sharing `uuid` marker: event-1 carries `actor + outcome + "
            "client`, event-2 carries `target + securityContext + debugContext`. Lean Okta "
            "saturation at 1224 bytes still ceilings at 10 XDM (L20) — splitting is required."
        ),
        xdm_ceiling="~10 XDM (genuine nested-JSON ceiling, not MTU-related per L20).",
        filter_field="xdm.event.id",
        extra_notes=(
            "Validated end-to-end with a lean-saturation Okta test."
        ),
    ),
    "Okta__OktaModelingRules__okta_sso_raw": vendor_entry(
        dataset="okta_sso_raw",
        sibling_datasets=["okta_okta_raw"],
        cef_vendor="Okta",
        cef_product="Okta",
        routing_notes=(
            "Same broker route as `okta_okta_raw` — the operator's PR splits them by reading "
            "the `eventType` raw field. For events to land in `okta_sso_raw`, set `eventType` "
            "to an SSO event: `user.authentication.sso` or `user.session.start`. Without this "
            "discriminator value, events fall through to the general `okta_okta_raw` dataset."
        ),
        mr_pattern=(
            "Nested-JSON. Same MR family as okta_okta_raw but selectively MODELed to the SSO "
            "dataset — events with `eventType` starting `user.session.*` or `user.authentication.sso` "
            "route here."
        ),
        composite_notes=(
            "Same as okta_okta_raw: pack `actor`, `client`, `outcome`, `target`, `authenticationContext` "
            "as JSON-string CEF extensions. The PR's discriminator is `eventType` — must contain "
            "`sso` substring or `session.start` for the SSO route."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "Set `eventType=user.authentication.sso` or `eventType=user.session.start` to route "
            "into this dataset instead of `okta_okta_raw`."
        ),
        saturation_notes=(
            "Same as okta_okta_raw — 2-event split for nested-JSON XDM > 10."
        ),
        xdm_ceiling="~10 XDM (nested-JSON ceiling).",
        filter_field="xdm.event.id",
    ),
    # ─── Alibaba ActionTrail ─────────────────────────────────────────
    "AlibabaActionTrail__AlibabaModelingRules__alibaba_action_trail_raw": vendor_entry(
        dataset="alibaba_action_trail_raw",
        cef_vendor="alibaba",
        cef_product="action_trail",
        routing_notes=(
            "Use the lowercased, underscore-separated form (`alibaba` / `action_trail`) rather "
            "than the marketing display name (`Alibaba ActionTrail`) — the broker normalizes "
            "non-alphanumerics to `_`, so display-name input would derive "
            "`alibaba_actiontrail_alibaba_actiontrail_raw` which doesn't match the operator's PR."
        ),
        mr_pattern=(
            "Flat-field. MR reads top-level CEF extensions directly (`event_eventtype`, "
            "`event_principalid`, `event_apiVersion`, `event_eventsource`, etc.)."
        ),
        composite_notes=(
            "Largely flat. `userIdentity` carries a JSON-string with `principalId`/`accessKeyId` "
            "but the MR mostly consumes flat fields."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "Send timestamp as `eventTime=<RFC3339>` and `event_eventTime=<RFC3339>` — both fields "
            "are referenced in the PR's filter regex."
        ),
        saturation_notes=(
            "Single event fits comfortably under MTU. PoC validated 7 XDM in one event."
        ),
        xdm_ceiling="~7 XDM single-event (flat MR but only 7 distinct XDM mappings exist).",
        filter_field="xdm.event.id",
        extra_notes=(
            "Proof of concept: a single JSON-as-CEF event."
        ),
    ),
    # ─── AWS CloudTrail ───────────────────────────────────────────────
    "AWS-CloudTrail__AWSCloudTrail__amazon_aws_raw": vendor_entry(
        dataset="amazon_aws_raw",
        cef_vendor="amazon",
        cef_product="aws",
        routing_notes=(
            "**Important**: use `amazon` / `aws` — NOT the marketing names `Amazon Web Services` "
            "/ `AWS-CloudTrail`. The display names would auto-derive to "
            "`amazon_web_services_aws_cloudtrail_raw` (a different dataset that may also exist in "
            "your tenant but doesn't carry the upstream CloudTrail PR/MR rules)."
        ),
        mr_pattern=(
            "Mixed. Flat-field MR reads `eventName`, `eventSource`, `awsRegion`, `recipientAccountId` "
            "directly; nested `userIdentity.userName` extracted via `json_extract_scalar`."
        ),
        composite_notes=(
            "Pack `userIdentity` as JSON-string CEF extension; the MR walks `userIdentity.userName` "
            "and `userIdentity.principalId`. L15 + batch-4 validate this pattern."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "Set `eventName` to a known CloudTrail event ID (e.g. `ConsoleLogin`, `AssumeRole`); "
            "`eventTime` must be ISO-8601 with `Z` suffix."
        ),
        saturation_notes=(
            "Mixed-MR ceiling ~11 XDM per L19. Single event of ~800-1000 bytes covers most XDM."
        ),
        xdm_ceiling="~11 XDM single-event (mixed flat + 1 nested).",
        filter_field="xdm.event.id",
        extra_notes=(
            "Validated with a JSON-as-CEF batch test."
        ),
    ),
    # ─── AWS Security Hub ─────────────────────────────────────────────
    "AWS-SecurityHub__AWSSecurityHubModelingRules__aws_security_hub_raw": vendor_entry(
        dataset="aws_security_hub_raw",
        cef_vendor="aws",
        cef_product="security_hub",
        routing_notes=(
            "Use `aws` / `security_hub` (NOT display names) to broker-derive `aws_security_hub_raw`. "
            "The display-name path `Amazon Web Services` / `AWS-SecurityHub` derives "
            "`amazon_web_services_aws_securityhub_raw` — a different dataset."
        ),
        mr_pattern=(
            "Mixed. Reads `Severity.Label`, `Resources[0].Type`, `Compliance.Status` via nested "
            "extraction; also reads flat `ProductArn`, `AwsAccountId`, `Region`, `Id`."
        ),
        composite_notes=(
            "Pack `Resources` as a JSON-string ARRAY of objects; `Severity` as JSON-string object; "
            "`Compliance` as JSON-string object. Multiple `json_extract_scalar` calls per event."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "`Id` must be present and shaped like an AWS ARN. `UpdatedAt` must be RFC-3339."
        ),
        saturation_notes=(
            "Mixed-MR — single event reaches ~10 XDM. For > 10, split events by finding type."
        ),
        xdm_ceiling="~10 XDM single-event.",
        filter_field="xdm.event.id",
    ),
    # ─── AWS WAF ──────────────────────────────────────────────────────
    "AWS_WAF__AWS_WAF__aws_waf_raw": vendor_entry(
        dataset="aws_waf_raw",
        cef_vendor="aws",
        cef_product="waf",
        routing_notes=(
            "Use `aws` / `waf` to broker-derive `aws_waf_raw`. The display-name path "
            "`Amazon Web Services` / `AWS_WAF` derives a different dataset name."
        ),
        mr_pattern=(
            "Heavy-nested. MR consumes `httpRequest.headers[].name`/`headers[].value` array "
            "indexing plus nested `terminatingRuleMatchDetails[].matchedData[]`."
        ),
        composite_notes=(
            "`httpRequest` carries deeply-nested JSON with `clientIp`, `country`, `httpMethod`, "
            "`uri`, `requestId`, and `headers[]` array. Pack as a JSON-string. L15 confirms array "
            "indexing survives CEF-extension wrapping when the MR uses `json_extract_scalar` with "
            "JSONPath array indices."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "`timestamp` must be epoch-ms (13 digits). `action` must be one of "
            "`ALLOW`/`BLOCK`/`COUNT`/`CAPTCHA`/`CHALLENGE`/`EXCLUDED_AS_COUNT` (case-sensitive)."
        ),
        saturation_notes=(
            "Heavy-nested ceiling ~5-8 XDM per L19. Splitting events helps minimally because "
            "the same nested objects feed multiple XDM fields."
        ),
        xdm_ceiling="~5-8 XDM single-event (heavy-nested MR).",
        filter_field="xdm.event.id",
    ),
    # ─── Jira ─────────────────────────────────────────────────────────
    "Jira__JiraEventCollector__atlassian_jira_raw": vendor_entry(
        dataset="atlassian_jira_raw",
        cef_vendor="Atlassian",
        cef_product="Jira",
        routing_notes=(
            "Jira's audit stream is a single dataset — set `category=audit` so the parsing rule "
            "routes the event here (other categories fall through). The high-signal events are "
            "configuration, permission, and workflow changes, which carry a `changedValues[]` "
            "array of `{fieldName,changedFrom,changedTo}`; include 3+ entries so the modeling rule "
            "can build the change-chain instead of a bare single-field edit."
        ),
        mr_pattern=(
            "Mixed. MR reads `objectItem.id`/`objectItem.parentId`, iterates `changedValues[]`."
        ),
        composite_notes=(
            "Pack `objectItem` as JSON-string object; `changedValues` as JSON-string array of "
            "`{fieldName,changedFrom,changedTo}`."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "`category` must be `audit` for the audit dataset route. `created` must be RFC-3339."
        ),
        saturation_notes=(
            "Single event covers ~8 XDM; field-change events benefit from including 3+ "
            "`changedValues` entries to populate `xdm.event.original_event_id` chain."
        ),
        xdm_ceiling="~8 XDM single-event.",
        filter_field="xdm.event.id",
    ),
    # ─── ServiceNow ───────────────────────────────────────────────────
    "ServiceNow__ServiceNow__servicenow_servicenow_raw": vendor_entry(
        dataset="servicenow_servicenow_raw",
        cef_vendor="ServiceNow",
        cef_product="ServiceNow",
        routing_notes=(
            "ServiceNow emits one audit `record` per incident, change-request, or CMDB mutation — "
            "the high-signal events are field edits and approvals carried in the nested "
            "`record.changes[]` array. The gotcha that silently drops events: `sys_created_on` "
            "must be ServiceNow's native space-separated `YYYY-MM-DD HH:MM:SS`, not RFC-3339."
        ),
        mr_pattern=(
            "Heavy-nested. MR consumes audit `record` objects with deeply-nested "
            "`changes[].fieldname`/`changes[].old`/`changes[].new`."
        ),
        composite_notes=(
            "Pack `record` as JSON-string object with `sys_id`, `sys_class_name`, `assigned_to`, "
            "`changes[]`. The MR's array iteration over `changes[]` survives CEF-extension "
            "wrapping but only the first 3-4 array entries reliably populate XDM."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "`sys_created_on` must be `YYYY-MM-DD HH:MM:SS` (NOT RFC-3339 — ServiceNow's "
            "native format)."
        ),
        saturation_notes=(
            "Heavy-nested — ~5-8 XDM ceiling. Pack the most-important 3 audit changes only; "
            "later entries silently drop."
        ),
        xdm_ceiling="~5-8 XDM single-event (heavy-nested).",
        filter_field="xdm.event.id",
    ),
    # ─── CyberArk ISP ─────────────────────────────────────────────────
    "CyberArkPAS__CyberArkISP__cyberark_isp_raw": vendor_entry(
        dataset="cyberark_isp_raw",
        cef_vendor="cyberark",
        cef_product="isp",
        routing_notes=(
            "Use the lowercased forms (`cyberark` / `isp`) — broker derives `cyberark_isp_raw`. "
            "The full product name `Identity Security Platform` would derive a different dataset."
        ),
        mr_pattern=(
            "Mixed. Reads flat `event_type`, `username`, `action_taken`; also extracts "
            "`endpoint.deviceId` and `endpoint.hostname` via nested JSON."
        ),
        composite_notes=(
            "Pack `endpoint` and `target_user` as JSON-string objects. The MR pulls "
            "`endpoint.deviceId` and `target_user.directoryName`."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "`timestamp` must be RFC-3339 with millisecond precision (`...000Z`)."
        ),
        saturation_notes=(
            "Mixed-MR — ~10 XDM single-event."
        ),
        xdm_ceiling="~10 XDM single-event (mixed MR).",
        filter_field="xdm.event.id",
    ),
    # ─── Microsoft Entra ID (Azure AD) — Audit ────────────────────────
    "MicrosoftEntraID__MicrosoftEntraID__msft_azure_ad_audit_raw": vendor_entry(
        dataset="msft_azure_ad_audit_raw",
        sibling_datasets=["msft_azure_ad_raw"],
        cef_vendor="msft",
        cef_product="azure_ad_audit",
        routing_notes=(
            "Use `msft` (not `Microsoft`) + `azure_ad_audit` (not `Entra ID`) to broker-derive "
            "`msft_azure_ad_audit_raw`. Microsoft Entra ID has TWO datasets sharing the same "
            "broker route only if you use `msft` / `azure_ad` — but using `azure_ad_audit` "
            "vs `azure_ad` lets the broker derive directly to the right one. Alternatively use "
            "`msft` / `azure_ad` for both and set `category=AuditLogs` so the operator's PR "
            "routes here (vs `SignInLogs` → `msft_azure_ad_raw`)."
        ),
        mr_pattern=(
            "Heavy-nested. MR uses `initiatedBy.user.userPrincipalName`, "
            "`targetResources[].displayName`, `additionalDetails[].key=='UserAgent' -> .value`."
        ),
        composite_notes=(
            "Pack `initiatedBy` (`user`/`app` object), `targetResources` (array), "
            "`additionalDetails` (key-value array) as JSON-string CEF extensions. The "
            "`additionalDetails[]` filter-by-key extraction is the most fragile part — XSIAM's "
            "evaluator may return null on the array filter for deeply-nested CEF-stored JSON (L20)."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "`category` discriminator routes to this dataset: set `category=Audit` for audit "
            "events (vs `SignIn` for the sign-in dataset)."
        ),
        saturation_notes=(
            "Heavy-nested ceiling ~5-8 XDM. Single event 1100-1300 bytes."
        ),
        xdm_ceiling="~5-8 XDM single-event (heavy-nested + array filter).",
        filter_field="xdm.event.id",
    ),
    # ─── Microsoft Entra ID — Sign-in ─────────────────────────────────
    "MicrosoftEntraID__MicrosoftEntraID__msft_azure_ad_raw": vendor_entry(
        dataset="msft_azure_ad_raw",
        sibling_datasets=["msft_azure_ad_audit_raw"],
        cef_vendor="msft",
        cef_product="azure_ad",
        routing_notes=(
            "Use `msft` / `azure_ad` to broker-derive `msft_azure_ad_raw` (sign-in events). "
            "For audit events use the sibling dataset's CEF product `azure_ad_audit`. "
            "Some operator tenants split via PR on the `category` field "
            "(`SignInLogs` here; `AuditLogs` → sibling)."
        ),
        mr_pattern=(
            "Mixed. Flat `userPrincipalName`, `appDisplayName`, `clientAppUsed`; nested "
            "`location.city`/`location.countryOrRegion`, `deviceDetail.operatingSystem`."
        ),
        composite_notes=(
            "Pack `location` and `deviceDetail` as JSON-string objects. The MR's "
            "`json_extract_scalar(location, \"$.city\")` works reliably for top-level keys."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "`category=SignInLogs` discriminator routes here. `createdDateTime` RFC-3339."
        ),
        saturation_notes=(
            "Mixed MR — ~10 XDM ceiling."
        ),
        xdm_ceiling="~10 XDM single-event (mixed).",
        filter_field="xdm.event.id",
    ),
    # ─── Office 365 ────────────────────────────────────────────────────
    "Office365__Office365__msft_o365_general_raw": vendor_entry(
        dataset="msft_o365_general_raw",
        sibling_datasets=[
            "msft_o365_exchange_online_raw",
            "msft_o365_sharepoint_online_raw",
            "msft_o365_emails_raw",
            "msft_o365_dlp_raw",
        ],
        cef_vendor="msft",
        cef_product="o365_general",
        routing_notes=(
            "Use `msft` / `o365_general` to broker-derive `msft_o365_general_raw`. The 5 O365 "
            "workload datasets each have their own CEF product (`o365_exchange_online`, "
            "`o365_sharepoint_online`, etc.) — pick the one matching your event's `Workload` "
            "field. Display-name path `Microsoft` / `Office365` collapses to `microsoft_office365_raw` "
            "(a SINGLE catch-all that doesn't split by workload — operator's PR may not handle it)."
        ),
        mr_pattern=(
            "Mixed. Generic Office365 management activity events. Reads flat `Operation`, "
            "`UserId`, `ClientIP`, `Workload` and nested `ExtendedProperties[]`."
        ),
        composite_notes=(
            "`ExtendedProperties` is a `[{Name,Value}]` array — pack as JSON-string array. "
            "Filter-by-Name extraction in the MR is fragile per L20."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "`Workload` is the discriminator — set to `AzureActiveDirectory`/`Office365`/"
            "`SecurityComplianceCenter` for general; specific workloads route to siblings."
        ),
        saturation_notes=(
            "Mixed MR — ~10 XDM. Each sibling has a different XDM count."
        ),
        xdm_ceiling="~10 XDM single-event.",
        filter_field="xdm.event.id",
    ),
    "Office365__Office365__msft_o365_exchange_online_raw": vendor_entry(
        dataset="msft_o365_exchange_online_raw",
        sibling_datasets=[
            "msft_o365_general_raw",
            "msft_o365_sharepoint_online_raw",
            "msft_o365_emails_raw",
            "msft_o365_dlp_raw",
        ],
        cef_vendor="msft",
        cef_product="o365_exchange_online",
        routing_notes=(
            "Use `msft` / `o365_exchange_online` to broker-derive `msft_o365_exchange_online_raw`. "
            "Also set `Workload=Exchange` in the raw payload so the operator's PR (if it splits "
            "by Workload rather than dataset name) routes the event correctly."
        ),
        mr_pattern=(
            "Mixed. Reads Exchange-specific flat fields (`MailboxOwnerUPN`, `OperationProperties`, "
            "`AffectedItems`) and nested `Parameters[]`."
        ),
        composite_notes=(
            "Pack `Parameters`, `AffectedItems`, `OperationProperties` as JSON-string arrays."
        ),
        sentinel_notes="None.",
        pr_filter_notes="`Workload=Exchange` discriminator. Operation discriminators: `MailItemsAccessed`, `Set-Mailbox`, etc.",
        saturation_notes="Mixed MR — ~10 XDM.",
        xdm_ceiling="~10 XDM single-event.",
        filter_field="xdm.event.id",
    ),
    "Office365__Office365__msft_o365_sharepoint_online_raw": vendor_entry(
        dataset="msft_o365_sharepoint_online_raw",
        sibling_datasets=[
            "msft_o365_general_raw",
            "msft_o365_exchange_online_raw",
            "msft_o365_emails_raw",
            "msft_o365_dlp_raw",
        ],
        cef_vendor="msft",
        cef_product="o365_sharepoint_online",
        routing_notes=(
            "Use `msft` / `o365_sharepoint_online` to broker-derive `msft_o365_sharepoint_online_raw`. "
            "Also set `Workload=SharePoint`, `EventSource=SharePoint` in the raw payload."
        ),
        mr_pattern="Mixed. SharePoint-specific flat `SiteUrl`, `SourceFileName`, `SourceRelativeUrl`.",
        composite_notes="Pack `ModifiedProperties` as JSON-string array of `{Name,OldValue,NewValue}`.",
        sentinel_notes="None.",
        pr_filter_notes="`Workload=SharePoint` discriminator. `EventSource=SharePoint`.",
        saturation_notes="Mixed MR — but SharePoint XDM mapping is sparse; ~7 XDM observed.",
        xdm_ceiling="~7 XDM single-event.",
        filter_field="xdm.event.id",
    ),
    "Office365__Office365__msft_o365_emails_raw": vendor_entry(
        dataset="msft_o365_emails_raw",
        sibling_datasets=[
            "msft_o365_general_raw",
            "msft_o365_exchange_online_raw",
            "msft_o365_sharepoint_online_raw",
            "msft_o365_dlp_raw",
        ],
        cef_vendor="msft",
        cef_product="o365_emails",
        routing_notes=(
            "Use `msft` / `o365_emails` to broker-derive `msft_o365_emails_raw`. Also set "
            "`Operation=EmailEvent`, `Workload=ThreatIntelligence` in the raw payload."
        ),
        mr_pattern=(
            "Heavy-nested. Reads `Recipients[]`, `Attachments[]`, `Detections[]`, "
            "`UrlClickAction[]` plus the email envelope from `EmailDirection`, `DeliveryAction`."
        ),
        composite_notes=(
            "Pack `Recipients`, `Attachments`, `Detections` as JSON-string arrays. Heavy-nested "
            "ceiling applies (L19 + L20)."
        ),
        sentinel_notes="None.",
        pr_filter_notes="`Operation=EmailEvent` discriminator + `Workload=ThreatIntelligence`.",
        saturation_notes="Heavy-nested — ~2-5 XDM single-event observed; multi-event split useful.",
        xdm_ceiling="~2-5 XDM single-event (heavy-nested arrays).",
        filter_field="xdm.event.id",
        extra_notes=(
            "Lowest-yield O365 sibling per batch 10 testing. Multi-event split + careful array "
            "shaping required to exceed 5 XDM."
        ),
    ),
    "Office365__Office365__msft_o365_dlp_raw": vendor_entry(
        dataset="msft_o365_dlp_raw",
        sibling_datasets=[
            "msft_o365_general_raw",
            "msft_o365_exchange_online_raw",
            "msft_o365_sharepoint_online_raw",
            "msft_o365_emails_raw",
        ],
        cef_vendor="msft",
        cef_product="o365_dlp",
        routing_notes=(
            "Use `msft` / `o365_dlp` to broker-derive `msft_o365_dlp_raw`. Also set "
            "`Workload=DLP` + the appropriate `RecordType` in the raw payload."
        ),
        mr_pattern="Mixed. DLP-specific flat `PolicyId`, `PolicyName`, `RuleName`, `SensitiveInfoDetections[]`.",
        composite_notes="Pack `SensitiveInfoDetections` as JSON-string array. `ExceptionInfo` as JSON-string object.",
        sentinel_notes="None.",
        pr_filter_notes="`Workload=DLP` + `RecordType` discriminator.",
        saturation_notes="Mixed MR — ~8 XDM.",
        xdm_ceiling="~8 XDM single-event.",
        filter_field="xdm.event.id",
    ),
    # ─── Qualys ───────────────────────────────────────────────────────
    "qualys__QualysModelingRules__qualys_qualys_raw": vendor_entry(
        dataset="qualys_qualys_raw",
        cef_vendor="Qualys",
        cef_product="Qualys",
        routing_notes=(
            "Qualys emits one record per scanned asset — flat fields (`ID`, `IP`, `OS`) identify "
            "the host while the vulnerability detail lives in the nested "
            "`VULN_INFO_LIST.VULN_INFO[]` array the modeling rule iterates. Note the non-standard "
            "time field: the parsing rule keys on `LAST_VULN_SCAN_DATETIME` "
            "(`YYYY-MM-DDTHH:MM:SSZ`), not a generic `timestamp`/`rt`."
        ),
        mr_pattern=(
            "Mixed. Reads flat asset fields (`ID`, `IP`, `OS`, `LAST_VULN_SCAN_DATETIME`) and "
            "nested `VULN_INFO_LIST.VULN_INFO[].QID`."
        ),
        composite_notes=(
            "Pack `VULN_INFO_LIST` as JSON-string object with nested `VULN_INFO` array. The MR "
            "iterates this array via `json_extract_scalar`."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "Qualys uses `LAST_VULN_SCAN_DATETIME` for the time field — must be `YYYY-MM-DDTHH:MM:SSZ`."
        ),
        saturation_notes="Mixed MR — ~9 XDM. Single event ~1200 bytes.",
        xdm_ceiling="~9 XDM single-event.",
        filter_field="xdm.event.id",
    ),
    # ─── ProofPoint Email Security ────────────────────────────────────
    "ProofpointEmailSecurity__ProofpointEmailSecurity__proofpoint_email_security_raw": vendor_entry(
        dataset="proofpoint_email_security_raw",
        cef_vendor="proofpoint",
        cef_product="email_security",
        routing_notes=(
            "Use lowercased forms (`proofpoint` / `email_security`) — display form "
            "`Proofpoint` / `Email Security` also auto-derives the same name (the broker "
            "lowercases + replaces spaces with `_`)."
        ),
        mr_pattern=(
            "Heavy-nested. Reads `messageParts[]`, `headers[]`, `policyRoutes[]`, plus "
            "`recipient[]`, `sender`, `subject`."
        ),
        composite_notes=(
            "Pack `messageParts`, `headers`, `policyRoutes` as JSON-string arrays. The MR's "
            "filter-by-key extraction over `headers[].name == 'From'` may not survive deeply-"
            "nested CEF-stored JSON (L20)."
        ),
        sentinel_notes="None.",
        pr_filter_notes="`messageID` must be unique. `ts` (epoch ms) is the timestamp field.",
        saturation_notes="Heavy-nested — ~5 XDM single-event.",
        xdm_ceiling="~5 XDM single-event (heavy-nested + array filter).",
        filter_field="xdm.event.id",
    ),
    # ─── ProofPoint TAP ──────────────────────────────────────────────
    "ProofpointTAP__ProofpointTAPModelingRules__proofpoint_tap_raw": vendor_entry(
        dataset="proofpoint_tap_raw",
        cef_vendor="Proofpoint",
        cef_product="TAP",
        routing_notes=(
            "Proofpoint TAP (Targeted Attack Protection) reports message-level threat verdicts "
            "and URL-click events — most of the signal is in flat fields (`threatType`, "
            "`threatStatus`, `classification`, `clickIP`), with `messageParts[]` carrying "
            "per-attachment detail. Every event needs a unique `GUID` and an RFC-3339 "
            "`threatTime`; without the `GUID` the parsing rule drops the event. (Distinct pack "
            "from `proofpoint_email_security_raw` — different rule, different dataset.)"
        ),
        mr_pattern=(
            "Mixed. Reads flat `threatType`, `threatStatus`, `classification`, `clickIP`, "
            "`completelyRewritten`, `recipient` plus nested `messageParts[].md5`."
        ),
        composite_notes=(
            "Pack `messageParts` as JSON-string array. Most TAP fields are flat."
        ),
        sentinel_notes="None.",
        pr_filter_notes="`GUID` must be present; `threatTime` RFC-3339.",
        saturation_notes="Mixed MR — ~10 XDM.",
        xdm_ceiling="~10 XDM single-event.",
        filter_field="xdm.event.id",
    ),
    # ─── Azure Flow Logs ──────────────────────────────────────────────
    "AzureFlowLogs__AzureFlowLogs__msft_azure_flowlogs_raw": vendor_entry(
        dataset="msft_azure_flowlogs_raw",
        cef_vendor="msft",
        cef_product="azure_flowlogs",
        routing_notes=(
            "Use `msft` / `azure_flowlogs` (NOT `Microsoft` / `Azure`) to broker-derive "
            "`msft_azure_flowlogs_raw`. Display-name path collapses to `microsoft_azure_raw` — "
            "a catch-all that doesn't carry the flow-log MR."
        ),
        mr_pattern=(
            "Flat-field. MR reads top-level `srcIp_s`, `destIp_s`, `srcPort_d`, `destPort_d`, "
            "`L7Protocol_s`, `FlowStatus_s` — all flat columns."
        ),
        composite_notes=(
            "None. Flat-field vendor. Just send 13+ flat CEF extensions matching the MR's "
            "field names."
        ),
        sentinel_notes="None.",
        pr_filter_notes="`TimeGenerated` RFC-3339.",
        saturation_notes=(
            "Flat-field — easy to saturate to the 13 XDM ceiling (L18). Single event of "
            "~1000 bytes reaches the ceiling."
        ),
        xdm_ceiling="~13 XDM single-event (flat-field MR — highest single-event yield).",
        filter_field="xdm.event.id",
    ),
    # ─── Azure WAF ────────────────────────────────────────────────────
    "AzureWAF__AzureWAF__msft_azure_waf_raw": vendor_entry(
        dataset="msft_azure_waf_raw",
        cef_vendor="msft",
        cef_product="azure_waf",
        routing_notes=(
            "Use `msft` / `azure_waf` to broker-derive `msft_azure_waf_raw`. Display-name path "
            "`Microsoft` / `Azure WAF` derives `microsoft_azure_waf_raw` — a different dataset."
        ),
        mr_pattern=(
            "Flat-field. MR reads flat `clientIp_s`, `httpStatusCode_s`, `requestUri_s`, "
            "`hostname_s`, `action_s`, `ruleId_s` — all _s/_d/_g typed CEF extensions."
        ),
        composite_notes=(
            "None. Flat-field. Send all WAF columns as flat CEF extensions matching the MR's "
            "exact field name (note the `_s`/`_d`/`_g` type suffixes from Azure's table column "
            "convention)."
        ),
        sentinel_notes="None.",
        pr_filter_notes="`TimeGenerated` RFC-3339.",
        saturation_notes=(
            "Flat-field — single event of 1166 bytes reached 13 XDM per L20 measurement. This "
            "is the easiest vendor to saturate."
        ),
        xdm_ceiling="~13 XDM single-event (flat-field, highest single-event yield).",
        filter_field="xdm.event.id",
    ),
    # ─── Azure Kubernetes Services (AKS) ──────────────────────────────
    "AzureKubernetesServices__AzureKubernetesServices__msft_azure_aks_raw": vendor_entry(
        dataset="msft_azure_aks_raw",
        cef_vendor="msft",
        cef_product="azure_aks",
        routing_notes=(
            "Use `msft` / `azure_aks` to broker-derive `msft_azure_aks_raw`. Also set "
            "`category=kube-audit` in the raw payload — the PR rejects events without it."
        ),
        mr_pattern=(
            "Heavy-nested. Reads `properties.log` as a nested object containing `auditID`, "
            "`user.username`, `verb`, `objectRef.resource`, `objectRef.namespace`, etc. Up to "
            "4 levels deep."
        ),
        composite_notes=(
            "Pack `properties` as JSON-string with nested `log` object. The MR walks "
            "`properties.log.user.username` and `properties.log.objectRef.resource` — L15 "
            "validates 4-level nesting survives CEF-extension wrapping."
        ),
        sentinel_notes="None.",
        pr_filter_notes=(
            "`category=kube-audit` discriminator; PR rejects events without exact `properties.log` "
            "shape — getting the JSON nesting wrong silently kills the event (L17)."
        ),
        saturation_notes=(
            "Heavy-nested, deep-nested — ~5-8 XDM. Single event ~1100 bytes."
        ),
        xdm_ceiling="~5-8 XDM single-event (deep-nested).",
        filter_field="xdm.event.id",
        extra_notes=(
            "Most fragile vendor in the validated set — the `properties.log` nested object MUST "
            "be exactly right or the PR drops the event."
        ),
    ),
}


def upsert_how_to_use(yaml_path: Path, how_to_use: str) -> tuple[bool, str]:
    """Add or replace the `how_to_use` field in a data_source.yaml file.

    Returns (changed, reason). Idempotent — running twice with the same content
    leaves the file unchanged.
    """
    if not yaml_path.exists():
        return False, "file_not_found"

    with yaml_path.open("r", encoding="utf-8") as f:
        doc: dict[str, Any] = yaml.safe_load(f) or {}

    if doc.get("how_to_use") == how_to_use:
        return False, "already_current"

    # Insert between description (if present) and categories
    # PyYAML preserves insertion order on dump if sort_keys=False, but we need
    # to rebuild the dict to inject at the right position.
    ordered: dict[str, Any] = {}
    inserted = False
    for k, v in doc.items():
        ordered[k] = v
        if k == "description" and not inserted:
            ordered["how_to_use"] = how_to_use
            inserted = True
    if not inserted:
        # No description present — insert before categories or at end
        ordered = {}
        inserted = False
        for k, v in doc.items():
            if k == "categories" and not inserted:
                ordered["how_to_use"] = how_to_use
                inserted = True
            ordered[k] = v
        if not inserted:
            ordered["how_to_use"] = how_to_use

    # Preserve the existing `how_to_use` slot if it already exists
    # (the above loops would double-write it). Strip any prior occurrence
    # that wasn't from our injection point.
    seen = False
    final: dict[str, Any] = {}
    for k, v in ordered.items():
        if k == "how_to_use":
            if seen:
                continue
            final[k] = how_to_use
            seen = True
        else:
            final[k] = v

    with yaml_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            final,
            f,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
            width=100,
        )
    return True, "updated"


def main() -> int:
    if not BUNDLE_ROOT.is_dir():
        print(f"ERROR: BUNDLE_ROOT not found: {BUNDLE_ROOT}", file=sys.stderr)
        return 1

    n_updated = 0
    n_already = 0
    n_missing = 0
    for slug, how_to_use in ENTRIES.items():
        yaml_path = BUNDLE_ROOT / slug / "data_source.yaml"
        changed, reason = upsert_how_to_use(yaml_path, how_to_use)
        if reason == "file_not_found":
            print(f"  MISSING {slug}")
            n_missing += 1
        elif changed:
            print(f"  UPDATED {slug}")
            n_updated += 1
        else:
            print(f"  already {slug}")
            n_already += 1
    print()
    print(f"Done: updated={n_updated} already={n_already} missing={n_missing}")
    return 0 if n_missing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
