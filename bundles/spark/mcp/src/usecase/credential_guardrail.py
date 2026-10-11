"""Canonical set of credential-side tool names (agent credential guardrail).

The root CLAUDE.md ("Agent credential guardrail") says the chat agent must
never have a tool that reads, writes, mints or rotates credentials: provider
auth, per-instance connector secrets, API keys. Those operations are REST-only
(`/api/v1/providers`, `/api/v1/instances`, `/api/v1/api_keys`).

This module is the ONE place that lists those tool names. Every enforcement
point derives from it, so there are no hand-kept copies to drift apart:

  - `connector_loader` refuses to register any of them as an agent tool
  - `self_mod_tools` builds the `agent_batch_propose` table and asserts it
    does not overlap this set, and the batch tool refuses an action naming one
  - the job-scheduler tool dispatcher refuses them, which covers `tool_call`
    job actions and the batch tool's registry route

It is a leaf module on purpose: it imports nothing from the rest of the
package, so any of those layers can import it without creating a cycle.

Adding a name here is always safe. Removing one needs the same review as
changing the guardrail itself.
"""

from __future__ import annotations

from typing import Iterable

# Read-only listing tools (`providers_list`, `providers_get`, `instances_list`,
# `instances_get`, `api_keys_list`) are NOT in this set: they return secrets
# redacted and stay on the agent surface.
CREDENTIAL_SIDE_TOOLS: frozenset[str] = frozenset({
    "providers_create",
    "providers_update",
    "providers_delete",
    "instances_create",
    "instances_update",
    "instances_delete",
    "api_keys_create",
    "api_keys_rotate",
    "api_keys_revoke",
})

# Namespaced forms a registry or dispatcher may use for the same tool
# (`connector.tool`, `connector/tool`, `connector__tool`).
_SEPARATORS = ("__", "/", ".")


class CredentialGuardrailError(ValueError):
    """A credential-side tool was named where the agent can reach it.

    A ValueError so request-validation paths (job actions) report it as a
    bad request rather than a server fault.
    """


def _bare_name(name: str) -> str:
    for sep in _SEPARATORS:
        if sep in name:
            name = name.rsplit(sep, 1)[-1]
    return name


def is_credential_tool(name: object) -> bool:
    """True when `name`, bare or namespaced, is a credential-side tool."""
    if not isinstance(name, str) or not name:
        return False
    return name in CREDENTIAL_SIDE_TOOLS or _bare_name(name) in CREDENTIAL_SIDE_TOOLS


def assert_no_credential_tools(names: Iterable[str], *, where: str) -> None:
    """Raise `CredentialGuardrailError` if any name is credential-side.

    `where` names the surface being checked, for the error message.
    """
    leaked = sorted({n for n in names if is_credential_tool(n)})
    if leaked:
        raise CredentialGuardrailError(
            f"credential-side tool(s) {leaked} must not be reachable from the "
            f"agent ({where}); they are REST-only. See the agent credential "
            f"guardrail in CLAUDE.md."
        )
