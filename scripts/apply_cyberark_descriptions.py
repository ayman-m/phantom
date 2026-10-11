#!/usr/bin/env python3
"""CyberArk vendor dictionary.

# Why

CyberArk spans several packs (CyberArkIdentity, CyberArkPAS, CyberArkEPV,
plus EPM, PTA, etc.) whose fields lack descriptions.

# Sources

* CyberArk Identity (Idaptive) audit log schema:
  https://docs.cyberark.com/idaptive/Latest/en/Content/Logs/audit-logs.htm
* CyberArk PAS / Privileged Access Manager event schema:
  https://docs.cyberark.com/PAS/Latest/en/Content/PASIMP/SIEM_Application.htm
* CyberArk EPV vault activity events:
  https://docs.cyberark.com/PAS/Latest/en/Content/PASIMP/PrivCloud-VendorLog.htm
* CyberArk EPM endpoint privilege management events:
  https://docs.cyberark.com/EPM/Latest/en/Content/SIEM/EPM-SIEMEvents.htm
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


CYBERARK_DICT: dict[str, str] = {
    # ─── CyberArk Identity audit log fields ─────────────────────
    # Operator/principal
    "ID": "Event id",
    "UserName": "User name performing the action",
    "TargetUser": "Target user the action was performed on",
    "TargetUserID": "Target user id",
    "EnrollProfileUser": "User being enrolled (device enrollment)",
    "EmailAddress": "User email address",
    "Cname": "Canonical (CN) name",
    "Uuid": "Event UUID",
    "EntityType": "Entity type (User/Device/Role/Application/...)",
    "EntityUuid": "Entity UUID",
    "NewEntity": "New entity state (post-change)",
    "OldEntity": "Old entity state (pre-change)",
    "Alias": "User/entity alias",
    "Thumbprint": "Certificate thumbprint",
    "Description": "Event description",
    "_TableName": "Audit table name (Identity-internal)",
    "Type": "Event type",
    "Level": "Event severity level",

    # Tenancy
    "Tenant": "Identity tenant id",
    "AffectedTenant": "Tenant affected by the operation",

    # Application context
    "ApplicationID": "Application client id",
    "ApplicationName": "Application name",
    "AppName": "Application name",
    "ApplicationType": "Application type",
    "ProxyId": "Proxy server id (Identity Connector)",
    "ConnectorUuid": "Identity Connector UUID",

    # Request/device
    "RequestHostName": "Hostname the request came from",
    "RequestIsMobileDevice": "Whether the request was from a mobile device",
    "RequestDeviceOS": "Operating system of the requesting device",
    "ClientAddress": "Client IP address",
    "HostAddress": "Server host address",
    "DeviceID": "Device id",
    "DeviceName": "Device name",
    "MachineName": "Machine hostname",
    "SessionId": "Session id",

    # Role/permission
    "RoleId": "Role id",
    "Role": "Role name",
    "SetPath": "Permission set / vault path",
    "OU": "Organizational Unit (LDAP)",
    "Key": "Setting/property key",
    "Value": "Setting/property value",

    # Directory service sync
    "DSName": "Directory Service name (AD/LDAP)",
    "DSType": "Directory Service type (AD/LDAP/Generic)",
    "DSUuid": "Directory Service UUID",
    "DirectoryServiceUuid": "Directory Service UUID",
    "DirectoryServicePartnerName": "Directory Service partner name",
    "SyncAction": "Sync action (create/update/delete)",
    "SyncResult": "Sync result (success/failure)",
    "SyncActionReason": "Reason code for sync action",
    "LocalAccountUuid": "Local CyberArk account UUID",

    # State transitions
    "OldState": "Old state (pre-change)",
    "NewState": "New state (post-change)",
    "UserState": "User state (active/disabled/locked/...)",
    "DeleteReason": "Reason the entity was deleted",
    "FailureReason": "Reason the operation failed",
    "FailedMessage": "Failure message text",

    # Time
    "WhenLogged": "When the event was logged",
    "WhenOccurred": "When the event occurred",

    # Impersonation
    "ImpersonateTargetName": "User being impersonated (target)",
    "ImpersonatorUuid": "Impersonator (actor) UUID",

    # Licensing
    "LicenseType": "Current license type",
    "NewLicenseType": "New license type (after change)",

    # Source/target for relationship events
    "From": "Source of the operation",
    "To": "Destination/target of the operation",
    "Target": "Operation target",

    # ─── CyberArk PAS / Privileged Access Manager ────────────────
    "timestamp": "Event timestamp",
    "applicationCode": "CyberArk application code",
    "auditCode": "Audit code (event-specific identifier)",
    "auditType": "Audit type (logon/access/admin/...)",
    "source": "Event source (component name)",
    "actionType": "Action type",
    "component": "PAS component (Vault/PVWA/CPM/PSM/PTA)",
    "serviceName": "Service name",
    "accessMethod": "Access method (RDP/SSH/HTTPS/Connector)",
    "accountId": "Privileged account id",
    "target": "Operation target",
    "issuer": "Event issuer / actor",
    "stationId": "Station identifier",
    "stationProtocol": "Station protocol",
    "stationName": "Station name",
    "trail": "Audit trail id",
    "sessionDuration": "Session duration (seconds)",
    "sessionRecordingFileName": "Session recording file name",
    "providerId": "Provider id",
    "container": "Account container/safe",
    "iso8601": "ISO 8601 timestamp",
    "extraDetails": "Extra event details (JSON)",

    # ─── CyberArk EPV (vault audit events) ───────────────────────
    "userType": "User type (Internal/External/...)",
    "fromIp": "Source IP",
    "safeName": "Vault safe name",
    "objectName": "Vault object name",
    "objectType": "Vault object type",
    "categoryName": "Object category name",
    "categoryValue": "Object category value",
    "platformId": "Platform id (account template)",
    "operationType": "Operation type",
    "passwordChangeMethod": "Password change method (CPM/Manual/...)",
    "policyId": "Policy id",
    "policyName": "Policy name",
    "address": "Resource address",

    # ─── CyberArk EPM (endpoint privilege management) ────────────
    "agentId": "EPM agent id",
    "computerName": "Computer hostname",
    "userPrincipal": "User principal name",
    "executableName": "Executable name",
    "executablePath": "Executable path",
    "executableHash": "Executable hash",
    "ruleName": "EPM policy rule name",
    "ruleId": "EPM policy rule id",
    "verdict": "EPM verdict (Allow/Block/Elevate)",
    "publisher": "Code publisher",
    "publisherCommonName": "Code publisher common name",
    "trusted": "Whether the executable is trusted",

    # ─── CyberArk PTA (Privileged Threat Analytics) ─────────────
    "score": "PTA risk/anomaly score",
    "alertType": "Alert type",
    "anomaly": "Anomaly type detected",
}


def main() -> int:
    print("=== CyberArk vendor dictionary ===")
    print(f"  Dictionary size: {len(CYBERARK_DICT)}\n")

    import yaml

    filled = 0
    yamls_modified = 0
    fill_per_field: Counter[str] = Counter()
    skipped: Counter[str] = Counter()

    for ds_dir in sorted(BUNDLE_ROOT.glob("*/")):
        yaml_path = ds_dir / "data_source.yaml"
        if not yaml_path.is_file():
            continue
        d = yaml.safe_load(yaml_path.read_text()) or {}
        if d.get("vendor") != "CyberArk":
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
            if (f.get("description") or "").strip():
                new_fields.append(f)
                continue
            name = f.get("name")
            desc = CYBERARK_DICT.get(name) if name else None
            if desc:
                nf = dict(f)
                nf["description"] = desc
                new_fields.append(nf)
                filled += 1
                fill_per_field[name] += 1
                any_changed = True
            else:
                new_fields.append(f)
                skipped[f"{pack}:{name}"] += 1
        if any_changed:
            ok, msg = update_one_yaml(yaml_path, new_fields)
            if ok:
                yamls_modified += 1

    print(f"  Newly filled : {filled}")
    print(f"  YAMLs modified : {yamls_modified}\n")
    print(f"  Skipped (no dictionary entry): {sum(skipped.values())}")
    print("  First 20:")
    for n, _ in skipped.most_common(20):
        print(f"    {n}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
