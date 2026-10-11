#!/usr/bin/env python3
"""Microsoft vendor dictionary backfill.

# Why

Microsoft spans 18 packs whose fields lack descriptions. Microsoft's
log schemas are well-documented across:

  * Office 365 Management Activity API
    https://learn.microsoft.com/en-us/office/office-365-management-api/office-365-management-activity-api-schema
  * Azure Activity Log
    https://learn.microsoft.com/en-us/azure/azure-monitor/essentials/activity-log-schema
  * Microsoft Entra ID (Azure AD) sign-in + audit
    https://learn.microsoft.com/en-us/azure/active-directory/reports-monitoring/concept-sign-ins
    https://learn.microsoft.com/en-us/azure/active-directory/reports-monitoring/concept-audit-logs
  * Microsoft Graph API resources (mail, drive, ...)
    https://learn.microsoft.com/en-us/graph/api/overview
  * Azure WAF + AppService diagnostic logs
    https://learn.microsoft.com/en-us/azure/web-application-firewall/ag/web-application-firewall-logs
  * Microsoft Defender for Cloud
    https://learn.microsoft.com/en-us/azure/defender-for-cloud/

This script bakes one curated dictionary. Each entry cites the
authoritative Microsoft Learn schema name.

# Strategy

For each field in each Microsoft pack without a description, look it
up in MICROSOFT_DICT. Don't overwrite existing descriptions.
"""

from __future__ import annotations
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from extend_data_source_fields import update_one_yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_ROOT = REPO_ROOT / "bundles" / "spark" / "data-sources"


# ─── Microsoft field → description dictionary ──────────────────


MICROSOFT_DICT: dict[str, str] = {
    # ─── Office 365 Management Activity API (common audit fields) ──
    "CreationTime": "Event creation time (UTC)",
    "Id": "Unique audit record GUID",
    "Operation": "Operation name (e.g. FileAccessed, UserLoggedIn)",
    "OrganizationId": "Microsoft 365 tenant GUID",
    "RecordType": "Record type code (audit category enum)",
    "ResultStatus": "Operation result (Succeeded/Failed/PartiallySucceeded)",
    "UserKey": "Alternative user identifier (PUID/SID)",
    "UserType": "User type (0=Regular, 1=Reserved, 2=Admin, 3=DcAdmin, 4=System, 5=Application, 6=ServicePrincipal, 7=CustomPolicy, 8=SystemPolicy)",
    "Workload": "Microsoft 365 workload (e.g. Exchange, SharePoint, AzureActiveDirectory, OneDrive)",
    "ClientIP": "Client IP address",
    "ObjectId": "Microsoft 365 object the operation targeted",
    "UserId": "User principal name (UPN)",
    "Platform": "Client OS platform code (1=Windows, 2=MacOSX, 3=iOS, 4=Android, 5=WindowsMobile)",
    "AppId": "Application id that performed the operation",
    "DeviceId": "Device identifier",
    "ClientAppId": "Client application identifier",
    "ClientInfoString": "Free-form client app info string",
    "InterSystemsId": "Cross-system audit correlation id",
    "IntraSystemId": "Intra-system audit correlation id",
    "LogonType": "Logon type code (numeric enum)",
    "MailboxOwnerUPN": "Mailbox owner's UPN (Exchange)",
    "MailboxOwnerSid": "Mailbox owner's SID (Exchange)",
    "ExternalAccess": "Whether the operation was performed by an external user",

    # Azure AD / Entra ID specific
    "AzureActiveDirectoryEventType": "Azure AD event type (0=AccountLogon, 1=AzureApplicationAuditEvent)",
    "Actor": "Actor performing the action (Azure AD)",
    "ActorContextId": "Actor's context (tenant) id",
    "ActorIpAddress": "Actor's IP address",
    "ActorUserId": "Actor's user id",
    "Target": "Target of the operation",
    "TargetContextId": "Target's context (tenant) id",
    "TargetId": "Target user/object id",

    # Audit details
    "ExtendedProperties": "Additional event properties (workload-specific)",
    "ModifiedProperties": "Properties modified by the operation",
    "AdditionalDetails": "Additional event details (workload-specific)",
    "AppAccessContext": "Application access context (auth method/protocol)",

    # Defender / Security
    "AlertId": "Alert/incident identifier",
    "AlertEntityId": "Entity correlated with the alert",
    "AlertLinks": "URLs to alert in security console",
    "AlertType": "Alert type/category",
    "Category": "Event category",
    "Detail": "Operation detail",
    "Details": "Operation details (array)",
    "Detection": "Detection name",
    "DetectionMethod": "Method used to detect the event",
    "DeviceName": "Device hostname",
    "EntityType": "Entity type involved (e.g. User, Device, Mailbox)",
    "InvestigationType": "Type of investigation (e.g. Manual, Auto)",
    "PolicyMatchInfo": "Policy that matched (DLP/sensitivity)",
    "Severity": "Severity level (Low/Medium/High/Informational)",
    "Source": "Source of the event/alert",
    "Status": "Current status (e.g. New, InProgress, Resolved)",

    # File operations (SharePoint, OneDrive, Defender)
    "FileName": "File name",
    "FilePath": "File path",
    "FileData": "File payload metadata",
    "DestinationFileName": "Destination file name (move/copy)",
    "DestinationFileExtension": "Destination file extension",
    "SourceFileName": "Source file name (move/copy)",
    "SourceFileExtension": "Source file extension",
    "SourceRelativeUrl": "Source URL (SharePoint relative)",
    "ListTitle": "SharePoint list title",
    "ItemName": "Item name",
    "ItemType": "Item type",

    # Email/Exchange
    "InternetMessageId": "RFC 5322 Internet Message-ID",
    "Message": "Message contents/excerpt",
    "MessageId": "Message identifier",
    "Messages": "Message array",
    "Recipients": "Email recipients",
    "ReleaseTo": "Quarantine release destination",
    "SenderIp": "Sender's IP address",
    "DeeplinkURL": "Deep link URL into the M365 console",
    "EmailDirection": "Inbound or Outbound",
    "DeliveryAction": "Delivery action (Delivered/Junk/Quarantined/Blocked/Replaced)",
    "DeliveryLocation": "Delivery location (Inbox/JunkFolder/Quarantine)",

    # Microsoft Graph mail (https://learn.microsoft.com/en-us/graph/api/resources/message)
    "isDraft": "Whether the message is a draft",
    "isRead": "Whether the recipient has read the message",
    "sentDateTime": "When the message was sent (UTC)",
    "receivedDateTime": "When the message was received (UTC)",
    "hasAttachments": "Whether the message has attachments",
    "isReadReceiptRequested": "Whether a read receipt was requested",
    "isDeliveryReceiptRequested": "Whether a delivery receipt was requested",
    "from": "Sender's name + address",
    "attachments": "Email attachments (array)",
    "evaluationsource": "Source of evaluation rule (DLP)",

    # Custom MS Graph / Defender flexible properties
    "Data": "Event data payload",
    "DataExportType": "Data export operation type",
    "ExtraProperties": "Additional non-standard properties",
    "Fields": "Modified field list",
    "Members": "Group/team members",
    "SourceWorkload": "Source workload (cross-workload events)",
    "UserIp": "User's IP address",

    # ─── Azure Activity Log ─────────────────────────────────────
    "callerIpAddress": "Caller's IP address",
    "category": "Log category (e.g. Administrative, ServiceHealth)",
    "operationName": "Azure ARM operation name",
    "operationVersion": "Azure ARM operation API version",
    "resultType": "Operation result (Success/Failure/Started)",
    "resultSignature": "Result HTTP status code (signature)",
    "resultDescription": "Operation result description",
    "subscriptionId": "Azure subscription GUID",
    "resourceGroupName": "Azure resource group name",
    "resourceProviderName": "Azure resource provider (e.g. Microsoft.Compute)",
    "resourceType": "Azure resource type",
    "resourceId": "Azure resource ID (fully qualified)",
    "tenantId": "Azure AD tenant GUID",
    "correlationId": "Correlation id for distributed tracing",
    "principalOid": "Principal object ID (Azure AD)",
    "claims": "JWT claims for the caller",
    "authorization": "Authorization details (action/scope)",
    "level": "Severity level (Critical/Error/Warning/Informational)",
    "location": "Azure region",
    "properties": "Resource/event properties (provider-specific)",
    "identity": "Caller identity",
    "scope": "Operation scope",
    "eventName": "Event name",
    "status": "Operation status",
    "subStatus": "Operation sub-status",

    # ─── Azure WAF / App Gateway logs ───────────────────────────
    "clientIp": "Client IP",
    "clientIP": "Client IP",
    "instanceId": "WAF instance id",
    "ruleSetType": "OWASP rule set type (e.g. OWASP_3.2)",
    "ruleSetVersion": "OWASP rule set version",
    "ruleId": "OWASP rule id",
    "ruleGroup": "OWASP rule group",
    "messageId": "Message identifier",
    "transactionId": "Transaction id",
    "action": "WAF action (Matched/Blocked/Allowed/Detected)",
    "site": "Site/listener identifier",
    "hostname": "Hostname / target host",
    "requestUri": "HTTP request URI",
    "requestQuery": "HTTP request query string",
    "policyId": "WAF policy id",
    "policyScope": "WAF policy scope",
    "policyScopeName": "WAF policy scope name",
    "originalRequestUriWithArgs": "Original request URI including args",
    "engine": "Detection engine",
    "details": "WAF rule match details",
    "matchVariableValue": "Value that matched the rule variable",
    "matchVariableName": "Name of the rule match variable",

    # ─── App Service / AppGateway / general HTTP ────────────────
    "CsHost": "Host header",
    "CsMethod": "HTTP method",
    "CsUriStem": "URI stem (path)",
    "CsUriQuery": "URI query string",
    "CsBytes": "Client→server bytes",
    "ScStatus": "HTTP response status code",
    "ScSubStatus": "HTTP sub-status",
    "ScWin32Status": "Win32 status code",
    "ScBytes": "Server→client bytes",
    "TimeTaken": "Request processing time (ms)",
    "CIp": "Client IP",
    "SIp": "Server IP",
    "SPort": "Server port",
    "UserAgent": "HTTP user agent",
    "Cookie": "Cookie header",
    "Referer": "HTTP referer",
    "ComputerName": "Server hostname",

    # ─── Kubernetes audit (AKS) ─────────────────────────────────
    "verb": "K8s API verb (get/list/create/update/delete/patch/watch)",
    "user": "User/serviceaccount performing the action",
    "userAgent": "User agent (kubectl version + client info)",
    "namespace": "K8s namespace",
    "objectRef": "Reference to the K8s object",
    "responseStatus": "K8s API response status",
    "stage": "Audit stage (RequestReceived/ResponseStarted/ResponseComplete/Panic)",
    "auditID": "Audit event id",
    "sourceIPs": "Source IP addresses (request chain)",
    "annotations": "Audit annotations (decision metadata)",
    "requestObject": "K8s request body",
    "responseObject": "K8s response body",

    # ─── Entra ID (Azure AD) sign-in / audit ────────────────────
    "userPrincipalName": "User principal name (UPN)",
    "userDisplayName": "User display name",
    "userId": "User object id",
    "appDisplayName": "Application display name",
    "appId": "Application (client) id",
    "ipAddress": "IP address",
    "clientAppUsed": "Client app used (Browser/MobileApp/...)",
    "deviceDetail": "Device detail (browser/OS/displayName)",
    "locationDetails": "Sign-in location (city/state/country/geoCoords)",
    "conditionalAccessStatus": "Conditional Access result (success/failure/notApplied)",
    "isInteractive": "Interactive sign-in",
    "riskDetail": "Risk detail (none/adminGeneratedTemporaryPassword/...)",
    "riskLevelAggregated": "Aggregated risk level (none/low/medium/high)",
    "riskLevelDuringSignIn": "Risk level at sign-in (none/low/medium/high)",
    "riskState": "Risk state (none/confirmedSafe/remediated/dismissed/atRisk/confirmedCompromised)",
    "tokenIssuerType": "Token issuer (AzureAD/ADFederationServices/...)",
    "mfaDetail": "MFA detail",
    "homeTenantId": "Home tenant id",
    "resourceDisplayName": "Resource display name (Azure AD)",
    "resourceTenantId": "Resource tenant id",

    # ─── Exchange Server / Defender for Office ──────────────────
    "Recipient": "Email recipient",
    "RecipientStatus": "Per-recipient delivery status",
    "Sender": "Email sender",
    "OriginalClientIp": "Original client IP (before NAT)",
    "EventId": "Event id",
    "TimestampUtc": "Timestamp (UTC)",
    "Subject": "Email subject",

    # ─── ADFS / Authentication ──────────────────────────────────
    "AuthenticationProvider": "Authentication provider",
    "EventType": "Event type",

    # ─── Microsoft Defender for Cloud Apps ──────────────────────
    "rawEventType": "Raw event type",
    "alertType": "Alert type",
    "displayName": "Display name",
    "policyType": "Policy type",
}


def main() -> int:
    print("=== Microsoft vendor dictionary ===")
    print(f"  Microsoft dictionary size: {len(MICROSOFT_DICT)}\n")

    import yaml

    filled = 0
    yamls_modified = 0
    fill_per_field: Counter[str] = Counter()
    skipped_no_match: Counter[str] = Counter()

    for ds_dir in sorted(BUNDLE_ROOT.glob("*/")):
        yaml_path = ds_dir / "data_source.yaml"
        if not yaml_path.is_file():
            continue
        d = yaml.safe_load(yaml_path.read_text()) or {}
        if d.get("vendor") != "Microsoft":
            continue
        pack = d.get("pack_name", "?")
        fields = d.get("fields") or []
        if not fields:
            continue

        any_changed = False
        new_fields: list[dict[str, Any]] = []
        for f in fields:
            if not isinstance(f, dict):
                new_fields.append(f)
                continue
            existing = (f.get("description") or "").strip()
            if existing:
                new_fields.append(f)
                continue
            name = f.get("name")
            desc = MICROSOFT_DICT.get(name) if name else None
            if desc:
                nf = dict(f)
                nf["description"] = desc
                new_fields.append(nf)
                filled += 1
                fill_per_field[name] += 1
                any_changed = True
            else:
                new_fields.append(f)
                skipped_no_match[f"{pack}:{name}"] += 1

        if any_changed:
            ok, msg = update_one_yaml(yaml_path, new_fields)
            if ok:
                yamls_modified += 1

    print(f"  Newly filled : {filled}")
    print(f"  YAMLs modified : {yamls_modified}\n")
    print("  Top 15 fields filled (across packs):")
    for name, count in fill_per_field.most_common(15):
        print(f"    {name:35s} {count} packs")
    print()
    print(f"  Fields still missing in Microsoft packs (candidates for further dictionaries): "
          f"{sum(skipped_no_match.values())}")
    print("  Top 15:")
    for name, count in skipped_no_match.most_common(15):
        print(f"    {name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
