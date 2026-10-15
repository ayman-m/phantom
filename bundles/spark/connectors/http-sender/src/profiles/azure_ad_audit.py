"""The `azure_ad_audit` event profile: synthetic Microsoft Graph `directoryAudit` objects.

Each event has the shape of one object from Graph's `GET /auditLogs/directoryAudits`, as the `azure_ad_audit` Cribl
source parses it into `msft_azure_ad_audit_raw` and normalizes it into `cloud_audit_logs` (`azure_ad_audit_logs`).
It is meant for the `cribl_azure_ad_audit` destination (measured on a Cortex tenant: five detectors fired;
those were the first normalized Azure AD audit rows the tenant had, as thousands of syslog rows had produced none).

Every scenario is ONE audit operation that fired its detector. The sign-in half of Azure AD (`azure_ad_signins`)
produced no normalized feed on that tenant and has no profile; the audit shapes that stayed silent (MFA disabled,
multiple admin role removals, first PowerShell operation, account deletion) are not here either.

The admin actor, its object id, the targets (policy, domain) and every id are generated per call, so a replay looks
like a first-time actor; the admin's address is a real one from the Saudi home pool. `target_user` instead names one of
the organization's people (login, email or the part before the @): the admin is then `<local>.adm@<email domain>` and the
calls come from that person's own home address. `activityDateTime` is UTC with seven fractional digits, as Graph returns it.
The event shape carries no tenant or subscription id, so `cloud.azure` of the organization is not read here.

`benign_activity` is the baseline and its identities are STABLE: the organization's IT staff who have Azure access
(`<local>.adm@<email domain>`, the helpdesk analyst resets passwords) and its people who may log on and have Azure access
(`cloud_access`) as the ordinary users (their email), each with one object id (a pure function of the UPN) and one home
address (`home_ip`). They do the ordinary things a directory sees all day: update a user's job title, add or
remove a member of an ordinary group, reset a password (the helpdesk administrator, on a user), change one's own password,
assign an ordinary app to a user, and now and then add a new-hire user. None of them is an operation one of the detectors
above fired on; roles, PIM, Conditional Access, federation and domains are never touched.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from runtime.organization_reader import OrganizationUnavailable
from runtime.organization_view import OrganizationView

from . import _fresh, _org, ippools
from .okta import _times

# The profile interface (see profiles/__init__.py).
NAME = "azure_ad_audit"
DESCRIPTION = ("Microsoft Graph directoryAudit objects for the cribl_azure_ad_audit destination: Conditional Access policy "
               "deleted, PIM alert disabled, PIM role settings changed, federation settings changed, unverified domain added; "
               "benign_activity is a stable pool of admins and users doing ordinary directory work.")
EXPECTED_DATASET = "cribl_azure_ad_audit"
EXPECTED_DATASETS = ("cribl_azure_ad_audit",)
CRIBL_DESTINATIONS = ("cribl_azure_ad_audit",)
DEFAULT_DESTINATION = "cribl_azure_ad_audit"
CRIBL_ONLY = True
TEST_ID_FIELD = "id"
TIME_FIELD = "activityDateTime"

_NAMES = ("northwind", "contoso", "fabrikam", "tailspin", "litware", "adatum", "proseware", "wingtip")


class _Admin:
    def __init__(self, upn: str, name: str, oid: str, ip: str, person: dict[str, Any] | None = None) -> None:
        self.upn, self.name, self.oid, self.ip, self.person = upn, name, oid, ip, person


class _Ctx:
    def __init__(self, view: OrganizationView, seed: int | None) -> None:
        self.rng = random.Random(seed)
        self.view = view
        self.domain = view.email_domain

    def hexs(self, n: int) -> str:
        return _fresh.hexs(self.rng, n)

    def guid(self) -> str:
        return _fresh.guid(self.rng)

    def admin(self, person: dict[str, Any] | None) -> _Admin:
        """The acting administrator: the organization's `person` the caller named (their own home address), else a fresh one."""
        local = _org.local_part(person) if person else _fresh.handle(self.rng)
        ip = ippools.home_for(self.rng.randrange(len(ippools.HOME)))[0]  # drawn even for a named person: the rest of a seeded call is the same either way
        name = _org.display(person) if person else local.replace(".", " ").title()
        if person:
            ip = _org.home(person)[0]
        return _Admin(f"{local}.adm@{self.domain}", f"{name} (admin)", self.guid(), ip, person)

    def audit(self, who: _Admin, activity: str, category: str, service: str, op: str,
              targets: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "id": f"Directory_{self.guid()}_{self.rng.randint(10000, 99999)}", "category": category,
            "correlationId": self.guid(), "result": "success", "resultReason": "", "activityDisplayName": activity,
            "activityDateTime": "", "loggedByService": service, "operationType": op,
            "initiatedBy": {"user": {"id": who.oid, "displayName": who.name, "userPrincipalName": who.upn,
                                     "ipAddress": who.ip, "userType": "Member", "homeTenantId": None,
                                     "homeTenantName": None}, "app": None},
            "targetResources": targets, "additionalDetails": [{"key": "UserType", "value": "Member"}],
        }

    def target(self, kind: str, name: str | None = None, props: list[tuple[str, Any, Any]] | None = None) -> dict[str, Any]:
        return {"id": self.guid(), "displayName": name, "type": kind, "userPrincipalName": None, "groupType": None,
                "modifiedProperties": [{"displayName": k, "oldValue": old, "newValue": new} for k, old, new in (props or [])]}

    def fresh_domain(self) -> str:
        return f"{self.rng.choice(_NAMES)}-{self.hexs(6)}.example"


# -- scenario recipes: (c, actor, repetition, source_ip) -> one repetition's events --------------------------------------

def _ca_policy_deleted(c, who, k, src):
    return [c.audit(who, "Delete conditional access policy", "Policy", "Conditional Access", "Delete", [
        c.target("Policy", "Require MFA for all users",
                 [("ConditionalAccessPolicy", '{"displayName":"Require MFA for all users","state":"enabled"}', None)])])]


def _pim_alert_disabled(c, who, k, src):
    return [c.audit(who, "Disable PIM Alert", "RoleManagement", "PIM", "Update", [
        c.target("Directory", "Alert", [("AlertDefinitionId", "RolesAssignedOutsidePimAlert", None), ("IsEnabled", "true", "false")])])]


def _pim_role_setting_changed(c, who, k, src):
    return [c.audit(who, "Update role setting in PIM", "RoleManagement", "PIM", "Update", [
        c.target("Role", "Global Administrator",
                 [("ExpirationRule", '{"maximumDuration":"PT8H"}', '{"maximumDuration":"P365D"}')])])]


def _federation_modified(c, who, k, src):
    return [c.audit(who, "Set federation settings on domain", "DirectoryManagement", "Core Directory", "Update", [
        c.target("Domain", c.fresh_domain(), [("LiveType", "Managed", "Federated"), (
            "IssuerUri", None, f"http://sts-{c.hexs(6)}.example/adfs/services/trust")])])]


def _unverified_domain_added(c, who, k, src):
    return [c.audit(who, "Add unverified domain", "DirectoryManagement", "Core Directory", "Add", [
        c.target("Domain", c.fresh_domain())])]


def _stamp(c: _Ctx, event: dict[str, Any], when: datetime) -> None:
    event["activityDateTime"] = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond:06d}{c.rng.randint(0, 9)}Z"


_TABLE: dict[str, tuple[Callable, int]] = {
    "ca_policy_deleted": (_ca_policy_deleted, 1),
    "pim_alert_disabled": (_pim_alert_disabled, 1),
    "pim_role_setting_changed": (_pim_role_setting_changed, 1),
    "federation_modified": (_federation_modified, 1),
    "unverified_domain_added": (_unverified_domain_added, 1),
}
BENIGN_SCENARIOS = ("benign_activity",)
SCENARIOS = tuple(_TABLE) + BENIGN_SCENARIOS
# The fewest events that make a scenario's recipe complete (a larger count repeats the recipe). Benign: any count.
MIN_COUNT = {name: steps for name, (_, steps) in _TABLE.items()}
# What an omitted `count` means for a scenario that is not a recipe.
DEFAULT_COUNT = {"benign_activity": 20}

# -- benign_activity: a stable pool, ordinary directory work --------------------------------------------------------------

BENIGN_GROUPS = ("Finance Team", "Marketing Team", "Project Atlas", "All Staff", "Engineering", "Sales EMEA", "HR Portal Users", "VPN Users")
BENIGN_APPS = ("Salesforce", "ServiceNow", "Slack", "Workday", "Zoom", "Jira Cloud")
# (property, old, new) changes of an `Update user`: Graph writes the values as JSON strings.
# The new value of a `Manager` change is the user's manager in the organization (filled in where it is used).
_PROFILE_CHANGES = (("JobTitle", '"Analyst"', '"Senior Analyst"'), ("JobTitle", '"Associate"', '"Specialist"'),
                    ("Department", '"Finance"', '"Finance and Planning"'), ("OfficeLocation", '"Riyadh"', '"Dammam"'),
                    ("Manager", None, None))
_NEW_HIRES = tuple(f"{first}.{last}" for first in ("hanan", "salman", "mona", "rakan", "aisha", "badr")
                   for last in ("alshehri", "alharbi", "alsaadi", "alnajjar"))
_BENIGN_OPS = (("update_user", 28), ("add_member", 18), ("remove_member", 8), ("reset_password", 14), ("change_password", 14),
               ("app_role_assignment", 12), ("add_user", 6))


def _json(value: str) -> str:
    return f'"{value}"'


def _persona(c: _Ctx, person: dict[str, Any], *, admin: bool) -> _Admin:
    """An organization person as an actor or a target: UPN, display name, object id and address are pure functions of them.
    An administrator's UPN is `<local>.adm@<email domain>`; an ordinary user's is their email."""
    upn = f"{_org.local_part(person)}.adm@{c.domain}" if admin else _org.email(person)
    name = _org.display(person) + (" (admin)" if admin else "")
    return _Admin(upn, name, _fresh.stable_guid("azure|user|" + upn), _org.home(person)[0], person)


def _user_target(c: _Ctx, who: _Admin, props: list[tuple[str, Any, Any]] | None = None) -> dict[str, Any]:
    return {**c.target("User", who.name.replace(" (admin)", ""), props), "id": who.oid, "userPrincipalName": who.upn}


def _benign_event(c: _Ctx, op: str) -> dict[str, Any]:
    admin = _persona(c, c.rng.choice(c.admins), admin=True)
    user = _persona(c, c.users[c.rng.randrange(len(c.users))], admin=False)
    if op == "update_user":
        prop, old, new = c.rng.choice(_PROFILE_CHANGES)
        if prop == "Manager":
            new = _json(_org.display(_org.manager_of(c.view, user.person)))
        return c.audit(admin, "Update user", "UserManagement", "Core Directory", "Update",
                       [_user_target(c, user, [(prop, old, new), ("Included Updated Properties", None, _json(prop))])])
    if op in ("add_member", "remove_member"):
        group = c.rng.choice(BENIGN_GROUPS)
        gid, added = _fresh.stable_guid("azure|group|" + group), op == "add_member"
        group_target = {**c.target("Group", group, [("Group.ObjectID", None, _json(gid)) if added else ("Group.ObjectID", _json(gid), None),
                                                    ("Group.DisplayName", None, _json(group)) if added else ("Group.DisplayName", _json(group), None)]),
                        "id": gid}
        return c.audit(admin, "Add member to group" if added else "Remove member from group", "GroupManagement", "Core Directory",
                       "Assign" if added else "Unassign", [_user_target(c, user), group_target])
    if op == "reset_password":
        helpdesk = _persona(c, c.helpdesk, admin=True)
        return c.audit(helpdesk, "Reset password (by admin)", "UserManagement", "Core Directory", "Update",
                       [_user_target(c, user, [("TargetId.UserType", None, _json("Member"))])])
    if op == "change_password":
        return c.audit(user, "Change password (self-service)", "UserManagement", "Core Directory", "Update",
                       [_user_target(c, user, [("TargetId.UserType", None, _json("Member"))])])
    if op == "app_role_assignment":
        app = c.rng.choice(BENIGN_APPS)
        sp = {**c.target("ServicePrincipal", app, [("AppRole.Value", None, _json("User")), ("AppRole.DisplayName", None, _json("User")),
                                                     ("ServicePrincipal.DisplayName", None, _json(app))]),
              "id": _fresh.stable_guid("azure|app|" + app)}
        return c.audit(admin, "Add app role assignment grant to user", "ApplicationManagement", "Core Directory", "Assign",
                       [_user_target(c, user), sp])
    hire = c.rng.choice(_NEW_HIRES)
    upn = f"{hire}@{c.domain}"
    target = {**c.target("User", hire.replace(".", " ").title(), [("UserPrincipalName", None, upn)]),
              "id": _fresh.stable_guid("azure|user|" + upn), "userPrincipalName": upn}
    return c.audit(admin, "Add user", "UserManagement", "Core Directory", "Add", [target])


def _benign_activity(c: _Ctx, count: int, end: datetime, spread_seconds: int) -> list[dict[str, Any]]:
    """`count` ordinary directory operations by the stable pool, at random moments of the window (the first at its start,
    the last at `end`)."""
    c.users = _org.cloud_people(c.view, "azure")
    c.admins = _org.administrators(c.users)
    if not c.admins:
        raise OrganizationUnavailable(
            f"organization {c.view.id!r} has nobody in department IT with 'azure' in cloud_access: the benign directory "
            "work needs administrators to do it")
    # The helpdesk analyst resets passwords; without one, the first administrator does.
    c.helpdesk = next((p for p in c.admins if "helpdesk" in p.get("title", "").lower()), c.admins[0])
    out = [_benign_event(c, _fresh.weighted(c.rng, _BENIGN_OPS)) for _ in range(count)]
    for event, when in zip(out, _fresh.jittered_times(c.rng, end, count, spread_seconds)):
        _stamp(c, event, when)
    return out


def build_events(
    scenario: str, count: int, *, view: OrganizationView, now: datetime,
    spread_seconds: int = 120, start_offset_minutes: int = 0,
    target_user: str | None = None, source_ip: str | None = None, seed: int | None = None,
) -> list[dict[str, Any]]:
    """Build `count` directoryAudit objects for `scenario`, oldest first.

    The window ends `start_offset_minutes` before `now` and is `spread_seconds` wide; nothing is dated after `now`.
    `target_user` names the admin who acts: one of the organization's people (`view`; `.adm@<email domain>` is appended to
    the email's local part); `source_ip` is the admin's address. `benign_activity` ignores both: its actors and addresses
    are the stable pool's.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; choose one of {', '.join(SCENARIOS)}")
    if count < 1:
        raise ValueError("count must be at least 1")
    end = now - timedelta(minutes=max(start_offset_minutes, 0))
    c = _Ctx(view, seed)
    if scenario == "benign_activity":
        return _benign_activity(c, count, end, spread_seconds)
    who = c.admin(_org.resolve(view, target_user) if _fresh.bare_name(target_user) else None)
    if source_ip:
        who.ip = source_ip
    recipe, _ = _TABLE[scenario]
    return _fresh.run_recipe(lambda k: recipe(c, who, k, source_ip), count, _times(end, count, spread_seconds),
                             lambda event, when: _stamp(c, event, when))


def sample_event(*, view: OrganizationView, now: datetime) -> dict[str, Any]:
    """One benign audit event (a fresh admin adds a user), for proving the Cribl path."""
    c = _Ctx(view, None)
    who = c.admin(None)
    user = f"{_fresh.handle(c.rng)}@{c.domain}"
    event = c.audit(who, "Add user", "UserManagement", "Core Directory", "Add", [
        {**c.target("User", user.split("@")[0], [("UserPrincipalName", None, user)]), "userPrincipalName": user}])
    _stamp(c, event, now)
    return event
