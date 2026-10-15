"""What the profiles read from the organization (see `runtime/organization_view.py`): who may log on, where they live on the
internet, which cloud accounts the organization owns.

Nothing here is a roster. The people, their emails, Okta ids and home addresses, the AWS account, GCP project and regions, the
partner domain and the public egress addresses all come from the `OrganizationView` a caller passes in, and every function
reads it at CALL time. An organization that lacks something a scenario needs is a broken install: the function raises
`OrganizationUnavailable` with a message that says what to add, and `connector.py` returns it as `{ok: false, error}`.

Fresh identities are NOT organization data. The attack recipes mint actors the organization has never seen (a new IAM user,
`fastpass.phishing.<id>`, a new-hire account, an external sender) because the detectors they replay profile "first time seen".
Those stay in the profiles; only their email domain is the organization's.
"""
from __future__ import annotations

from typing import Any, Iterable

from runtime.organization_reader import OrganizationUnavailable
from runtime.organization_view import OrganizationView

from . import ippools

CLOUD_PROVIDERS = ("aws", "azure", "gcp")
_SHOWN_CHOICES = 60


class UnknownUser(ValueError):
    """`target_user` names nobody in the organization. The message lists the valid choices."""


# -- who may log on ----------------------------------------------------------------------------------------------------------

def is_leaver(person: dict[str, Any]) -> bool:
    return "leaver" in person.get("flags", [])


def logon_people(view: OrganizationView) -> list[dict[str, Any]]:
    """Everyone who may log on, in organization order: the people minus the leavers. Contractors and outliers are included
    (they sign in like anybody else; what they do is the baseline's business)."""
    pool = [p for p in view.people if not is_leaver(p)]
    if not pool:
        raise OrganizationUnavailable(
            f"organization {view.id!r} has nobody who may log on (every person is a leaver): add people so the profiles "
            "have identities to use")
    return pool


def cloud_people(view: OrganizationView, provider: str) -> list[dict[str, Any]]:
    """The people who may log on and whose `cloud_access` contains `provider` ("aws" | "azure" | "gcp")."""
    pool = [p for p in logon_people(view) if provider in p.get("cloud_access", [])]
    if not pool:
        raise OrganizationUnavailable(
            f"organization {view.id!r} has nobody with {provider!r} in cloud_access: grant it to the people who use "
            f"{provider} so the benign baseline has identities")
    return pool


def administrators(pool: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The IT staff of `pool`, in organization order: the people who administer the directory."""
    return [p for p in pool if p.get("department") == "IT"]


# -- how a person is named ---------------------------------------------------------------------------------------------------

def email(person: dict[str, Any]) -> str:
    return person["email"]


def local_part(person: dict[str, Any]) -> str:
    """The part of the email before the @ (`first.last`): the name cloud identities and mail logins carry."""
    return person["email"].split("@", 1)[0]


def display(person: dict[str, Any]) -> str:
    return person.get("display_name") or f"{person['given_name']} {person['family_name']}"


def home(person: dict[str, Any]) -> tuple[str, ippools.Range | None]:
    """The person's home address and its pool range (see `ippools.home_of`)."""
    return ippools.home_of(person)


def manager_of(view: OrganizationView, person: dict[str, Any]) -> dict[str, Any]:
    """The person's manager; the first vip (else the first person) when the manager is unknown."""
    manager = view.person(person.get("manager") or "")
    if manager is not None:
        return manager
    vips = view.people_with_flag("vip")
    return (vips or view.people)[0]


# -- target_user -------------------------------------------------------------------------------------------------------------

def resolve(view: OrganizationView, value: str) -> dict[str, Any]:
    """The person a `target_user` names: a login (`jdoe`), an admin login (`adm.jdoe`), an email or the part of
    it before the @ (`first.last`), in any case, with or without a `DOMAIN\\` prefix. Leavers resolve (an attack on a
    disabled account is a legitimate scenario) though they are in no pool. Anything else raises `UnknownUser` listing the
    valid emails."""
    key = value.strip().rsplit("\\", 1)[-1].lower()
    for pick in (
        lambda p: p["login"], lambda p: p["email"], lambda p: p["email"].split("@", 1)[0],
        lambda p: (p.get("admin_account") or {}).get("login"),
    ):
        for person in view.people:
            if (pick(person) or "").lower() == key:
                return person
    emails = sorted(p["email"] for p in view.people)
    shown = ", ".join(emails[:_SHOWN_CHOICES]) + (f" and {len(emails) - _SHOWN_CHOICES} more" if len(emails) > _SHOWN_CHOICES else "")
    raise UnknownUser(
        f"target_user {value!r} is nobody in the organization {view.name!r}. Name one of its people by login, email or the "
        f"part of the email before the @. The valid emails are: {shown}")


# -- organization-wide facts -------------------------------------------------------------------------------------------------

def partner_domain(view: OrganizationView) -> str:
    """The domain of the outside party in external shares and mail. It is the organization's `domain.partner_domain`."""
    if not view.partner_domain:
        raise OrganizationUnavailable(
            f"organization {view.id!r} declares no domain.partner_domain, which scenarios that share with an outside "
            "party need: add one (a reserved name such as partner.example)")
    return view.partner_domain


def cloud(view: OrganizationView, provider: str, *keys: str) -> dict[str, str]:
    """The `cloud.<provider>` section of the organization, checked to carry `keys`."""
    section = (view.doc.get("cloud") or {}).get(provider) or {}
    missing = [k for k in keys if not section.get(k)]
    if missing:
        raise OrganizationUnavailable(
            f"organization {view.id!r} has no cloud.{provider}.{'/'.join(missing)}: add it so {provider} events carry the "
            "organization's own account")
    return section


def egress(view: OrganizationView) -> list[str]:
    """The organization's public egress addresses, in a fixed order: the office NATs, the other NATs, the DMZ servers."""
    section = view.doc.get("egress") or {}
    out = [section[k] for k in ("ruh_nat", "jed_nat") if section.get(k)]
    out += list((section.get("nat") or {}).values()) + list((section.get("dmz_public") or {}).values())
    if not out:
        raise OrganizationUnavailable(
            f"organization {view.id!r} has no egress addresses: add egress.ruh_nat (or nat / dmz_public) so service "
            "accounts have an address to call from")
    return out


def bucket_prefix(view: OrganizationView) -> str:
    """The naming prefix of the organization's storage buckets: its id (`phantom-lab`)."""
    return view.id
