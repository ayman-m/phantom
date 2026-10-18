"""cie-sender connector: provisions a synthetic directory into a Cloud Identity Engine SCIM directory.

The Cloud Identity Engine (CIE) feeds Cortex XSIAM its directory context (the `pan_dss_raw` dataset), and Cortex requires a
paired CIE before its Identity Analytics detectors are active. CIE accepts directories over SCIM 2.0: the operator adds a
SCIM directory (client type Others) in the CIE app, which gives a Base URL and a bearer token. This connector is the SCIM
client: it creates, updates and removes users and groups there, the way an identity provider's provisioning service does.

Tools (the runtime strips the `phantom_` prefix, so the agent sees `cie-sender/<tool>`):

  phantom_test_connection        prove the Base URL and token work (one filtered GET /Users)
  phantom_provision_directory    create or update the synthetic phantom.lab directory: users, managers, groups, members
  phantom_list_directory         one page of the users or groups the SCIM directory holds
  phantom_update_user            change one user's title, department, display name, manager or active flag
  phantom_set_group_membership   add a user to a group or remove them from it
  phantom_remove_provisioned     delete every user and group this connector created (DESTRUCTIVE, needs confirm=true)

The token lives in the instance's `scimToken` secret slot and is read at call time; no tool accepts or returns it, so the
agent never handles a credential. Only objects Phantom made are ever changed or deleted (directory.owned: a `phantom:`
externalId, or no externalId and a name the provisioned directory uses).
"""
from __future__ import annotations

import functools
import logging
from typing import Any
from urllib.parse import urlparse

from runtime.organization_reader import OrganizationUnavailable
from runtime.organization_view import OrganizationView, get_view

from . import directory, scim

logger = logging.getLogger(__name__)

NEXT_STEP = ("In the Cloud Identity Engine app, open Directory Sync > Directories and run Actions > Full Sync on this SCIM "
             "directory (setup is not complete until a full sync succeeds), then check `dataset = pan_dss_raw` in XSIAM. "
             "The CIE instance must also be selected in XSIAM under Settings > Configuration > Integrations > Cloud "
             "Identity Engine.")


def _settings() -> dict[str, Any]:
    """The instance config and secret. Split out so tests can stub it."""
    from config.config import get_config

    cfg = get_config()

    def get(name: str, default: Any = None) -> Any:
        return getattr(cfg, name, default)

    verify = get("verifyTls", True)
    if isinstance(verify, str):
        verify = verify.strip().lower() not in ("false", "0", "no", "off")
    return {
        "base_url": (get("scimBaseUrl", "") or "").strip(),
        "token": (get("scimToken", "") or "").strip(),
        "organization": (get("organization", "") or "").strip(),
        "style": (get("userNameStyle", "sam") or "sam").strip().lower(),
        "verify_tls": bool(verify),
        "timeout": float(get("timeoutSeconds", 20) or 20),
    }


def _transport() -> Any:
    """The httpx transport to use (None = the network). Tests replace it with a MockTransport."""
    return None


def _err(message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, **extra}


def _problem(settings: dict[str, Any]) -> str | None:
    url = settings["base_url"]
    if not url:
        return "scimBaseUrl is not set: copy the Base URL the Cloud Identity Engine shows for the SCIM directory"
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return "scimBaseUrl must be an https:// URL"
    if not settings["token"]:
        return "the scimToken secret is empty: generate a static bearer token for the SCIM directory in the CIE app"
    return None


def _client(settings: dict[str, Any]) -> scim.ScimClient:
    return scim.ScimClient(settings["base_url"], settings["token"], verify_tls=settings["verify_tls"],
                           timeout=settings["timeout"], transport=_transport())


def _view(settings: dict[str, Any]) -> OrganizationView:
    """The organization this instance provisions: the pinned one, else the active one. Read on every call."""
    return get_view(settings["organization"] or None)


def _directory(settings: dict[str, Any]) -> directory.Directory:
    """The directory of the instance's organization and style: what the ownership test compares names against."""
    return directory.build(_view(settings), settings["style"])


def _guarded(fn):
    """Turn an unreadable organization into the {ok: false, error} every tool answers with."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except OrganizationUnavailable as exc:
            return _err(f"the organization cannot be read: {exc}")
    return wrapper


def _host(settings: dict[str, Any]) -> str:
    return urlparse(settings["base_url"]).netloc


def _scim_error(exc: scim.ScimError, **extra: Any) -> dict[str, Any]:
    hint = None
    if exc.status == 401:
        hint = "the token was refused: generate a new bearer token in the CIE app and save it in the instance"
    elif exc.status == 403:
        hint = "the token is valid but not allowed to do this; check the SCIM directory in the CIE app"
    elif exc.status == 400:
        hint = "the SCIM server rejected the request; its detail names what it did not accept"
    elif exc.status == 404:
        hint = "the path was not found: check that scimBaseUrl is the Base URL exactly as the CIE app shows it"
    elif exc.status == 0:
        hint = "no response: check the URL, DNS and outbound HTTPS from the Phantom host"
    out = _err(str(exc), http_status=exc.status, **extra)
    if hint:
        out["hint"] = hint
    return out


def _user_summary(resource: dict[str, Any], d: directory.Directory) -> dict[str, Any]:
    ent = resource.get(scim.ENTERPRISE_SCHEMA) or {}
    manager = ent.get("manager")
    return {"id": resource.get("id"), "user_name": resource.get("userName"), "display_name": resource.get("displayName"),
            "title": resource.get("title"), "department": ent.get("department"),
            "manager_id": manager.get("value") if isinstance(manager, dict) else manager,
            "active": resource.get("active"), "phantom": directory.owned(resource, d)}


def _group_summary(resource: dict[str, Any], d: directory.Directory) -> dict[str, Any]:
    members = resource.get("members")
    return {"id": resource.get("id"), "name": resource.get("displayName"),
            "members": len(members) if isinstance(members, list) else None, "phantom": directory.owned(resource, d)}


# -- tools --------------------------------------------------------------------------------------------------------------

@_guarded
def phantom_test_connection() -> dict[str, Any]:
    """Check that the instance's SCIM Base URL and bearer token work, with one filtered GET /Users.

    Use it first after creating or changing the instance. It changes nothing.

    Returns:
      {ok, host, http_status, users_total, phantom_user_found} or {ok: false, error, http_status, hint}
    """
    settings = _settings()
    problem = _problem(settings)
    if problem:
        return _err(problem)
    try:
        d = _directory(settings)
    except ValueError as exc:
        return _err(str(exc))
    user_name = d.user_name(d.people[0])
    try:
        with _client(settings) as client:
            page = client.list("Users", filter=f"userName eq {scim.quote_filter_value(user_name)}", count=1)
            total = client.list("Users", count=1)["total"]
    except scim.ScimError as exc:
        return _scim_error(exc, host=_host(settings))
    return {"ok": True, "host": _host(settings), "http_status": 200, "users_total": total,
            "phantom_user_found": bool(page["resources"])}


@_guarded
def phantom_provision_directory(dry_run: bool = False, user_name_style: str | None = None,
                                include_service_accounts: bool = True) -> dict[str, Any]:
    """Create or update the active organization's directory in the Cloud Identity Engine SCIM directory.

    The directory is the organization every other Phantom tool generates logs for: its people and their separate admin
    accounts, the service and break-glass accounts, departments, titles, managers and groups (a leaver is provisioned
    disabled), so Cortex can join directory context to the users in the logs. To add or change people, edit the
    organization (the Organization page, or organization_update), then run this again. Switching the organization and
    provisioning creates the new people; nothing already provisioned is removed (use remove_provisioned for that). Safe to run again: users are matched by userName and groups by displayName, missing
    ones are created, Phantom-made ones are updated to match, members are added, and anything the connector did not
    create (no `phantom:` externalId) is left alone and reported as skipped. After the first run the operator must run
    Full Sync on the directory in the CIE app.

    Args:
      dry_run: Return the directory that would be provisioned without calling the SCIM server. Use it to show the
        operator what will be created.
      user_name_style: "sam" (default; userName `nalharbi@<domain>`, the login the Windows events carry) or "dotted"
        (`noura.alharbi@<domain>`, the form the Okta and cloud profiles use). Default: the instance's userNameStyle.
        Changing it later creates a second set of users; do not switch styles on a provisioned directory.
      include_service_accounts: Also provision the organization's service accounts and the break-glass account (default
        true).

    Returns:
      {ok, dry_run, host, domain, users: {created, updated, unchanged, skipped, failed}, groups: {created, existing,
      skipped, failed}, members_added, errors (first 20), calls, next_step} or, with dry_run, {ok, dry_run, directory}
    """
    settings = _settings()
    style = (user_name_style or settings["style"]).strip().lower()
    try:
        d = directory.build(_view(settings), style, include_service_accounts)
    except ValueError as exc:
        return _err(str(exc))
    if dry_run:
        return {"ok": True, "dry_run": True, "directory": directory.summary(d)}
    problem = _problem(settings)
    if problem:
        return _err(problem)

    users = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "failed": 0}
    groups = {"created": 0, "existing": 0, "skipped": 0, "failed": 0}
    errors: list[dict[str, Any]] = []
    ids: dict[str, str] = {}
    managed: set[str] = set()
    members_added = 0

    def fail(kind: str, name: str, exc: scim.ScimError) -> None:
        errors.append({"object": f"{kind}:{name}", "http_status": exc.status, "detail": exc.detail})

    try:
        with _client(settings) as client:
            people = d.people
            pending_manager: list[directory.Person] = []
            for person in people:
                user_name = d.user_name(person)
                manager_id = ids.get(person.manager) if person.manager else None
                if person.manager and not manager_id:
                    pending_manager.append(person)
                wanted = directory.user_body(d, person, manager_id)
                try:
                    current = client.find_user(user_name)
                    if current is None:
                        created = client.create("Users", wanted)
                        ids[person.login] = created["id"]
                        managed.add(person.login)
                        users["created"] += 1
                    elif not directory.owned(current, d):
                        ids[person.login] = current["id"]
                        users["skipped"] += 1
                    else:
                        ids[person.login] = current["id"]
                        managed.add(person.login)
                        ops = directory.user_patch_ops(current, wanted)
                        if ops:
                            client.patch("Users", current["id"], ops)
                            users["updated"] += 1
                        else:
                            users["unchanged"] += 1
                except scim.ScimError as exc:
                    # Nothing has succeeded yet: the same error would repeat for every user (a refused token, a wrong
                    # URL, an attribute this server rejects), and the groups would be created empty. Stop and say why.
                    if not any(users[k] for k in ("created", "updated", "unchanged", "skipped")):
                        return _scim_error(exc, host=_host(settings), object=f"user:{user_name}")
                    users["failed"] += 1
                    fail("user", user_name, exc)
            for person in pending_manager:
                if person.login in managed and ids.get(person.manager or ""):
                    try:
                        client.patch("Users", ids[person.login], [{
                            "op": "replace", "path": f"{scim.ENTERPRISE_SCHEMA}:manager",
                            "value": {"value": ids[person.manager]}}])
                    except scim.ScimError as exc:
                        fail("manager", person.login, exc)

            for name, logins in d.groups.items():
                try:
                    current = client.find_group(name)
                    if current is None:
                        current = client.create("Groups", directory.group_body(name))
                        groups["created"] += 1
                    elif not directory.owned(current, d):
                        groups["skipped"] += 1
                        continue
                    else:
                        groups["existing"] += 1
                    have = {m.get("value") for m in current.get("members") or [] if isinstance(m, dict)}
                    missing = [ids[login] for login in logins if login in managed and ids[login] not in have]
                    for start in range(0, len(missing), 50):
                        client.add_members(current["id"], missing[start:start + 50])
                    members_added += len(missing)
                except scim.ScimError as exc:
                    groups["failed"] += 1
                    fail("group", name, exc)
            calls = client.calls
    except scim.ScimError as exc:
        return _scim_error(exc, host=_host(settings))

    return {"ok": users["failed"] == 0 and groups["failed"] == 0, "dry_run": False, "host": _host(settings),
            "domain": d.domain, "user_name_style": d.style, "users": users, "groups": groups,
            "members_added": members_added, "errors": errors[:20], "calls": calls, "next_step": NEXT_STEP}


@_guarded
def phantom_list_directory(resource: str = "Users", filter: str | None = None, count: int = 50,
                           start_index: int = 1) -> dict[str, Any]:
    """List one page of the users or groups in the SCIM directory (parsed summaries, not raw SCIM objects).

    Args:
      resource: "Users" (default) or "Groups".
      filter: Optional SCIM filter, e.g. 'userName eq "nalharbi@phantom.lab"' or 'displayName eq "Domain Admins"'.
      count: Page size, 1-200 (default 50).
      start_index: 1-based index of the first result (default 1).

    Returns:
      {ok, resource, total, start_index, items: [{id, user_name|name, ..., phantom}]}
    """
    kind = (resource or "Users").strip().capitalize()
    if kind not in ("Users", "Groups"):
        return _err("resource must be Users or Groups")
    settings = _settings()
    problem = _problem(settings)
    if problem:
        return _err(problem)
    try:
        with _client(settings) as client:
            page = client.list(kind, filter=filter, start_index=start_index, count=max(1, min(int(count), 200)))
    except scim.ScimError as exc:
        return _scim_error(exc, host=_host(settings))
    summarize = _user_summary if kind == "Users" else _group_summary
    d = _directory(settings)
    return {"ok": True, "resource": kind, "total": page["total"], "start_index": page["start_index"],
            "items": [summarize(r, d) for r in page["resources"]]}


def _resolve_user(client: scim.ScimClient, settings: dict[str, Any], user: str) -> dict[str, Any] | None:
    user = user.strip()
    user_name = user if "@" in user else f"{user}@{_view(settings).dns}"
    return client.find_user(user_name)


@_guarded
def phantom_update_user(user_name: str, title: str | None = None, department: str | None = None,
                        display_name: str | None = None, manager: str | None = None,
                        active: bool | None = None) -> dict[str, Any]:
    """Change one Phantom-provisioned user, to simulate a directory change (a promotion, a move, a disabled account).

    Only users this connector created can be changed.

    Args:
      user_name: The userName (`nalharbi@phantom.lab`) or the login alone (`nalharbi`).
      title: New job title.
      department: New department.
      display_name: New display name.
      manager: userName or login of the new manager.
      active: false disables the account (the SCIM equivalent of disabling it in the directory); true enables it.

    Returns:
      {ok, user_name, id, changed: [paths]} or {ok: false, error}
    """
    settings = _settings()
    problem = _problem(settings)
    if problem:
        return _err(problem)
    try:
        with _client(settings) as client:
            current = _resolve_user(client, settings, user_name)
            if current is None:
                return _err(f"no user {user_name!r} in the SCIM directory")
            if not directory.owned(current, _directory(settings)):
                return _err(f"{current.get('userName')} was not created by Phantom; it is left alone")
            ops: list[dict[str, Any]] = []
            if title is not None:
                ops.append({"op": "replace", "path": "title", "value": title})
            if display_name is not None:
                ops.append({"op": "replace", "path": "displayName", "value": display_name})
            if department is not None:
                ops.append({"op": "replace", "path": f"{scim.ENTERPRISE_SCHEMA}:department", "value": department})
            if active is not None:
                ops.append({"op": "replace", "path": "active", "value": bool(active)})
            if manager is not None:
                boss = _resolve_user(client, settings, manager)
                if boss is None:
                    return _err(f"no manager {manager!r} in the SCIM directory")
                ops.append({"op": "replace", "path": f"{scim.ENTERPRISE_SCHEMA}:manager", "value": {"value": boss["id"]}})
            if not ops:
                return _err("nothing to change: pass at least one of title, department, display_name, manager, active")
            client.patch("Users", current["id"], ops)
    except scim.ScimError as exc:
        return _scim_error(exc, host=_host(settings))
    return {"ok": True, "user_name": current.get("userName"), "id": current["id"], "changed": [o["path"] for o in ops]}


@_guarded
def phantom_set_group_membership(group: str, user_name: str, action: str = "add",
                                 create_group: bool = False) -> dict[str, Any]:
    """Add a user to a group or remove them from it, e.g. to simulate a user added to a privileged group.

    Args:
      group: The group's displayName, e.g. "Domain Admins" or "SG-Finance".
      user_name: The member's userName or login.
      action: "add" (default) or "remove".
      create_group: Create the group (as a Phantom group) when it does not exist. Default false.

    Returns:
      {ok, group, group_id, user_name, action, changed} or {ok: false, error}
    """
    action = (action or "add").strip().lower()
    if action not in ("add", "remove"):
        return _err("action must be add or remove")
    settings = _settings()
    problem = _problem(settings)
    if problem:
        return _err(problem)
    try:
        with _client(settings) as client:
            member = _resolve_user(client, settings, user_name)
            if member is None:
                return _err(f"no user {user_name!r} in the SCIM directory")
            target = client.find_group(group)
            if target is None:
                if not (create_group and action == "add"):
                    return _err(f"no group {group!r} in the SCIM directory (pass create_group=true to create it)")
                target = client.create("Groups", directory.group_body(group))
            elif not directory.owned(target, _directory(settings)):
                return _err(f"group {group!r} was not created by Phantom; it is left alone")
            have = {m.get("value") for m in target.get("members") or [] if isinstance(m, dict)}
            changed = (member["id"] not in have) if action == "add" else (member["id"] in have or not have)
            if action == "add" and changed:
                client.add_members(target["id"], [member["id"]])
            elif action == "remove":
                client.remove_member(target["id"], member["id"])
    except scim.ScimError as exc:
        return _scim_error(exc, host=_host(settings))
    return {"ok": True, "group": target.get("displayName", group), "group_id": target["id"],
            "user_name": member.get("userName"), "action": action, "changed": changed}


@_guarded
def phantom_remove_provisioned(confirm: bool = False) -> dict[str, Any]:
    """DESTRUCTIVE: delete every user and group this connector created from the SCIM directory.

    Only objects Phantom made are deleted: an externalId starting `phantom:`, or, when the server keeps no externalId,
    a userName or group name the provisioned directory uses. Everything else is left alone. The CIE then
    removes them from its directory, and Cortex stops seeing them after its next sync. Without confirm=true it only
    counts what it would delete. Set confirm=true only when the operator has explicitly asked to remove the provisioned
    directory.

    Args:
      confirm: Must be true to delete anything (default false: report the counts only).

    Returns:
      {ok, confirmed, users, groups, deleted_users, deleted_groups, errors}
    """
    settings = _settings()
    problem = _problem(settings)
    if problem:
        return _err(problem)
    errors: list[dict[str, Any]] = []
    deleted_users = deleted_groups = 0
    try:
        with _client(settings) as client:
            d = _directory(settings)
            phantom_groups = [g for g in client.list_all("Groups") if directory.owned(g, d)]
            phantom_users = [u for u in client.list_all("Users") if directory.owned(u, d)]
            if confirm:
                for kind, items in (("Groups", phantom_groups), ("Users", phantom_users)):
                    for item in items:
                        try:
                            client.delete(kind, item["id"])
                            if kind == "Users":
                                deleted_users += 1
                            else:
                                deleted_groups += 1
                        except scim.ScimError as exc:
                            errors.append({"object": f"{kind}:{item.get('userName') or item.get('displayName')}",
                                           "http_status": exc.status, "detail": exc.detail})
    except scim.ScimError as exc:
        return _scim_error(exc, host=_host(settings))
    return {"ok": not errors, "confirmed": bool(confirm), "users": len(phantom_users), "groups": len(phantom_groups),
            "deleted_users": deleted_users, "deleted_groups": deleted_groups, "errors": errors[:20]}


__all__ = [
    "phantom_test_connection",
    "phantom_provision_directory",
    "phantom_list_directory",
    "phantom_update_user",
    "phantom_set_group_membership",
    "phantom_remove_provisioned",
]
