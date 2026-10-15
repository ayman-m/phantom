"""Render the active organization into the read-only `organization` knowledge base.

The Knowledge page and the agent's `knowledge_search` / `knowledge_list` then find the organization the same way they find
the XQL examples. The authoritative, complete source stays the `organization_get` tool (a semantic top-5 would let a model
invent the rest of a roster); these documents are the readable, searchable view of it.

The knowledge base is derived state, not a second home: every save or switch rebuilds it from the store, documents whose
text did not change are skipped by the KB's own source-hash check, and documents the new organization no longer produces
are removed. Embedding can be slow or fail (no embedder configured), so syncing runs off the caller's thread and a failure
only logs: it never blocks or fails an organization save.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from typing import Any

from usecase import organization_model as om

logger = logging.getLogger("Phantom MCP")

KB_NAME = "organization"
_lock = threading.Lock()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def render_docs(rec_id: str, version: int, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The knowledge documents of an organization: [{doc_id, title, category, content}]."""
    name, dns = doc["name"], doc["domain"]["dns"]
    hosts = {h["name"].lower(): h for h in doc.get("hosts", [])}
    head = (f"Active organization: {name} (id {rec_id}, domain {dns}). This is a readable view; the complete, exact "
            f"lists come from the organization_get tool.\n\n")
    out: list[dict[str, Any]] = []

    def add(doc_id: str, title: str, category: str, body: str) -> None:
        out.append({"doc_id": doc_id, "title": title, "category": category, "content": head + body})

    s = om.summary(doc)
    loc = doc.get("locale") or {}
    lines = [f"{name} is {s['description'] or 'a fictitious company'}",
             f"Active Directory domain {dns} (NetBIOS {doc['domain']['netbios']}); email and UPN domain "
             f"{doc['domain'].get('email_domain') or dns}; partner domain {doc['domain'].get('partner_domain', 'none')}.",
             f"{s['people']} people across: " + ", ".join(f"{d} {n}" for d, n in s["departments"].items()) + ".",
             f"{s['admin_accounts']} administrators have a separate adm. account; {s['service_accounts']} service and "
             "break-glass accounts.",
             f"Working week {', '.join(loc.get('workweek', []))}, {loc.get('work_hours', {}).get('start', '')}-"
             f"{loc.get('work_hours', {}).get('end', '')} {loc.get('timezone', '')}.",
             "Sites: " + ", ".join(f"{x['id']} ({x['name']})" for x in doc.get("sites", [])) + ".",
             "Stitching rule: every person has one primary workstation with one fixed address. Use the person's login, "
             "that workstation name and that address together in every log, so Okta, Windows, firewall and cloud events "
             "about one person land on the same entities."]
    add("overview", f"{name}: overview", "overview", "\n".join(lines))

    by_dept: dict[str, list[dict[str, Any]]] = {}
    for p in doc.get("people", []):
        by_dept.setdefault(p["department"], []).append(p)
    for dept, ppl in by_dept.items():
        rows = []
        for p in ppl:
            ws = hosts.get(p["workstation"].lower(), {})
            flags = f" [{', '.join(p['flags'])}]" if p.get("flags") else ""
            admin = f", admin login {p['admin_account']['login']}" if p.get("admin_account") else ""
            rows.append(f"- {p['login']} ({p['given_name']} {p['family_name']}), {p['title']}, {p['site']}, reports to "
                        f"{p.get('manager') or 'nobody'}; workstation {p['workstation']} {ws.get('ip', '')}{admin}{flags}")
        add(f"dept-{_slug(dept)}", f"{dept} department: people", "people",
            f"{dept} department, {len(ppl)} people:\n" + "\n".join(rows))

    infra = [h for h in doc.get("hosts", []) if h["role"] != "workstation"]
    add("infrastructure", "Servers, domain controllers, DMZ, network and cloud hosts", "hosts",
        "\n".join(f"- {h['name']} ({h['role']}, {h.get('site')}) {h['ip']} {h.get('os', '')}: {h.get('purpose', '')}"
                  for h in infra))

    ws_by_site: dict[str, list[dict[str, Any]]] = {}
    for h in doc.get("hosts", []):
        if h["role"] == "workstation":
            ws_by_site.setdefault(h.get("site") or "?", []).append(h)
    for site, items in ws_by_site.items():
        add(f"workstations-{_slug(site)}", f"Workstations at {site}", "hosts",
            "\n".join(f"- {h['name']} {h['ip']} owned by {h.get('owner')}" for h in items))

    add("networks", "Networks, VLANs and address plan", "networks",
        "\n".join(f"- {n['name']} ({n['id']}): {', '.join(om.network_cidrs(n))}"
                  f"{' VLAN ' + str(n['vlan']) if n.get('vlan') else ''}, site {n.get('site')}"
                  for n in doc.get("networks", [])))

    acct = ["Administrators (use the adm. login for privileged work, never the normal login):"]
    acct += [f"- {p['admin_account']['login']} belongs to {p['login']}" for p in doc.get("people", [])
             if p.get("admin_account")]
    acct.append("Service and special accounts:")
    acct += [f"- {a['login']} ({a['kind']}) runs on {a['host']}" for a in doc.get("service_accounts", [])]
    acct.append("Privileged groups: " + ", ".join(g["name"] for g in doc.get("groups", []) if g.get("privileged")))
    add("accounts", "Administrator, service and break-glass accounts", "accounts", "\n".join(acct))

    pers = om.personas(doc)
    names = lambda key: ", ".join(r["login"] for r in pers[key]) or "none"  # noqa: E731
    add("personas", "Designated personas for scenarios", "personas",
        f"VIP targets: {names('vip')}\nAttack source (outlier): {names('outlier')}\nContractors: {names('contractors')}\n"
        f"Leavers (disabled): {names('leavers')}\n{pers['usage']}")

    cloud = doc.get("cloud") or {}
    eg = doc.get("egress") or {}
    add("cloud-and-egress", "Cloud accounts and internet egress addresses", "cloud",
        "\n".join([f"- {k}: " + ", ".join(f"{a}={b}" for a, b in v.items()) for k, v in cloud.items()]
                  + [f"- egress {k}: {v}" for k, v in eg.items()]))

    cx = om.cortex_setup(doc)
    add("cortex-setup", "Cortex Network Configuration for this organization", "cortex",
        "Internal ranges: " + ", ".join(cx["internal_ranges"]) + "\nDomain suffixes: " + ", ".join(cx["domain_suffixes"]))
    return out


def sync(kb: Any, rec: Any | None) -> dict[str, int]:
    """Make the `organization` KB match `rec` (the active record, or None to empty it)."""
    counts = {"insert": 0, "update": 0, "unchanged": 0, "removed": 0, "failed": 0}
    with _lock:
        wanted = render_docs(rec.id, rec.version, rec.document) if rec is not None else []
        for d in wanted:
            h = hashlib.sha256((d["title"] + "\n" + d["content"]).encode("utf-8")).hexdigest()
            try:
                _, action = kb.upsert(kb_name=KB_NAME, doc_id=d["doc_id"], content=d["content"], title=d["title"],
                                      category=d["category"], metadata={"organization": rec.id, "version": rec.version},
                                      source_path=f"organization:{rec.id}", source_hash=h)
                counts[action] += 1
            except Exception as exc:  # noqa: BLE001 - e.g. no embedder; the organization_get tool still works
                counts["failed"] += 1
                logger.warning("organization KB: could not index %s: %s", d["doc_id"], exc)
                if counts["failed"] >= 3:
                    break
        keep = {d["doc_id"] for d in wanted}
        for stale in kb.kb_doc_ids(KB_NAME) - keep:
            if kb.remove(KB_NAME, stale):
                counts["removed"] += 1
    return counts


def sync_in_background(kb: Any, rec: Any | None) -> threading.Thread:
    t = threading.Thread(target=lambda: _run(kb, rec), name="organization-kb-sync", daemon=True)
    t.start()
    return t


def _run(kb: Any, rec: Any | None) -> None:
    try:
        logger.info("organization KB synced: %s", sync(kb, rec))
    except Exception as exc:  # noqa: BLE001
        logger.warning("organization KB sync failed: %s", exc)
