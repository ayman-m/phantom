"""A minimal valid organization on another domain, shared by the organization tests (the replace test)."""

from __future__ import annotations


def _small_org(org_id: str = "acme") -> dict:
    """A minimal valid organization on another domain (for the replace test)."""
    return {
        "schema_version": 1, "id": org_id, "name": "Acme Example",
        "domain": {"dns": "acme.example", "netbios": "ACME"},
        "sites": [{"id": "HQ", "name": "Headquarters", "kind": "office"}],
        "networks": [{"id": "lan", "name": "LAN", "site": "HQ", "kind": "workstations", "cidr": "10.50.0.0/24"}],
        "groups": [{"name": "SG-All"}],
        "hosts": [{"name": "ACME-WS-001", "role": "workstation", "site": "HQ", "ip": "10.50.0.21", "network": "lan",
                   "owner": "jdoe"}],
        "people": [{"login": "jdoe", "given_name": "Jane", "family_name": "Doe", "email": "jane.doe@acme.example",
                    "title": "Analyst", "department": "Finance", "site": "HQ", "workstation": "ACME-WS-001",
                    "groups": ["SG-All"]}],
    }
