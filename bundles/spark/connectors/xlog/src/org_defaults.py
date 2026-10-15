"""Fill the identity fields a caller left unset from the active organization.

xlog's generator invents a value for every field nobody pins: random hosts, random users, public addresses. That is why logs
from different sources never shared an entity, so Cortex could not stitch them. When the caller leaves the user, host or
address fields of a worker unset, this module pins them to the organization's people, workstations and servers instead.

Two shapes, matching the two ways xlog takes values:

  * vendor-schema path (`schema_override`): the fields are the vendor's own names (`suser`, `source_ip`, `Hostname`). Each
    recognised identity field is bound through the reserved `__entities__` key, so a person, their workstation name and its
    address are drawn TOGETHER for every record, and a server is paired with each as the destination.
  * legacy faker path (the 46-key camelCase vocabulary, scenario steps): one person and one server are pinned for the whole
    call, because that path draws each key independently and could not keep a person with their own workstation.

Nothing the caller set is overwritten: a field named in `observables_dict`, or any `__entities__` the caller gave, is left alone.
Field matching is by NAME, so it is conservative: an unrecognised field keeps its generated value, and the result reports
exactly which fields were bound so the agent (and the operator) can see what happened.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # imported lazily at call time: a connector on an older runtime base image must still load and serve its other tools
    from runtime.organization_view import OrganizationView

MAX_ENTITIES = 100

_SRC = {"src", "source", "client", "actor", "initiator", "origin", "local", "from", "caller"}
_DST = {"dst", "dest", "destination", "target", "server", "remote", "peer", "to", "responder", "resp"}
_USER = {"user", "username", "usr", "account", "login", "principal", "samaccountname", "suser", "duser", "upn",
         "userprincipalname", "accountname"}
_HOST = {"host", "hostname", "computer", "workstation", "machine", "shost", "dhost", "computername", "devicehost",
         "nodename"}
_IP = {"ip", "ipv4", "ipaddress", "addr", "address", "ipaddr"}

# CEF extension keys that stand alone (no side/kind tokens to read)
_CEF = {"src": ("src", "ip"), "dst": ("dst", "ip"), "shost": ("src", "host"), "dhost": ("dst", "host"),
        "suser": ("src", "user"), "duser": ("dst", "user"), "sourceaddress": ("src", "ip"),
        "destinationaddress": ("dst", "ip")}


def _tokens(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return [t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t]


def classify(field: str) -> tuple[str, str] | None:
    """(side, kind) for an identity field, or None. side: 'src' | 'dst'; kind: 'user' | 'host' | 'ip' | 'email' | 'upn'."""
    key = field.lower().replace("_", "").replace("-", "").replace(".", "")
    if key in _CEF:
        return _CEF[key]
    toks = _tokens(field)
    joined = "".join(toks)
    if not toks or "subject" in toks:
        return None
    side = "dst" if any(t in _DST for t in toks) else "src"
    if joined in ("upn", "userprincipalname") or toks[-1] == "upn":
        return side, "upn"
    if toks[-1] in ("email", "mail") and any(t in ("user", "account", "sender", "actor") for t in toks[:-1]):
        return "src", "email"
    if joined in ("email", "mail"):
        return "src", "email"
    last = toks[-1]
    if any(t in _USER for t in toks) and last not in ("domain", "id", "sid", "type", "agent", "group", "count", "email"):
        return side, "user"
    if any(t in _HOST for t in toks) and last not in ("domain", "id", "type", "port", "count", "ip", "address"):
        return side, "host"
    if last in _IP or joined in ("srcip", "dstip", "sourceip", "destip", "destinationip", "clientip", "serverip",
                                 "localip", "remoteip", "srcaddr", "dstaddr"):
        if "remote" in toks or "public" in toks or "nat" in toks or "external" in toks:
            return None  # remote/public/NAT addresses are not the organization's
        return side, "ip"
    return None


def _server_for(view: OrganizationView, login: str) -> dict[str, Any] | None:
    servers = [h for h in view.hosts_by_role("server") if h.get("domain_joined", True)]
    if not servers:
        return None
    return servers[int.from_bytes(hashlib.sha256(login.encode()).digest()[:4], "big") % len(servers)]


def _people(view: OrganizationView) -> list[dict[str, Any]]:
    return [p for p in view.people if "leaver" not in p.get("flags", [])]


def _usable(spec: dict[str, Any]) -> bool:
    t = spec.get("type")
    return not spec.get("is_array") and not spec.get("is_meta") and (t in (None, "", "string", "str", "text", "ip"))


def apply_to_schema_path(view: OrganizationView, fields: list[dict[str, Any]],
                         observables: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """For a `schema_override` worker: return (observables with `__entities__` added, report).

    The report is {"organization": id, "bound": {field: role}, "entities": n}; `bound` is empty (and the observables
    unchanged) when the caller already supplied `__entities__` or no field was recognised."""
    obs = dict(observables or {})
    if "__entities__" in obs:
        return obs, {"organization": view.id, "bound": {}, "entities": 0, "skipped": "caller supplied __entities__"}
    pinned = {k.lower() for k in obs}
    bound: dict[str, tuple[str, str]] = {}
    for spec in fields:
        name = spec.get("name")
        if not name or name.lower() in pinned or not _usable(spec):
            continue
        role = classify(name)
        if role is not None:
            bound[name] = role
    if not bound:
        return obs, {"organization": view.id, "bound": {}, "entities": 0}
    entities: list[dict[str, Any]] = []
    for p in _people(view)[:MAX_ENTITIES]:
        ws = view.host(p["workstation"])
        srv = _server_for(view, p["login"])
        ent: dict[str, Any] = {}
        for name, (side, kind) in bound.items():
            if side == "src":
                value = {"user": p["login"], "host": ws["name"] if ws else None, "ip": ws["ip"] if ws else None,
                         "email": p["email"], "upn": f"{p['login']}@{view.dns}"}[kind]
            else:
                value = {"user": p["login"], "host": srv["name"] if srv else None, "ip": srv["ip"] if srv else None,
                         "email": p["email"], "upn": f"{p['login']}@{view.dns}"}[kind]
            if value:
                ent[name] = value
        if ent:
            entities.append(ent)
    if not entities:
        return obs, {"organization": view.id, "bound": {}, "entities": 0}
    obs["__entities__"] = entities
    return obs, {"organization": view.id, "bound": {n: f"{s} {k}" for n, (s, k) in bound.items()},
                 "entities": len(entities)}


# Legacy faker vocabulary (camelCase). key -> (side, kind)
_LEGACY = {"srcHost": ("src", "host"), "dstHost": ("dst", "host"), "localIp": ("src", "ip"), "sourceIp": ("src", "ip"),
           "sourceIP": ("src", "ip"), "clientIp": ("src", "ip"), "clientIP": ("src", "ip"), "privateIp": ("src", "ip"),
           "privateIP": ("src", "ip"), "destinationIp": ("dst", "ip"), "destinationIP": ("dst", "ip"),
           "serverIp": ("dst", "ip"), "serverIP": ("dst", "ip"), "user": ("src", "user"),
           "senderEmail": ("src", "email"), "srcDomain": ("src", "domain")}


def pick_actor(view: OrganizationView) -> dict[str, Any]:
    """The person a legacy-path call defaults to: the designated outlier (attacks run from them), else the first person
    who is neither a VIP nor a leaver."""
    outliers = view.people_with_flag("outlier")
    if outliers:
        return outliers[0]
    ok = [p for p in _people(view) if "vip" not in p.get("flags", [])]
    return (ok or _people(view) or view.people)[0]


def apply_to_legacy_path(view: OrganizationView, observables: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """For the legacy faker vocabulary: pin the unset identity keys to one person, their workstation and one server."""
    obs = dict(observables or {})
    p = pick_actor(view)
    ws = view.host(p["workstation"])
    srv = _server_for(view, p["login"])
    values = {("src", "host"): ws and ws["name"], ("src", "ip"): ws and ws["ip"], ("src", "user"): p["login"],
              ("src", "email"): p["email"], ("src", "domain"): view.dns,
              ("dst", "host"): srv and srv["name"], ("dst", "ip"): srv and srv["ip"]}
    bound: dict[str, str] = {}
    present = {k.lower() for k in obs}
    for key, role in _LEGACY.items():
        if key.lower() in present or values.get(role) in (None, ""):
            continue
        present.add(key.lower())
        obs[key] = [values[role]]
        bound[key] = f"{role[0]} {role[1]}"
    return obs, {"organization": view.id, "actor": p["login"], "bound": bound}


def resolve(*, schema_fields: list[dict[str, Any]] | None, observables: dict[str, Any] | None,
            use_organization: bool = True) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The one entry point the tools call: (observables, report). With `use_organization` false the call is returned
    untouched and the report is None. The organization is read NOW, per call, from the shared data volume; an unreadable
    organization stops the call with a message that says what to check, instead of generating a different company."""
    if not use_organization:
        return observables, None
    from runtime.organization_reader import OrganizationUnavailable
    from runtime.organization_view import get_view
    try:
        view = get_view()
    except OrganizationUnavailable as exc:
        raise ValueError(
            f"cannot fill users, hosts and addresses from the organization: {exc}. Fix that, or pass "
            "use_organization=false to generate unconstrained random identities.") from exc
    obs, report = (apply_to_schema_path(view, schema_fields, observables) if schema_fields
                   else apply_to_legacy_path(view, observables))
    # Keep "no observables" as None when nothing was bound, so an unchanged call sends exactly what it sent before.
    return (obs if obs or observables is not None else None), report
