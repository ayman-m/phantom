"""The directory cie-sender provisions: the active organization's people, accounts and groups.

The Cloud Identity Engine is worth having in Cortex because it joins directory context (department, title, manager, group
membership) to the users that appear in logs. So this directory is NOT a roster of its own: it is the active organization
(`runtime.organization_view`), the same people the Okta, Windows, firewall and cloud logs are generated for. Switching the
organization and provisioning again creates the new people; nothing is removed until `phantom_remove_provisioned`.

What becomes a SCIM user:
  * every person's normal account, and the separate `adm.` account of every administrator (the tiered-admin model Identity
    Analytics reads), each with its own employee number, department, title and manager;
  * the organization's service accounts and the break-glass account (department IT);
  * a leaver's account is provisioned `active: false`, the persona for "logon by a disabled account".
Groups are the organization's groups, with the members its people and accounts list.

Every object carries an `externalId` starting `phantom:`, which is how the connector recognises what it created and the
only thing remove_provisioned deletes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from runtime.organization_view import OrganizationView

from . import scim

EXTERNAL_PREFIX = "phantom:"
USER_NAME_STYLES = ("sam", "dotted")
CITY, COUNTRY = "Riyadh", "SA"


@dataclass
class Person:
    login: str                       # sAMAccountName-style login, the name the Windows events carry
    given: str
    family: str
    display: str
    title: str
    department: str
    employee_number: str
    role: str                        # staff | admin | service
    manager: str | None = None       # login of the manager
    groups: list[str] = field(default_factory=list)
    email_local: str = ""
    active: bool = True


@dataclass
class Directory:
    domain: str
    company: str
    style: str
    people: list[Person]
    groups: dict[str, list[str]]     # group name -> member logins, in creation order
    privileged: frozenset[str] = frozenset()

    def user_name(self, person: Person) -> str:
        local = person.login if self.style == "sam" or person.role == "service" else person.email_local
        return f"{local}@{self.domain}"

    def email(self, person: Person) -> str:
        return f"{person.email_local}@{self.domain}"

    def by_login(self) -> dict[str, Person]:
        return {p.login: p for p in self.people}


def _managers_first(people: list[Person]) -> list[Person]:
    """The same people, stably reordered so every manager comes before the people who report to them: provisioning sets a
    user's manager when it creates them, which needs the manager's SCIM id."""
    logins = {p.login for p in people}
    placed: set[str] = set()
    ordered: list[Person] = []
    pending = list(people)
    while pending:
        later = []
        for p in pending:
            if p.manager is None or p.manager not in logins or p.manager in placed:
                ordered.append(p)
                placed.add(p.login)
            else:
                later.append(p)
        if len(later) == len(pending):  # a loop (organizations are validated against this): keep the rest in order
            ordered.extend(later)
            break
        pending = later
    return ordered


def build(view: OrganizationView, style: str = "sam", include_service_accounts: bool = True) -> Directory:
    """The directory of `view`: one SCIM user per account, one group per organization group."""
    if style not in USER_NAME_STYLES:
        raise ValueError(f"user_name_style must be one of {', '.join(USER_NAME_STYLES)}, not {style!r}")
    people: list[Person] = []
    for a in view.accounts:
        owner = view.person(a.person) if a.person else None
        if a.kind in ("service", "break_glass"):
            if not include_service_accounts:
                continue
            raw = next(s for s in view.doc.get("service_accounts", []) if s["login"] == a.login)
            given, _, family = a.display.partition(" ")
            people.append(Person(a.login, given, family or "Account", a.display,
                                 "Service Account" if a.kind == "service" else "Emergency Administrator", "IT",
                                 a.employee_number or "", "service" if a.kind == "service" else "admin",
                                 manager=raw.get("manager"), groups=list(a.groups), email_local=a.login))
            continue
        assert owner is not None
        local = owner["email"].split("@")[0]
        people.append(Person(a.login, owner["given_name"], owner["family_name"], a.display, owner["title"],
                             owner["department"], a.employee_number or "", a.role, manager=owner.get("manager"),
                             groups=list(a.groups), email_local=local if a.kind == "user" else f"adm.{local}",
                             active=a.active))
    people = _managers_first(people)
    groups: dict[str, list[str]] = {g["name"]: [] for g in view.doc.get("groups", [])}
    for person in people:
        for name in person.groups:
            groups.setdefault(name, []).append(person.login)
    if not include_service_accounts:
        groups = {n: m for n, m in groups.items() if m or n not in {g for a in view.accounts if a.kind in ("service", "break_glass") for g in a.groups}}
    privileged = frozenset(g["name"] for g in view.doc.get("groups", []) if g.get("privileged"))
    return Directory(view.dns, view.name, style, people, groups, privileged)


# -- SCIM resource bodies ---------------------------------------------------------------------------------------------

def external_id(person: Person) -> str:
    return f"{EXTERNAL_PREFIX}{person.login}"


def group_external_id(name: str) -> str:
    return f"{EXTERNAL_PREFIX}group:{name}"


def is_phantom(resource: dict[str, Any]) -> bool:
    return str(resource.get("externalId") or "").startswith(EXTERNAL_PREFIX)


def owned(resource: dict[str, Any], d: Directory) -> bool:
    """Whether Phantom made this user or group: the one ownership test every tool uses.

    A `phantom:` externalId decides it. CIE's documented SCIM attributes do not include externalId, so a server may not
    store it; then an object with NO externalId counts as Phantom's only when its userName (users) or displayName
    (groups) is one this directory provisions. Any other externalId means someone else made it."""
    ext = resource.get("externalId")
    if ext:
        return str(ext).startswith(EXTERNAL_PREFIX)
    if "userName" in resource:
        return str(resource.get("userName") or "").lower() in {d.user_name(p).lower() for p in d.people}
    return str(resource.get("displayName") or "") in d.groups


def user_body(d: Directory, person: Person, manager_id: str | None) -> dict[str, Any]:
    enterprise: dict[str, Any] = {"employeeNumber": person.employee_number, "department": person.department,
                                  "organization": d.company}
    if manager_id:
        enterprise["manager"] = {"value": manager_id}
    return {
        "schemas": [scim.USER_SCHEMA, scim.ENTERPRISE_SCHEMA],
        "externalId": external_id(person),
        "userName": d.user_name(person),
        "name": {"givenName": person.given, "familyName": person.family, "formatted": person.display},
        "displayName": person.display,
        "nickName": person.given,
        "title": person.title,
        "preferredLanguage": "en-US",
        "active": person.active,
        "emails": [{"value": d.email(person), "type": "work", "primary": True}],
        "addresses": [{"type": "work", "locality": CITY, "country": COUNTRY,
                       "formatted": f"{d.company}, {CITY}, {COUNTRY}", "primary": True}],
        scim.ENTERPRISE_SCHEMA: enterprise,
    }


def group_body(name: str) -> dict[str, Any]:
    return {"schemas": [scim.GROUP_SCHEMA], "externalId": group_external_id(name), "displayName": name, "members": []}


def _work_email(resource: dict[str, Any]) -> str | None:
    for item in resource.get("emails") or []:
        if isinstance(item, dict) and (item.get("type") == "work" or item.get("primary")):
            return item.get("value")
    return None


def user_patch_ops(current: dict[str, Any], wanted: dict[str, Any]) -> list[dict[str, Any]]:
    """Path-based `replace` operations (the form Entra ID sends) for every attribute that differs."""
    ops: list[dict[str, Any]] = []

    def replace(path: str, have: Any, want: Any) -> None:
        if want is not None and have != want:
            ops.append({"op": "replace", "path": path, "value": want})

    # externalId is set on create only: a server that does not keep it would otherwise be patched on every run.
    for key in ("displayName", "nickName", "title", "preferredLanguage", "active"):
        replace(key, current.get(key), wanted.get(key))
    have_name, want_name = current.get("name") or {}, wanted.get("name") or {}
    for key in ("givenName", "familyName", "formatted"):
        replace(f"name.{key}", have_name.get(key), want_name.get(key))
    replace('emails[type eq "work"].value', _work_email(current), _work_email(wanted))
    have_ent = current.get(scim.ENTERPRISE_SCHEMA) or {}
    want_ent = wanted.get(scim.ENTERPRISE_SCHEMA) or {}
    for key in ("employeeNumber", "department", "organization"):
        replace(f"{scim.ENTERPRISE_SCHEMA}:{key}", have_ent.get(key), want_ent.get(key))
    want_manager = (want_ent.get("manager") or {}).get("value")
    have_manager = have_ent.get("manager")
    have_manager = have_manager.get("value") if isinstance(have_manager, dict) else have_manager
    if want_manager and have_manager != want_manager:
        ops.append({"op": "replace", "path": f"{scim.ENTERPRISE_SCHEMA}:manager", "value": {"value": want_manager}})
    return ops


def summary(d: Directory) -> dict[str, Any]:
    """What provision_directory would create, without any network call."""
    return {
        "domain": d.domain,
        "user_name_style": d.style,
        "users": [{"user_name": d.user_name(p), "display_name": p.display, "email": d.email(p), "role": p.role,
                   "department": p.department, "title": p.title, "manager": p.manager, "groups": p.groups,
                   "active": p.active}
                  for p in d.people],
        "groups": [{"name": name, "members": len(members), "privileged": name in d.privileged}
                   for name, members in d.groups.items()],
    }
