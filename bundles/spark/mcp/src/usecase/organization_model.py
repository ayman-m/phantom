"""The organization document: validation, read views and structured edits.

An organization is the one fictitious company Phantom generates telemetry for: its people and their accounts, hosts,
networks, sites, groups and cloud accounts. This module is pure (no I/O beyond reading the bundled JSON Schema), so the
store, the REST routes, the agent tools and the tests share one definition of "valid" and one set of views.

Validation is two layers:
  1. the JSON Schema (`bundles/spark/organization/organization.schema.json`): shape, types, enums, patterns;
  2. the consistency checks in `_semantic_errors`: the references and uniqueness JSON Schema cannot express.

The checks that matter for stitching are the semantic ones: every host address sits inside the network it names, every
person's workstation exists and belongs to them, the manager chain has no cycle, and no login, host name, address or RID
is used twice. An organization that passes cannot make a generator emit a user on a host that is not there.

`apply_changes` is how the agent (and the UI's quick edits) change an organization: id-keyed `upsert` and `remove` per
collection plus a deep-merge `set` for the scalar sections, with the boring parts of adding a person (workstation, RID,
Okta id, groups) filled in so an edit stays one small call.
"""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import itertools
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import jsonschema
import yaml

SCHEMA_VERSION = 1
SCHEMA_FILE = "organization.schema.json"

# Collections that hold a list of objects, and the field that identifies one of them.
COLLECTION_KEYS: dict[str, str] = {
    "people": "login",
    "service_accounts": "login",
    "hosts": "name",
    "networks": "id",
    "sites": "id",
    "groups": "name",
}
# Top-level sections `apply_changes(set=...)` may deep-merge (collections change through upsert/remove instead).
SETTABLE_SECTIONS = ("name", "description", "domain", "locale", "cortex", "egress", "cloud")
SECTIONS = ("overview", "people", "accounts", "hosts", "networks", "sites", "groups", "personas", "cloud", "egress",
            "cortex")


class OrganizationError(ValueError):
    """The document is unreadable, invalid, or a requested change cannot be applied. `errors` lists every problem."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


# ── schema ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def bundle_dir() -> Path:
    """`<bundle root>/organization`: the schema and the bundled organizations ship there."""
    return Path(os.getenv("BUNDLE_ROOT", "/app/bundle")).resolve() / "organization"


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    path = bundle_dir() / SCHEMA_FILE
    return json.loads(path.read_text(encoding="utf-8"))


def parse_document(text: str, fmt: str | None = None) -> dict[str, Any]:
    """Parse YAML or JSON text into a document. `fmt` is "yaml", "json" or None (JSON first, then YAML)."""
    if not isinstance(text, str) or not text.strip():
        raise OrganizationError("the organization text is empty")
    try:
        if fmt == "json" or (fmt is None and text.lstrip().startswith("{")):
            doc = json.loads(text)
        else:
            doc = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise OrganizationError(f"the organization is not valid {fmt or 'YAML/JSON'}: {exc}") from exc
    if not isinstance(doc, dict):
        raise OrganizationError("the organization must be an object at the top level")
    return doc


def to_yaml(doc: dict[str, Any]) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120)


def to_json(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2)


# ── network helpers ──────────────────────────────────────────────────────────────────────────────────────────────────


def _net_bounds(net: dict[str, Any]) -> tuple[ipaddress.IPv4Address, ipaddress.IPv4Address]:
    if net.get("cidr"):
        n = ipaddress.ip_network(net["cidr"], strict=False)
        return n.network_address, n.broadcast_address
    lo, hi = str(net["range"]).split("-", 1)
    return ipaddress.ip_address(lo), ipaddress.ip_address(hi)


def network_cidrs(net: dict[str, Any]) -> list[str]:
    """The network as CIDR blocks: its own cidr, or the smallest set of blocks covering its address range."""
    if net.get("cidr"):
        return [str(ipaddress.ip_network(net["cidr"], strict=False))]
    lo, hi = _net_bounds(net)
    return [str(n) for n in ipaddress.summarize_address_range(lo, hi)]


def network_contains(net: dict[str, Any], ip: str) -> bool:
    try:
        lo, hi = _net_bounds(net)
        return lo <= ipaddress.ip_address(ip) <= hi
    except ValueError:
        return False


def _is_private(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


# ── validation ──────────────────────────────────────────────────────────────────────────────────────────────────────


def validate_document(doc: Any) -> list[str]:
    """Every problem with `doc`, or [] when it is valid. Schema problems come first; the consistency checks only run on a
    document the schema accepts, so they can rely on its shape."""
    if not isinstance(doc, dict):
        return ["the organization must be an object"]
    errors: list[str] = []
    validator = jsonschema.Draft202012Validator(load_schema())
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(document)"
        errors.append(f"{where}: {err.message}")
    if errors:
        return errors
    return _semantic_errors(doc)


def _dups(values: Iterable[str], label: str) -> list[str]:
    seen: dict[str, int] = {}
    for v in values:
        seen[v] = seen.get(v, 0) + 1
    return [f"{label} {k!r} is used {n} times" for k, n in seen.items() if n > 1]


def _semantic_errors(doc: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    people = doc.get("people", [])
    services = doc.get("service_accounts", [])
    hosts = doc.get("hosts", [])
    networks = doc.get("networks", [])
    sites = {s["id"] for s in doc.get("sites", [])}
    groups = {g["name"] for g in doc.get("groups", [])}
    nets = {n["id"]: n for n in networks}
    host_by = {h["name"].lower(): h for h in hosts}
    domain = doc["domain"]
    email_domain = domain.get("email_domain") or domain["dns"]

    # uniqueness
    logins: list[str] = []
    for p in people:
        logins.append(p["login"].lower())
        if p.get("admin_account"):
            logins.append(p["admin_account"]["login"].lower())
    logins += [s["login"].lower() for s in services]
    errs += _dups(logins, "login")
    errs += _dups([h["name"].lower() for h in hosts], "host name")
    errs += _dups([h["ip"] for h in hosts], "host address")
    errs += _dups([n["id"] for n in networks], "network id")
    errs += _dups([n.get("vlan") for n in networks if n.get("vlan")], "VLAN")  # type: ignore[misc]
    errs += _dups([s["id"] for s in doc.get("sites", [])], "site id")
    errs += _dups([g["name"] for g in doc.get("groups", [])], "group")
    errs += _dups([p["email"].lower() for p in people], "email address")
    errs += _dups([p["okta_id"] for p in people if p.get("okta_id")], "Okta id")
    rids = [p["rid"] for p in people if p.get("rid")]
    rids += [p["admin_account"]["rid"] for p in people if p.get("admin_account", {}).get("rid")]
    rids += [s["rid"] for s in services if s.get("rid")]
    rids += [h["rid"] for h in hosts if h.get("rid")]
    errs += _dups([str(r) for r in rids], "RID")
    # employee numbers: a person's admin account shares the person's, so only people and service accounts count
    errs += _dups([p["employee_number"] for p in people if p.get("employee_number")]
                  + [p["admin_account"]["employee_number"] for p in people
                     if (p.get("admin_account") or {}).get("employee_number")]
                  + [s["employee_number"] for s in services if s.get("employee_number")], "employee number")

    # networks
    bounds_by_id: dict[str, tuple[ipaddress.IPv4Address, ipaddress.IPv4Address]] = {}
    for n in networks:
        try:
            bounds_by_id[n["id"]] = _net_bounds(n)
        except ValueError as exc:
            errs.append(f"network {n['id']}: not a valid address block ({exc})")
            continue
        if sites and n.get("site") and n["site"] not in sites:
            errs.append(f"network {n['id']}: site {n['site']!r} is not declared in sites")
    # overlap: every declared network is a standalone block for host containment and the Cortex
    # setup ranges, with no concept of a parent/child range, so any address shared by two networks
    # makes both ambiguous (which network does that address belong to?). Measured 2026-10-18: `vpn`
    # was widened from a disjoint /22 to a /18 that swallowed `ruh-unmanaged`, saved with no warning
    # because this check did not exist. ids are sorted so the message is deterministic regardless
    # of document order, and each pair is reported once.
    for id_a, id_b in itertools.combinations(sorted(bounds_by_id), 2):
        lo_a, hi_a = bounds_by_id[id_a]
        lo_b, hi_b = bounds_by_id[id_b]
        if max(lo_a, lo_b) <= min(hi_a, hi_b):
            errs.append(f"network {id_a!r} and network {id_b!r} overlap")
    internal = (doc.get("cortex") or {}).get("internal_ranges") or []
    for r in internal:
        try:
            ipaddress.ip_network(r, strict=False)
        except ValueError:
            errs.append(f"cortex.internal_ranges: {r!r} is not a valid CIDR")
    if internal:
        blocks = [ipaddress.ip_network(r, strict=False) for r in internal if _valid_cidr(r)]
        for n in networks:
            try:
                lo, hi = _net_bounds(n)
            except ValueError:
                continue
            if not any(lo in b and hi in b for b in blocks):
                errs.append(f"network {n['id']} is not covered by cortex.internal_ranges")

    # hosts
    for h in hosts:
        net = nets.get(h["network"])
        if net is None:
            errs.append(f"host {h['name']}: network {h['network']!r} does not exist")
        elif not network_contains(net, h["ip"]):
            errs.append(f"host {h['name']}: address {h['ip']} is outside network {h['network']}")
        if sites and h.get("site") and h["site"] not in sites:
            errs.append(f"host {h['name']}: site {h['site']!r} is not declared in sites")
        if h["role"] == "workstation":
            owner = h.get("owner")
            if not owner:
                errs.append(f"workstation {h['name']} has no owner")
            elif owner.lower() not in {p["login"].lower() for p in people}:
                errs.append(f"workstation {h['name']}: owner {owner!r} is not a person")

    # people
    by_login = {p["login"].lower(): p for p in people}
    owner_count: dict[str, int] = {}
    for p in people:
        who = p["login"]
        if not p["email"].lower().endswith("@" + email_domain.lower()):
            errs.append(f"person {who}: email {p['email']!r} is not in the domain {email_domain}")
        ws = host_by.get(p["workstation"].lower())
        if ws is None:
            errs.append(f"person {who}: workstation {p['workstation']!r} does not exist")
        else:
            if ws["role"] != "workstation":
                errs.append(f"person {who}: {p['workstation']} is a {ws['role']}, not a workstation")
            elif (ws.get("owner") or "").lower() != who.lower():
                errs.append(f"person {who}: workstation {ws['name']} is owned by {ws.get('owner')!r}")
            owner_count[ws["name"].lower()] = owner_count.get(ws["name"].lower(), 0) + 1
        if sites and p["site"] not in sites:
            errs.append(f"person {who}: site {p['site']!r} is not declared in sites")
        m = p.get("manager")
        if m and m.lower() not in by_login:
            errs.append(f"person {who}: manager {m!r} is not a person")
        for g in list(p.get("groups", [])) + list((p.get("admin_account") or {}).get("groups", [])):
            if g not in groups:
                errs.append(f"person {who}: group {g!r} is not declared in groups")
        flags = set(p.get("flags", []))
        if "leaver" in flags and not p.get("disabled_on"):
            errs.append(f"person {who}: a leaver needs disabled_on")
        if "contractor" in flags:
            if not who.lower().startswith("ext."):
                errs.append(f"person {who}: a contractor's login starts with 'ext.'")
            if not p.get("contract_end"):
                errs.append(f"person {who}: a contractor needs contract_end")
    for name, n in owner_count.items():
        if n > 1:
            errs.append(f"workstation {host_by[name]['name']} is the primary workstation of {n} people")
    errs += _manager_cycles(people)

    # service accounts
    for s in services:
        if s["host"].lower() not in host_by:
            errs.append(f"service account {s['login']}: host {s['host']!r} does not exist")
        m = s.get("manager")
        if m and m.lower() not in by_login:
            errs.append(f"service account {s['login']}: manager {m!r} is not a person")
        for g in s.get("groups", []):
            if g not in groups:
                errs.append(f"service account {s['login']}: group {g!r} is not declared in groups")

    for key, ip in (doc.get("egress") or {}).items():
        values = ip.values() if isinstance(ip, dict) else [ip]
        for v in values:
            try:
                ipaddress.ip_address(v)
            except ValueError:
                errs.append(f"egress.{key}: {v!r} is not an address")
    return errs


def _valid_cidr(value: str) -> bool:
    try:
        ipaddress.ip_network(value, strict=False)
        return True
    except ValueError:
        return False


def _manager_cycles(people: list[dict[str, Any]]) -> list[str]:
    mgr = {p["login"].lower(): (p.get("manager") or "").lower() for p in people}
    bad: list[str] = []
    for start in mgr:
        seen, cur = {start}, mgr.get(start)
        while cur:
            if cur in seen:
                bad.append(f"the manager chain of {start!r} loops back on itself")
                break
            seen.add(cur)
            cur = mgr.get(cur)
    return bad[:5]


def warnings_for(doc: dict[str, Any]) -> list[str]:
    """Things that are valid but weaken the organization as a simulation (not blocking)."""
    out: list[str] = []
    ws = [h for h in doc.get("hosts", []) if h["role"] == "workstation"]
    if len(ws) < 30:
        out.append(f"{len(ws)} workstations: Cortex Analytics wants at least 30 endpoints over two weeks")
    dept: dict[str, int] = {}
    for p in doc.get("people", []):
        dept[p["department"]] = dept.get(p["department"], 0) + 1
    small = sorted(d for d, n in dept.items() if n < 5)
    if small:
        out.append("departments under 5 people give peer-group detectors little to compare: " + ", ".join(small))
    if not any("outlier" in p.get("flags", []) for p in doc.get("people", [])):
        out.append("no person is flagged outlier: attack scenarios have no designated source user")
    if not any(n.get("kind") == "unmanaged" for n in doc.get("networks", [])):
        out.append("no network of kind 'unmanaged': attack scenarios that need a never-seen internal address cannot run")
    if not (doc.get("cortex") or {}).get("internal_ranges"):
        out.append("cortex.internal_ranges is empty: the Cortex setup panel has nothing to copy")
    return out


def check(doc: Any) -> dict[str, Any]:
    """Validation outcome for the API: {valid, errors, warnings}."""
    errors = validate_document(doc)
    return {"valid": not errors, "errors": errors, "warnings": [] if errors else warnings_for(doc)}


def require_valid(doc: Any) -> None:
    errors = validate_document(doc)
    if errors:
        head = errors[:8]
        more = f" (+{len(errors) - 8} more)" if len(errors) > 8 else ""
        raise OrganizationError("the organization is not valid: " + "; ".join(head) + more, errors)


# ── identity derivation (kept equal to the connectors' by tests) ─────────────────────────────────────────────────────


def okta_user_id(email: str) -> str:
    """The Okta user id of an address: `00u` + 17 characters derived from it (http-sender's okta profile's `user_id`)."""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    digest = hashlib.sha256(email.strip().lower().encode("utf-8")).digest()
    return "00u" + "".join(alphabet[b % len(alphabet)] for b in digest[:17])


def full_sid(doc: dict[str, Any], rid: int | None) -> str | None:
    base = (doc.get("domain") or {}).get("sid")
    return f"{base}-{rid}" if base and rid else None


# ── read views ──────────────────────────────────────────────────────────────────────────────────────────────────────


def summary(doc: dict[str, Any]) -> dict[str, Any]:
    """Counts and the names an operator or agent needs to orient: what the organization is, at a glance."""
    people = doc.get("people", [])
    depts: dict[str, int] = {}
    for p in people:
        depts[p["department"]] = depts.get(p["department"], 0) + 1
    roles: dict[str, int] = {}
    for h in doc.get("hosts", []):
        roles[h["role"]] = roles.get(h["role"], 0) + 1
    return {
        "id": doc["id"],
        "name": doc["name"],
        "description": doc.get("description", ""),
        "domain": doc["domain"],
        "people": len(people),
        "departments": depts,
        "admin_accounts": sum(1 for p in people if p.get("admin_account")),
        "service_accounts": len(doc.get("service_accounts", [])),
        "hosts": roles,
        "networks": len(doc.get("networks", [])),
        "sites": [s["id"] for s in doc.get("sites", [])],
        "timezone": (doc.get("locale") or {}).get("timezone"),
    }


def _person_row(doc: dict[str, Any], p: dict[str, Any], hosts: dict[str, dict[str, Any]],
                detail: bool = False) -> dict[str, Any]:
    """One person as a compact row. `detail` adds what is rarely needed (SID, Okta id, home egress address, groups, dates)."""
    ws = hosts.get(p["workstation"].lower(), {})
    row = {
        "login": p["login"],
        "name": p.get("display_name") or f"{p['given_name']} {p['family_name']}",
        "email": p["email"],
        "title": p["title"],
        "department": p["department"],
        "manager": p.get("manager"),
        "site": p["site"],
        "workstation": p["workstation"],
        "workstation_ip": ws.get("ip"),
    }
    if p.get("admin_account"):
        row["admin_login"] = p["admin_account"]["login"]
    if p.get("flags"):
        row["flags"] = p["flags"]
    if detail:
        row.update({"sid": full_sid(doc, p.get("rid")), "okta_id": p.get("okta_id"), "home_ip": p.get("home_ip"),
                    "groups": p.get("groups", [])})
        for k in ("contract_end", "disabled_on", "cloud_access"):
            if p.get(k):
                row[k] = p[k]
    return row


def _tokens(flt: Any) -> list[tuple[str | None, str]]:
    """A filter as (key, value) pairs: "department=Finance,site=JED", a bare word, or a dict."""
    if not flt:
        return []
    if isinstance(flt, dict):
        return [(str(k).lower(), str(v)) for k, v in flt.items()]
    out: list[tuple[str | None, str]] = []
    for part in str(flt).split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            out.append((k.strip().lower(), v.strip()))
        else:
            out.append((None, part))
    return out


def _match(row: dict[str, Any], tokens: list[tuple[str | None, str]], text_fields: tuple[str, ...]) -> bool:
    for key, value in tokens:
        want = value.lower()
        if key is None:
            hay = " ".join(str(row.get(f) or "") for f in text_fields).lower()
            if want not in hay:
                return False
            continue
        alias = {"flag": "flags", "group": "groups", "dept": "department"}.get(key, key)
        got = row.get(alias)
        if got is None:
            return False
        if isinstance(got, list):
            if want not in [str(g).lower() for g in got]:
                return False
        elif alias in ("title", "name", "purpose", "os"):
            if want not in str(got).lower():
                return False
        elif str(got).lower() != want:
            return False
    return True


DEFAULT_MAX_BYTES = 12_000   # the chat route cuts tool results over 16 KB to head+tail: stay well under it


def section(doc: dict[str, Any], name: str | None = None, flt: Any = None, limit: int = 50, offset: int = 0,
            detail: bool = False, max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """One section of the organization as compact rows. `name` is one of SECTIONS (default overview); `flt` narrows the
    rows ("department=Finance", "flag=vip", "site=JED", "role=server", or a bare word matched against names, logins and
    addresses).

    Lists are PAGED by this function, never cut by a caller: a page holds at most `limit` rows and at most `max_bytes` of
    JSON (a tool result over the chat route's cap would lose its middle without saying so). `total`, `returned`, `offset`,
    `truncated` and, when more remain, `next_offset` always say exactly what the page is. `detail` adds the rarely needed
    columns (SIDs, Okta ids, home addresses, groups)."""
    name = (name or "overview").lower()
    if name not in SECTIONS:
        raise OrganizationError(f"unknown section {name!r}; use one of: {', '.join(SECTIONS)}")
    limit = max(1, min(int(limit or 50), 500))
    offset = max(0, int(offset or 0))
    tokens = _tokens(flt)
    hosts = {h["name"].lower(): h for h in doc.get("hosts", [])}

    def page(rows: list[dict[str, Any]]) -> dict[str, Any]:
        out: list[dict[str, Any]] = []
        used = 400  # the envelope around the rows
        for row in rows[offset:offset + limit]:
            size = len(json.dumps(row, ensure_ascii=False)) + 2
            if out and used + size > max_bytes:
                break
            out.append(row)
            used += size
        end = offset + len(out)
        result = {"total": len(rows), "offset": offset, "returned": len(out), "truncated": end < len(rows), "rows": out}
        if end < len(rows):
            result["next_offset"] = end
        return result

    if name == "overview":
        return {"section": name, **summary(doc), "warnings": warnings_for(doc)}
    if name == "people":
        rows = [_person_row(doc, p, hosts, detail) for p in doc.get("people", [])]
        rows = [r for r in rows if _match(r, tokens, ("login", "name", "email", "title", "department", "workstation"))]
        return {"section": name, **page(rows)}
    if name == "accounts":
        rows = []
        for p in doc.get("people", []):
            ws = hosts.get(p["workstation"].lower(), {})
            row = {"login": p["login"], "kind": "user", "person": p["login"], "sid": full_sid(doc, p.get("rid")),
                   "host": p["workstation"], "host_ip": ws.get("ip"), "department": p["department"],
                   "active": "leaver" not in p.get("flags", [])}
            if detail:
                row.update({"groups": p.get("groups", []), "flags": p.get("flags", [])})
            rows.append(row)
            a = p.get("admin_account")
            if a:
                arow = {"login": a["login"], "kind": "admin", "person": p["login"], "sid": full_sid(doc, a.get("rid")),
                        "host": p["workstation"], "host_ip": ws.get("ip"), "department": p["department"], "active": True}
                if detail:
                    arow.update({"groups": a.get("groups", []), "flags": []})
                rows.append(arow)
        for s_acct in doc.get("service_accounts", []):
            h = hosts.get(s_acct["host"].lower(), {})
            srow = {"login": s_acct["login"], "kind": s_acct["kind"], "person": None,
                    "sid": full_sid(doc, s_acct.get("rid")), "host": s_acct["host"], "host_ip": h.get("ip"),
                    "department": "IT", "active": True}
            if detail:
                srow.update({"groups": s_acct.get("groups", []), "flags": []})
            rows.append(srow)
        rows = [r for r in rows if _match(r, tokens, ("login", "person", "host", "kind"))]
        return {"section": name, **page(rows)}
    if name == "hosts":
        keep = ("name", "role", "ip", "site", "network", "owner", "purpose") if not detail else None
        rows = []
        for h in doc.get("hosts", []):
            r = {k: v for k, v in h.items() if keep is None or k in keep}
            if detail:
                r["fqdn"] = f"{h['name']}.{doc['domain']['dns']}".lower() if h.get("domain_joined") else None
            rows.append(r)
        rows = [r for r in rows if _match(r, tokens, ("name", "ip", "owner", "purpose", "role", "site"))]
        return {"section": name, **page(rows)}
    if name == "networks":
        rows = []
        for n in doc.get("networks", []):
            r = dict(n)
            r["cidrs"] = network_cidrs(n)
            rows.append(r)
        rows = [r for r in rows if _match(r, tokens, ("id", "name", "kind", "site"))]
        return {"section": name, **page(rows)}
    if name == "sites":
        rows = [s_ for s_ in doc.get("sites", []) if _match(s_, tokens, ("id", "name", "city"))]
        return {"section": name, **page(rows)}
    if name == "groups":
        members: dict[str, list[str]] = {}
        for p in doc.get("people", []):
            for g in p.get("groups", []):
                members.setdefault(g, []).append(p["login"])
            for g in (p.get("admin_account") or {}).get("groups", []):
                members.setdefault(g, []).append(p["admin_account"]["login"])
        for s_acct in doc.get("service_accounts", []):
            for g in s_acct.get("groups", []):
                members.setdefault(g, []).append(s_acct["login"])
        rows = [{**g, "members": members.get(g["name"], [])} for g in doc.get("groups", [])]
        rows = [r for r in rows if _match(r, tokens, ("name",))]
        return {"section": name, **page(rows)}
    if name == "personas":
        return {"section": name, **personas(doc)}
    if name == "cloud":
        return {"section": name, **(doc.get("cloud") or {}),
                "people_with_cloud_access": [p["login"] for p in doc.get("people", []) if p.get("cloud_access")]}
    if name == "egress":
        return {"section": name, **(doc.get("egress") or {})}
    return {"section": name, **cortex_setup(doc)}


def personas(doc: dict[str, Any]) -> dict[str, Any]:
    """The designated roles scenarios are built around: who to target, who to attack from, who is gone."""
    hosts = {h["name"].lower(): h for h in doc.get("hosts", [])}
    people = doc.get("people", [])

    def pick(flag: str) -> list[dict[str, Any]]:
        return [_person_row(doc, p, hosts) for p in people if flag in p.get("flags", [])]

    return {
        "vip": pick("vip"),
        "outlier": pick("outlier"),
        "contractors": pick("contractor"),
        "leavers": pick("leaver"),
        "administrators": [_person_row(doc, p, hosts) for p in people if p.get("admin_account")],
        "service_accounts": [s for s in doc.get("service_accounts", []) if s["kind"] == "service"],
        "break_glass": [s for s in doc.get("service_accounts", []) if s["kind"] == "break_glass"],
        "usage": ("Targets of phishing, BEC and MFA-fatigue scenarios are the vip people. Attacks that run from inside "
                  "start at the outlier person's workstation. A leaver's account is disabled: any logon by it is "
                  "the finding. Administrators use their admin login, never their normal one, for privileged work. "
                  "The break-glass account should never log on."),
    }


def cortex_setup(doc: dict[str, Any]) -> dict[str, Any]:
    """What to enter in Cortex under Inventory > Assets > Network Configuration."""
    cortex = doc.get("cortex") or {}
    ranges = list(cortex.get("internal_ranges") or [])
    if not ranges:  # derive from the networks when the document does not say
        for n in doc.get("networks", []):
            ranges += network_cidrs(n)
    suffixes = list(cortex.get("domain_suffixes") or [(doc.get("domain") or {}).get("dns")])
    return {"internal_ranges": ranges, "domain_suffixes": [s for s in suffixes if s],
            "networks": [{"id": n["id"], "name": n["name"], "vlan": n.get("vlan"), "cidrs": network_cidrs(n)}
                         for n in doc.get("networks", [])]}


# ── structured edits ────────────────────────────────────────────────────────────────────────────────────────────────


def _merge(base: Any, patch: Any) -> Any:
    """RFC 7386 merge-patch of objects: null deletes a key, objects merge, everything else replaces."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out = dict(base) if isinstance(base, dict) else {}
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = _merge(out.get(k), v)
    return out


def _next_rid(doc: dict[str, Any]) -> int:
    rids = [1000]
    rids += [p.get("rid") or 0 for p in doc.get("people", [])]
    rids += [(p.get("admin_account") or {}).get("rid") or 0 for p in doc.get("people", [])]
    rids += [s.get("rid") or 0 for s in doc.get("service_accounts", [])]
    rids += [h.get("rid") or 0 for h in doc.get("hosts", [])]
    return max(rids) + 1


def _next_workstation(doc: dict[str, Any], site: str) -> tuple[str, str, str]:
    """(name, ip, network id) for a new workstation at `site`: the next PHWS-nnn name, and the next address after the
    highest one already used by that site's workstations (so a Riyadh hire lands in the Riyadh workstation block)."""
    hosts = doc["hosts"]
    prefix, width = "PHWS-", 3
    numbers = []
    for h in hosts:
        m = re.fullmatch(r"([A-Za-z]+-)(\d+)", h["name"])
        if h["role"] == "workstation" and m:
            prefix, width = m.group(1), len(m.group(2))
            numbers.append(int(m.group(2)))
    name = f"{prefix}{(max(numbers) + 1) if numbers else 1:0{width}d}"
    nets = {n["id"]: n for n in doc["networks"]}
    pool = [h for h in hosts if h["role"] == "workstation" and h.get("site") == site and nets.get(h["network"])]
    taken = {h["ip"] for h in hosts}
    if pool:
        net_id = pool[-1]["network"]
        top = max(ipaddress.ip_address(h["ip"]) for h in pool if h["network"] == net_id)
        candidate = top + 1
    else:
        wanted = [n for n in doc["networks"] if n.get("site") == site and n["kind"] in ("workstations", "branch", "vpn")]
        if not wanted:
            raise OrganizationError(f"no workstation network exists for site {site!r}; add a network first")
        net_id = wanted[0]["id"]
        candidate = _net_bounds(wanted[0])[0] + 20
    net = nets[net_id]
    while str(candidate) in taken:
        candidate += 1
    if not network_contains(net, str(candidate)):
        raise OrganizationError(f"network {net_id} has no free address left")
    return name, str(candidate), net_id


def _autofill_person(doc: dict[str, Any], p: dict[str, Any], notes: list[str]) -> None:
    """Complete a newly added person from the few fields the caller gave: names, title and department."""
    given, family = p.get("given_name"), p.get("family_name")
    if not p.get("login") and given and family:
        p["login"] = f"{given[0]}{family}".lower()
        notes.append(f"login for {given} {family} set to {p['login']}")
    if given and family:
        p.setdefault("display_name", f"{given} {family}")
        email_domain = doc["domain"].get("email_domain") or doc["domain"]["dns"]
        p.setdefault("email", f"{given}.{family}".lower().replace(" ", "") + f"@{email_domain}")
    if p.get("email"):
        p.setdefault("okta_id", okta_user_id(p["email"]))
    p.setdefault("site", "RUH" if any(s["id"] == "RUH" for s in doc.get("sites", [])) else
                 (doc.get("sites") or [{"id": "HQ"}])[0]["id"])
    rid = _next_rid(doc)
    p.setdefault("rid", rid)
    p.setdefault("employee_number", f"PH{p['rid']:05d}")
    dept = p.get("department")
    if dept:
        gname = f"SG-{dept}"
        if not any(g["name"] == gname for g in doc.get("groups", [])):
            doc.setdefault("groups", []).append({"name": gname, "privileged": False})
            notes.append(f"group {gname} added")
        if "groups" not in p:
            p["groups"] = [gname] + (["SG-VPN-Users"] if any(g["name"] == "SG-VPN-Users" for g in doc["groups"]) else [])
        if "manager" not in p:
            mates = [x.get("manager") for x in doc["people"] if x["department"] == dept and x.get("manager")]
            if mates:
                p["manager"] = max(set(mates), key=mates.count)
    if not p.get("workstation"):
        name, ip, net_id = _next_workstation(doc, p["site"])
        p["workstation"] = name
        doc["hosts"].append({"name": name, "role": "workstation", "site": p["site"], "ip": ip, "network": net_id,
                             "os": "Windows 11 Enterprise", "rid": _next_rid(doc) + 1, "owner": p["login"],
                             "domain_joined": True})
        notes.append(f"workstation {name} ({ip}) created for {p['login']}")
    elif not any(h["name"].lower() == p["workstation"].lower() for h in doc["hosts"]):
        raise OrganizationError(f"workstation {p['workstation']!r} does not exist; omit it to create one")


def apply_changes(doc: dict[str, Any], changes: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Apply an edit to a COPY of `doc` and return (new document, notes). Nothing is validated here: the caller runs
    `require_valid` on the result so a bad edit is rejected whole.

    changes = {
      "set":    {"locale": {"timezone": "Asia/Dubai"}, "name": "..."},          # deep merge; null deletes a key
      "upsert": {"people": [{"login": "...", ...}], "hosts": [{"name": "...", ...}]},   # add, or merge fields by key
      "remove": {"people": ["login"], "hosts": ["name"]},
    }
    A new person needs only given_name, family_name, title and department: login, email, workstation (with its host),
    RID, Okta id, groups and manager are filled in, and the notes say what was added. Removing a person also removes their
    workstation and moves the people who reported to them up to their manager; the notes say so."""
    if not isinstance(changes, dict) or not any(k in changes for k in ("set", "upsert", "remove")):
        raise OrganizationError("changes must be an object with at least one of: set, upsert, remove")
    unknown = set(changes) - {"set", "upsert", "remove"}
    if unknown:
        raise OrganizationError(f"unknown change keys: {', '.join(sorted(unknown))}")
    new = copy.deepcopy(doc)
    notes: list[str] = []

    for key, value in (changes.get("set") or {}).items():
        if key not in SETTABLE_SECTIONS:
            raise OrganizationError(f"cannot set {key!r}; settable: {', '.join(SETTABLE_SECTIONS)}. Collections change "
                                    "through upsert and remove")
        new[key] = _merge(new.get(key), value)

    for coll, rows in (changes.get("upsert") or {}).items():
        if coll not in COLLECTION_KEYS:
            raise OrganizationError(f"unknown collection {coll!r}; use: {', '.join(COLLECTION_KEYS)}")
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise OrganizationError(f"upsert.{coll} must be a list of objects")
        key = COLLECTION_KEYS[coll]
        items = new.setdefault(coll, [])
        for row in rows:
            ident = row.get(key)
            existing = next((x for x in items if ident and str(x.get(key, "")).lower() == str(ident).lower()), None)
            if existing is not None:
                merged = _merge(existing, row)
                existing.clear()
                existing.update(merged)
                notes.append(f"{coll}: updated {ident}")
                continue
            row = copy.deepcopy(row)
            if coll == "people":
                _autofill_person(new, row, notes)
            items.append(row)
            notes.append(f"{coll}: added {row.get(key, '(new)')}")

    for coll, keys in (changes.get("remove") or {}).items():
        if coll not in COLLECTION_KEYS:
            raise OrganizationError(f"unknown collection {coll!r}; use: {', '.join(COLLECTION_KEYS)}")
        if not isinstance(keys, list):
            raise OrganizationError(f"remove.{coll} must be a list of {COLLECTION_KEYS[coll]} values")
        key = COLLECTION_KEYS[coll]
        wanted = {str(k).lower() for k in keys}
        found = {str(x.get(key, "")).lower() for x in new.get(coll, [])}
        missing = sorted(wanted - found)
        if missing:
            raise OrganizationError(f"{coll}: nothing to remove for {', '.join(missing)}")
        new[coll] = [x for x in new.get(coll, []) if str(x.get(key, "")).lower() not in wanted]
        notes.append(f"{coll}: removed {', '.join(sorted(wanted))}")
        if coll == "people":
            gone = {str(k).lower(): next((p for p in doc["people"] if p["login"].lower() == str(k).lower()), None)
                    for k in keys}
            for login, person in gone.items():
                parent = (person or {}).get("manager")
                for other in new["people"]:
                    if (other.get("manager") or "").lower() == login:
                        other["manager"] = parent
                        notes.append(f"{other['login']} now reports to {parent or 'nobody'}")
                gone_hosts = [h["name"] for h in new["hosts"]
                              if h["role"] == "workstation" and (h.get("owner") or "").lower() == login]
                if gone_hosts:
                    new["hosts"] = [h for h in new["hosts"] if h["name"] not in gone_hosts]
                    notes.append(f"{', '.join(gone_hosts)} removed with its owner {login}")
                for s in new.get("service_accounts", []):
                    if (s.get("manager") or "").lower() == login:
                        s["manager"] = parent
    return new, notes
