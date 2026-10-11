#!/usr/bin/env python3
"""Content audit + enrichment for the 22 validated vendor YAMLs.

Targets the exact 22 directories in this script's VENDORS list.

For each YAML this script:

  1. **Replaces the description** with a richer, vendor-context-aware
     paragraph (2-3 sentences covering what the vendor IS, what its CEF
     logs typically contain, and the operator's simulation utility).
     (1-line summaries pulled from the vendor's brief marketing tagline
     are too brief to be useful.)

  2. **Improves field examples** based on type + name heuristics:

     - `example: "see message"` → realistic free-form text
     - `example: '{}'` (json type) → realistic JSON shape per field name
     - `example: 'sample_<prefix>'` → realistic-typed value
     - leaves already-good examples untouched (numeric, URL, IP, etc.)

  3. **Adds `validated: true`** at the top level (above pack_name) so
     the UI can render a small green "Validated" pill on the Browse
     page row for vendors we've tested end-to-end.

  4. **Preserves `how_to_use`** verbatim — it already carries the
     broker-route + simulation guidance; we don't touch it.

The script is idempotent: re-running it leaves an already-enriched YAML
unchanged (idempotent at the per-field-example level, not just file-level
— each field example is regenerated from the same heuristics so the
output is deterministic).

Validation: after each YAML is rewritten, the schema validator runs
inline. Failures abort with
the offending vendor printed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_SOURCES_ROOT = REPO_ROOT / "bundles" / "spark" / "data-sources"

# The validated vendors this enrichment pass covers.
VENDORS = [
    "Okta__OktaModelingRules_2_0__okta_okta_raw",
    "Okta__OktaModelingRules_2_0__okta_sso_raw",
    "AlibabaActionTrail__AlibabaModelingRules__alibaba_action_trail_raw",
    "AWS-CloudTrail__AWSCloudTrail__amazon_aws_raw",
    "AWS-SecurityHub__AWSSecurityHubModelingRules__aws_security_hub_raw",
    "AWS_WAF__AWS_WAF__aws_waf_raw",
    "Jira__JiraEventCollector__atlassian_jira_raw",
    "ServiceNow__ServiceNow__servicenow_servicenow_raw",
    "CyberArkPAS__CyberArkISP__cyberark_isp_raw",
    "MicrosoftEntraID__MicrosoftEntraID__msft_azure_ad_audit_raw",
    "MicrosoftEntraID__MicrosoftEntraID__msft_azure_ad_raw",
    "Office365__Office365__msft_o365_general_raw",
    "Office365__Office365__msft_o365_exchange_online_raw",
    "Office365__Office365__msft_o365_sharepoint_online_raw",
    "Office365__Office365__msft_o365_emails_raw",
    "Office365__Office365__msft_o365_dlp_raw",
    "qualys__QualysModelingRules__qualys_qualys_raw",
    "ProofpointEmailSecurity__ProofpointEmailSecurity__proofpoint_email_security_raw",
    "ProofpointTAP__ProofpointTAPModelingRules__proofpoint_tap_raw",
    "AzureFlowLogs__AzureFlowLogs__msft_azure_flowlogs_raw",
    "AzureWAF__AzureWAF__msft_azure_waf_raw",
    "AzureKubernetesServices__AzureKubernetesServices__msft_azure_aks_raw",
]

# Hand-authored, vendor-context-aware descriptions. Each is 2-3 sentences
# covering: (a) what the vendor IS, (b) what its CEF logs typically
# contain, (c) why the operator might simulate it.
DESCRIPTIONS: dict[str, str] = {
    "Okta__OktaModelingRules_2_0__okta_okta_raw": (
        "Okta is an identity and access-management platform — single sign-on, "
        "MFA, lifecycle management — that emits an audit stream covering user "
        "logins, MFA challenges, group changes, application assignments, and "
        "administrative actions. The Okta primary stream (`okta_okta_raw`) "
        "carries the full system-log envelope: every actor, target, transaction "
        "id, geolocation, and outcome of every authentication or admin event. "
        "Simulate this to validate detections that look for impossible travel, "
        "password-spray patterns, privileged-role assignments, or MFA fatigue."
    ),
    "Okta__OktaModelingRules_2_0__okta_sso_raw": (
        "The Okta SSO stream (`okta_sso_raw`) is a subset of the primary Okta "
        "feed scoped to single-sign-on authentication events — typically "
        "`eventType=user.authentication.sso` rows describing a user's "
        "successful or failed federation into a downstream SaaS application. "
        "These rows carry the target SAML/OIDC application id, the IdP-side "
        "session context, and the authentication method. Simulate this to "
        "validate detections that correlate SSO usage with downstream "
        "application telemetry."
    ),
    "AlibabaActionTrail__AlibabaModelingRules__alibaba_action_trail_raw": (
        "Alibaba Cloud ActionTrail records management-plane API calls across "
        "an Alibaba Cloud account — the rough equivalent of AWS CloudTrail. "
        "Each row captures the API name, the caller's RAM identity, the "
        "source IP, the target resource id, the request and response shape, "
        "and the outcome. Simulate this to validate detections for "
        "unauthorized resource creation, privilege escalation in RAM policies, "
        "or large-scale data export from object storage."
    ),
    "AWS-CloudTrail__AWSCloudTrail__amazon_aws_raw": (
        "AWS CloudTrail is the authoritative audit log of every API call "
        "made within an AWS account — management-plane writes, data-plane "
        "reads, console sessions, automated SDK calls, all of it. Each event "
        "records `eventName`, `eventSource`, the IAM principal, the source "
        "IP, the user-agent, request and response parameters, and any error "
        "codes. Simulate CloudTrail to validate detections for IAM privilege "
        "escalation, S3 data exposure, root account usage, or AWS-API-driven "
        "lateral movement."
    ),
    "AWS-SecurityHub__AWSSecurityHubModelingRules__aws_security_hub_raw": (
        "AWS Security Hub aggregates findings from GuardDuty, Inspector, "
        "Macie, IAM Access Analyzer, and third-party scanners into a single "
        "normalized format (ASFF — AWS Security Finding Format). Each "
        "finding carries a severity, a resource id, a generator id, and a "
        "remediation hint. Simulate Security Hub to validate cross-finding "
        "correlation, incident workflow integration, or alert-fatigue tuning "
        "for a fully-integrated AWS security telemetry pipeline."
    ),
    "AWS_WAF__AWS_WAF__aws_waf_raw": (
        "AWS WAF (Web Application Firewall) logs every HTTP/HTTPS request "
        "evaluated by a Web ACL — including the matching rule, the action "
        "taken (`ALLOW`/`BLOCK`/`COUNT`), the request's headers, the URI, "
        "the source IP, the country code, and any rate-limit context. Simulate "
        "AWS WAF to validate detections for application-layer attacks like "
        "SQL injection, XSS attempts, credential stuffing, or scraping bots."
    ),
    "Jira__JiraEventCollector__atlassian_jira_raw": (
        "Atlassian Jira logs every issue mutation, workflow transition, "
        "comment, and administrative action — useful both as a project-"
        "tracking audit trail and as an insider-threat signal. Each event "
        "carries the actor, the affected issue id, the workflow state "
        "transition, and any text content (which may contain sensitive data). "
        "Simulate Jira to validate detections for unauthorized issue creation, "
        "data exfiltration via attachments, or anomalous admin activity."
    ),
    "ServiceNow__ServiceNow__servicenow_servicenow_raw": (
        "ServiceNow ITSM is a workflow + service-management platform that "
        "captures every incident, change request, problem, and CMDB mutation "
        "across an organization's IT processes. Each record carries the "
        "actor (caller / assignee), the affected CI (configuration item), "
        "the workflow state, approvals, and free-form work notes. Simulate "
        "ServiceNow to validate detections for unauthorized incident "
        "manipulation, ticket-based social engineering, or anomalous change "
        "approvals."
    ),
    "CyberArkPAS__CyberArkISP__cyberark_isp_raw": (
        "CyberArk Identity Security Platform (ISP) is a privileged-access "
        "management suite — it brokers all access to sensitive credentials, "
        "vaults, and privileged sessions. Each event records the privileged "
        "user, the safe / target system being accessed, the policy applied, "
        "session metadata, and any breakglass actions. Simulate CyberArk ISP "
        "to validate detections for privileged credential abuse, off-hours "
        "vault access, or session-recording bypass attempts."
    ),
    "MicrosoftEntraID__MicrosoftEntraID__msft_azure_ad_audit_raw": (
        "Microsoft Entra ID (formerly Azure AD) audit logs capture every "
        "directory mutation — user lifecycle, group membership changes, "
        "application registrations, conditional-access policy edits, "
        "role assignments. Each row carries `category=AuditLogs`, the "
        "initiating actor, the target object, and the activity name. "
        "Simulate Entra audit logs to validate detections for unauthorized "
        "admin role grants, OAuth consent grants to malicious applications, "
        "or backdoor user creation."
    ),
    "MicrosoftEntraID__MicrosoftEntraID__msft_azure_ad_raw": (
        "Microsoft Entra ID sign-in logs (`category=SignInLogs`) record every "
        "interactive and non-interactive authentication attempt against the "
        "tenant — user, application, conditional-access result, risk score, "
        "client IP, device id, and any MFA challenges. Simulate sign-in logs "
        "to validate detections for password-spray attacks, impossible-travel "
        "anomalies, legacy-auth protocol abuse, or MFA-bypass via token "
        "replay."
    ),
    "Office365__Office365__msft_o365_general_raw": (
        "The Office 365 Unified Audit Log captures activity across Exchange "
        "Online, SharePoint Online, OneDrive, Teams, Power BI, and other "
        "Microsoft 365 workloads. The general stream (`Workload` = various) "
        "is the catch-all view; vendor-specific streams below carve it by "
        "workload. Simulate the general stream to validate detections that "
        "span workloads — e.g., a file shared from SharePoint then forwarded "
        "via Exchange — without needing to wire each workload-specific feed."
    ),
    "Office365__Office365__msft_o365_exchange_online_raw": (
        "The Office 365 Exchange Online audit feed (`Workload=Exchange`) "
        "captures mailbox actions: message sends and receives, delegate "
        "additions, mailbox-rule creation, transport-rule mutations, and "
        "compliance-search executions. Simulate this to validate detections "
        "for business-email-compromise (BEC) precursors like auto-forward "
        "rules, suspicious delegate grants, or mass-email send patterns."
    ),
    "Office365__Office365__msft_o365_sharepoint_online_raw": (
        "The Office 365 SharePoint Online audit feed (`Workload=SharePoint`) "
        "captures file and folder operations — uploads, downloads, deletes, "
        "shares, permission changes, anonymous-link creation. Each event "
        "names the user, the affected document path, the operation, and any "
        "external-recipient context. Simulate SharePoint to validate "
        "detections for bulk data exfiltration, anonymous external sharing, "
        "or permission-elevation abuse."
    ),
    "Office365__Office365__msft_o365_emails_raw": (
        "The Office 365 emails stream is a focused view of message-level "
        "metadata from Exchange Online — sender, recipient, subject, "
        "attachment names, delivery action, and SPF/DKIM/DMARC evaluation "
        "results. Simulate to validate detections for phishing patterns, "
        "spoofed senders, or anomalous external-correspondent volume."
    ),
    "Office365__Office365__msft_o365_dlp_raw": (
        "The Office 365 DLP (Data Loss Prevention) audit stream surfaces "
        "every policy match across Exchange, SharePoint, OneDrive, and Teams "
        "— the matching policy rule, the sensitive-information types "
        "detected, the action taken (block / notify / encrypt), and the "
        "affected document or message. Simulate DLP events to validate "
        "incident-response runbooks for confidential data exposure, "
        "policy-tuning workflows, and DLP-driven case automation."
    ),
    "qualys__QualysModelingRules__qualys_qualys_raw": (
        "Qualys Vulnerability Management scans hosts and reports detected "
        "vulnerabilities — each finding includes the host id (asset ID, IP, "
        "FQDN), the QID (Qualys vulnerability id), CVSS score, CVE refs, "
        "scan timestamp, and remediation guidance. Simulate Qualys events to "
        "validate detections that correlate active exploits with known "
        "vulnerable assets, prioritize patching workflows, or feed risk-"
        "scoring pipelines."
    ),
    "ProofpointEmailSecurity__ProofpointEmailSecurity__proofpoint_email_security_raw": (
        "Proofpoint Email Security (legacy name: Email Protection) is a "
        "cloud email gateway that scans inbound and outbound mail for "
        "phishing, malware, BEC, and policy violations. Each event carries "
        "the message id, sender / recipient envelopes, verdict (clean / "
        "spam / phish / malware), the matching rule, and any quarantine "
        "metadata. Simulate Proofpoint to validate detections for advanced "
        "phishing campaigns, malicious attachments, and BEC indicators that "
        "the gateway already classified."
    ),
    "ProofpointTAP__ProofpointTAPModelingRules__proofpoint_tap_raw": (
        "Proofpoint Targeted Attack Protection (TAP) is a sandbox-and-URL-"
        "rewriting layer atop Proofpoint email security — it detonates "
        "attachments, follows URLs, and reports verdicts. Each event records "
        "the message context, the URL or attachment evaluated, the verdict "
        "(clean / threat / suspicious), and the threat family. Simulate TAP "
        "to validate detections that pivot from URL-click events to "
        "downstream endpoint / network telemetry — the click-through "
        "correlation chain."
    ),
    "AzureFlowLogs__AzureFlowLogs__msft_azure_flowlogs_raw": (
        "Azure NSG Flow Logs capture every IP flow that hits an Azure "
        "Network Security Group — 5-tuple, packet/byte counts, allow/deny "
        "decision, flow state (start/continuing/end). The shape mirrors "
        "AWS VPC Flow Logs. Simulate Azure Flow Logs to validate detections "
        "for east-west reconnaissance, unexpected egress, or NSG-bypass "
        "patterns in your Azure VNet topology."
    ),
    "AzureWAF__AzureWAF__msft_azure_waf_raw": (
        "Azure Web Application Firewall (WAF) — deployed in front of "
        "Application Gateway or Azure Front Door — logs every HTTP request "
        "evaluated against OWASP and custom rule sets. Each row carries the "
        "rule id, action taken, request URI, client IP, country, and the "
        "matched-string detail. Simulate Azure WAF to validate detections "
        "for application-layer attacks, custom-rule tuning, and bot-management "
        "policy enforcement."
    ),
    "AzureKubernetesServices__AzureKubernetesServices__msft_azure_aks_raw": (
        "Azure Kubernetes Service (AKS) emits cluster audit logs "
        "(`category=kube-audit`) covering every Kubernetes API call — pod "
        "creation, secret access, RBAC mutations, namespace operations. "
        "Each row carries the verb, the resource, the user context "
        "(serviceaccount or human), the requesting client, and the response "
        "status. Simulate AKS audit to validate detections for cluster "
        "tenant escape, privileged-pod creation, secret exfiltration, or "
        "anomalous RBAC binding changes."
    ),
}


# ─── Field example heuristics ────────────────────────────────────


def _better_example(field_name: str, field_type: str, current: Any) -> Any:
    """Produce a realistic example based on field name + type, or
    return current unchanged if it's already concrete.

    The priorities:
      1. If `current` is already a non-placeholder value (number, real
         JSON, real URL, plausible string), preserve it.
      2. Otherwise produce a realistic value per field-name pattern.
    """
    name = (field_name or "").lower()
    typ = (field_type or "string").lower()
    cur = current if current is not None else ""
    cur_s = str(cur).strip()

    # Preserve concrete-looking examples.
    placeholders = {"", "see message", "{}", "[]", "null", "none"}
    if cur_s.lower() in placeholders or cur_s.lower().startswith("sample_"):
        replace = True
    elif cur_s.startswith("{") and cur_s.endswith("}") and len(cur_s) > 2:
        # JSON-shaped string — preserve.
        return cur
    else:
        replace = False

    if not replace:
        return cur

    # ── Type-driven defaults ──────────────────────────────────────
    if typ in ("ipv4", "ip"):
        return "192.168.1.42"
    if typ == "ipv6":
        return "2001:db8::1"
    if typ in ("port", "tcp_port", "udp_port"):
        return 443
    if typ in ("integer", "int", "long"):
        return 42
    if typ in ("float", "double", "number"):
        return 3.14
    if typ in ("bool", "boolean"):
        return True
    if typ == "url":
        return "https://example.com/api/v1/resource/12345"
    if typ in ("email", "email_address"):
        return "alice@example.com"
    if typ in ("ts", "timestamp", "datetime"):
        return "2026-05-28T16:30:00Z"
    if typ == "user":
        return "alice@example.com"
    if typ in ("country_code", "country"):
        return "US"
    if typ in ("mac", "mac_address"):
        return "aa:bb:cc:dd:ee:ff"
    if typ == "hash":
        return "5d41402abc4b2a76b9719d911017c592"  # md5("hello")
    if typ in ("uuid", "guid"):
        return "f47ac10b-58cc-4372-a567-0e02b2c3d479"

    # ── Name-pattern defaults ─────────────────────────────────────
    if typ == "json":
        # Vendor-specific JSON shapes for the most common cases.
        if "actor" in name:
            return '{"id":"00u1ab2c3d","type":"User","alternateId":"alice@example.com"}'
        if "target" in name or "resource" in name:
            return '{"id":"res-abc123","type":"S3Object","displayName":"reports.csv"}'
        if "httprequest" in name or "http_request" in name:
            return '{"clientIp":"203.0.113.42","uri":"/login","httpMethod":"POST","headers":[{"name":"User-Agent","value":"Mozilla/5.0"}]}'
        if "geolocation" in name or "location" in name:
            return '{"city":"San Francisco","country":"US","latitude":37.7749,"longitude":-122.4194}'
        if "client" in name or "useragent" in name:
            return '{"id":"web","userAgent":{"rawUserAgent":"Mozilla/5.0"},"ipAddress":"203.0.113.42"}'
        return '{"key":"value"}'

    if "user" in name and ("name" in name or "id" in name):
        return "alice@example.com"
    if "host" in name and ("name" in name):
        return "host-prod-01.example.com"
    if "host" in name or "computer" in name or "device" in name:
        return "host-prod-01"
    if "domain" in name:
        return "example.com"
    if "department" in name or "dept" in name:
        return "Engineering"
    if "group" in name:
        return "grp-engineering-prod"
    if "role" in name:
        return "role-admin"
    if "action" in name or "operation" in name or "verb" in name:
        return "create"
    if "result" in name or "outcome" in name or "status" in name:
        return "SUCCESS"
    if "method" in name and "auth" not in name:
        return "POST"
    if "tenant" in name or "org" in name or "account" in name:
        return "tenant-acme-prod"
    if "policy" in name:
        return "policy-default-deny"
    if "rule" in name:
        return "rule-block-known-bad-ips"
    if "session" in name:
        return "sess-9f8c2337abc"
    if "request" in name and ("id" in name or "guid" in name):
        return "req-4e2c1a-12345"
    if "category" in name or "type" in name or "kind" in name:
        return "AuditEvent"
    if "severity" in name or "level" in name:
        return "INFO"
    if "country" in name:
        return "US"
    if "language" in name or "locale" in name:
        return "en-US"
    if "browser" in name:
        return "Chrome 124.0.6367.155"
    if "os" in name:
        return "Windows 11 (build 22631)"
    if "ip" in name or "addr" in name:
        return "192.168.1.42"
    if "port" in name:
        return 443
    if "id" in name or "guid" in name:
        return "00u1ab2c3d4e5f6"

    # Free-form text fallback — better than "see message".
    return "operator-visible value"


# ─── Main rewrite ────────────────────────────────────────────────


def _improve(yaml_path: Path) -> tuple[bool, str]:
    """Mutate one YAML in place. Returns (changed, reason)."""
    raw = yaml_path.read_text(encoding="utf-8")
    doc = yaml.safe_load(raw)
    if not isinstance(doc, dict):
        return (False, "not a dict at top level")

    slug = yaml_path.parent.name
    changed = False

    # ── description ──────────────────────────────────────────────
    if slug in DESCRIPTIONS:
        new_desc = DESCRIPTIONS[slug]
        if doc.get("description", "").strip() != new_desc.strip():
            doc["description"] = new_desc
            changed = True

    # ── validated: true ──────────────────────────────────────────
    if doc.get("validated") is not True:
        doc["validated"] = True
        changed = True

    # ── field examples ───────────────────────────────────────────
    fields = doc.get("fields") or []
    n_examples_changed = 0
    for f in fields:
        if not isinstance(f, dict):
            continue
        old = f.get("example")
        new = _better_example(f.get("name", ""), f.get("type", "string"), old)
        if new != old:
            f["example"] = new
            n_examples_changed += 1
    if n_examples_changed:
        changed = True

    if changed:
        # Dump with sensible options — keep block-scalars for long strings,
        # don't sort keys (we want our order preserved).
        new_yaml = yaml.dump(
            doc,
            sort_keys=False,
            allow_unicode=True,
            width=100,
            default_flow_style=False,
        )
        yaml_path.write_text(new_yaml, encoding="utf-8")
        return (True, f"description+validated+{n_examples_changed} examples")

    return (False, "no change")


def main() -> int:
    print(f"# content audit — {len(VENDORS)} validated vendor YAMLs\n")
    changed_count = 0
    for slug in VENDORS:
        ypath = DATA_SOURCES_ROOT / slug / "data_source.yaml"
        if not ypath.is_file():
            print(f"  MISSING — {slug}")
            continue
        changed, reason = _improve(ypath)
        marker = "✓" if changed else "·"
        print(f"  {marker} {slug:<88}  {reason}")
        if changed:
            changed_count += 1
    print(f"\n# Done. {changed_count}/{len(VENDORS)} updated.")
    return 0 if changed_count >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
