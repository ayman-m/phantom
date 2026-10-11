"""
Phantom — on-prem updater service.

Runs as a sidecar container in the customer's compose stack. Drives
the host's docker daemon via the mounted /var/run/docker.sock and
shells out to `docker compose` (using the host install dir mounted at
/host) to swap services after a pull.

Why a separate service (not a phantom-agent route): during an update,
phantom-agent's container is replaced. If the updater code lived inside
that image, the user's progress stream would die mid-update. Living in
its own container — its own image, its own version — means the updater
keeps streaming even when phantom-agent restarts.

V1 scope (per product direction):
  - No rollback. If a post-update healthcheck times out, we surface the
    error and stop; recovery is a manual SSH job.
  - No data-volume snapshots. Customers may lose in-flight jobs/chats
    during an update; this is acceptable for the early version where
    the goal is "push-button-update-when-something-breaks."
  - Updater never updates itself. A future `update-updater.sh` ships
    with the install kit for the rare cases that's needed.

API:
  GET  /healthz                       no auth, container healthcheck
  GET  /api/v1/version/current        running container image versions
  GET  /api/v1/version/check          compare running vs GHCR latest
  GET  /api/v1/update/status          {in_progress: bool}
  POST /api/v1/update                 SSE stream of update progress

Auth: every endpoint except /healthz requires
  Authorization: Bearer <MCP_TOKEN>
where MCP_TOKEN matches the env var (same shared secret phantom-agent
uses for its own MCP coordination). If MCP_TOKEN is unset, all
authenticated routes return 401 — fail-closed by design.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import re
import subprocess
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncGenerator

import docker
import httpx
from docker.errors import DockerException, NotFound
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


# ─── Configuration ────────────────────────────────────────────────────
# All knobs come from env vars. Defaults match the customer compose.

# Images are public on GHCR: every pull and every release lookup is anonymous,
# so there is no registry user, token or `docker login` anywhere in here.
REGISTRY = os.environ.get("PHANTOM_REGISTRY", "ghcr.io")
OWNER = os.environ.get("PHANTOM_OWNER", "ayman-m")
# Every published GHCR package carries this suffix (`phantom-agent-oss`,
# `phantom-connector-cortex-xdr-oss`, ...). Container and compose-service
# names do NOT: only the registry package name changes.
PACKAGE_SUFFIX = "-oss"
MCP_TOKEN = os.environ.get("MCP_TOKEN", "")
HOST_INSTALL_DIR = os.environ.get("HOST_INSTALL_DIR", "/host")

# How long we'll wait for a service to become healthy after restart
# before declaring the update failed. Longer than the longest
# healthcheck.start_period in the customer compose (caldera at 60s).
HEALTHY_TIMEOUT_S = int(os.environ.get("HEALTHY_TIMEOUT_S", "240"))


# ─── /host/.env reads ─────────────────────────────────────────────────
# PHANTOM_VERSION + DIGEST_PHANTOM_* are NOT passed to the phantom-updater
# container as `environment:` entries in the customer compose. An env
# entry that changes with the stack version would change docker compose's
# config-hash and recreate this container on every upgrade, even when
# phantom-updater's own image digest hasn't changed. Instead these are
# read from /host/.env at runtime so the updater's container config
# stays stable across stack upgrades that don't touch its image.
#
# Cache: parses /host/.env once per `_HOST_ENV_TTL_S` seconds. Long
# enough to amortize hot-path API calls (e.g. /api/v1/version/current
# fires on every observability-panel refresh), short enough that an
# operator's manual .env edit or a successful _apply_manifest_to_env
# call propagates within ~30s.
import time as _time_for_env_cache

_HOST_ENV_CACHE: dict[str, str] = {}
_HOST_ENV_CACHE_AT: float = 0.0
_HOST_ENV_TTL_S = 30.0


def _read_host_env() -> dict[str, str]:
    """Parse /host/.env, return {KEY: VALUE}. Cached with a 30s TTL.

    Bypassed (cache cleared) when `_apply_manifest_to_env` writes a
    new manifest — that path calls `_invalidate_host_env_cache()` to
    force the next read to re-parse fresh.

    Failure semantics: a missing /host/.env returns {} (callers
    handle missing keys gracefully). A malformed line is skipped
    with a debug log; we don't crash the updater over .env edits.
    """
    global _HOST_ENV_CACHE_AT
    now = _time_for_env_cache.monotonic()
    if _HOST_ENV_CACHE and (now - _HOST_ENV_CACHE_AT) < _HOST_ENV_TTL_S:
        return _HOST_ENV_CACHE
    env_path = pathlib.Path(HOST_INSTALL_DIR) / ".env"
    if not env_path.is_file():
        # Empty cache, freshly stamped — avoid hammering the FS while
        # /host isn't writable yet (compose timing edge case at boot).
        _HOST_ENV_CACHE_AT = now
        return _HOST_ENV_CACHE
    parsed: dict[str, str] = {}
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key:
                continue
            # Strip surrounding quotes if present (the installer doesn't
            # quote, but operators editing by hand might).
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            parsed[key] = value
    except OSError as exc:
        log.warning("Failed reading %s: %s", env_path, exc)
    _HOST_ENV_CACHE.clear()
    _HOST_ENV_CACHE.update(parsed)
    _HOST_ENV_CACHE_AT = now
    return _HOST_ENV_CACHE


def _invalidate_host_env_cache() -> None:
    """Force the next _read_host_env() to re-parse fresh. Called by
    _apply_manifest_to_env after writing the new digest manifest so
    the in-process state reflects on-disk reality immediately."""
    global _HOST_ENV_CACHE_AT
    _HOST_ENV_CACHE_AT = 0.0


def _host_env_get(key: str, default: str | None = None) -> str | None:
    """Lookup `key` in /host/.env. Returns `default` if absent."""
    return _read_host_env().get(key, default)


def _running_phantom_version() -> str | None:
    """Currently-running stack version, sourced from /host/.env (not
    os.environ) so changes (via _apply_manifest_to_env or operator hand-
    edit) propagate without a container restart."""
    return _host_env_get("PHANTOM_VERSION")


def _stack_digest_env_var(service: str) -> str:
    """Map a compose service name to its DIGEST_PHANTOM_<SVC> env-var
    name. Centralized so callers don't duplicate the casing rule."""
    return f"DIGEST_PHANTOM_{service.replace('phantom-', '').upper().replace('-', '_')}"


def _stack_digest(service: str) -> str | None:
    """Currently-pinned digest for `service`, sourced from /host/.env.
    Returns None if missing."""
    return _host_env_get(_stack_digest_env_var(service))


def _connector_digest_env_var(connector_id: str) -> str:
    """Map a connector id to its DIGEST_PHANTOM_CONNECTOR_<ID> env-var
    name. Centralized so callers don't duplicate the casing rule."""
    return f"DIGEST_PHANTOM_CONNECTOR_{connector_id.upper().replace('-', '_')}"


# ─── /host/connector-digests.env reads ─────────────────────────────────
# Connector image digests (DIGEST_PHANTOM_CONNECTOR_*) are kept apart
# from /host/.env, following the operator config-file separation
# principle (see CLAUDE.md):
#   - .env is for service credentials + the 5 core compose-substitution
#     variables that docker-compose interpolates.
#   - Per-instance connector image refs are NOT compose substitutions;
#     they're runtime data this updater uses to spawn dynamic instance
#     containers. They belong in a dedicated file.
#
# The digests are read from /host/connector-digests.env only. Same
# env-format as .env (KEY=VALUE per line), but isolated. The installer
# writes this file when applying a release manifest, with one
# DIGEST_PHANTOM_CONNECTOR_* key per bundle connector.

_HOST_CONNECTOR_DIGESTS_CACHE: dict[str, str] = {}
_HOST_CONNECTOR_DIGESTS_CACHE_AT: float = 0.0


def _read_host_connector_digests_env() -> dict[str, str]:
    """Parse /host/connector-digests.env, return {KEY: VALUE}. 30s TTL.

    Failure semantics: a missing file returns {} (callers handle
    missing keys gracefully).
    """
    global _HOST_CONNECTOR_DIGESTS_CACHE_AT
    now = _time_for_env_cache.monotonic()
    if (
        _HOST_CONNECTOR_DIGESTS_CACHE
        and (now - _HOST_CONNECTOR_DIGESTS_CACHE_AT) < _HOST_ENV_TTL_S
    ):
        return _HOST_CONNECTOR_DIGESTS_CACHE
    env_path = pathlib.Path(HOST_INSTALL_DIR) / "connector-digests.env"
    if not env_path.is_file():
        _HOST_CONNECTOR_DIGESTS_CACHE_AT = now
        return _HOST_CONNECTOR_DIGESTS_CACHE
    parsed: dict[str, str] = {}
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            parsed[key] = value
    except OSError as exc:
        log.warning("Failed reading %s: %s", env_path, exc)
    _HOST_CONNECTOR_DIGESTS_CACHE.clear()
    _HOST_CONNECTOR_DIGESTS_CACHE.update(parsed)
    _HOST_CONNECTOR_DIGESTS_CACHE_AT = now
    return _HOST_CONNECTOR_DIGESTS_CACHE


def _invalidate_host_connector_digests_cache() -> None:
    """Force re-parse on next _read_host_connector_digests_env() call."""
    global _HOST_CONNECTOR_DIGESTS_CACHE_AT
    _HOST_CONNECTOR_DIGESTS_CACHE_AT = 0.0


# ─── Agent URL resolution (TLS-aware) ───────────────────────────────────
# phantom-updater calls the agent for instance container_url updates,
# audit log writes, and reconcile's `/api/v1/instances` fetch. The agent
# runs behind a TLS proxy on port 8080, so these calls must use https:
# plain HTTP fails with "Server disconnected without sending a response"
# because the TLS handshake rejects it.
#
# The scheme is not derived from SSL_CERT_PEM in /host/.env: that
# variable is only set when the operator pasted a cert at install time,
# while the agent's entrypoint auto-generates a self-signed cert
# otherwise. See _resolve_agent_internal_url().

_DEFAULT_AGENT_URL = "https://phantom-agent:8080"


def _agent_tls_verify() -> bool:
    """Return whether to verify TLS for agent calls.

    When phantom-updater hits the DEFAULT compose-internal URL
    (https://phantom-agent:8080), the agent's cert is the auto-generated
    self-signed one in /tls/cert.pem. That cert has no CA chain, so
    verify=True can NEVER succeed (CERTIFICATE_VERIFY_FAILED: self-signed
    certificate). The intra-cluster trust boundary is the docker network
    alias (only the legitimate phantom-agent container answers on that
    DNS name), not the cert chain.

    Default: verify=False when using the default agent URL. When the
    operator explicitly overrides PHANTOM_AGENT_INTERNAL_URL to a
    CA-signed endpoint, they can also set PHANTOM_TLS_VERIFY=1 to opt in
    to chain validation.

    PHANTOM_AGENT_INTERNAL_URL + PHANTOM_TLS_VERIFY are read from
    /host/.env via _host_env_get(), NOT from os.environ. Same pattern
    as PHANTOM_SECRET_KEK, PHANTOM_VERSION, and the DIGEST_PHANTOM_*
    reads. Reason: the compose phantom-updater.environment block
    INTENTIONALLY doesn't pass them — any env-block change there forces
    a phantom-updater container recreate on stack upgrade and defeats
    digest-pinning state preservation. So os.environ.get() would always
    return "" even when the operator had set the override in .env,
    silently making the escape hatch a no-op.
    """
    override = (_host_env_get("PHANTOM_AGENT_INTERNAL_URL", "") or "").strip()
    if override:
        # Honor operator's verify preference for non-default URLs.
        return (_host_env_get("PHANTOM_TLS_VERIFY", "1") or "1").strip() not in (
            "0", "false", "False", "no", "NO",
        )
    # Default URL is compose-internal self-signed; never verify.
    return False


def _resolve_agent_internal_url() -> str:
    """Return https://phantom-agent:8080 (or operator override).

    The agent's TLS state is not reliably signaled by .env's
    `SSL_CERT_PEM`: that variable is non-empty only when the operator
    EXPLICITLY pasted a cert at install time. Otherwise the agent's
    entrypoint auto-generates a self-signed cert at `/tls/cert.pem`,
    and the TLS proxy serves HTTPS unconditionally on port 8080. So
    phantom-agent:8080 is ALWAYS https from any compose-network
    client's perspective. Deriving the scheme from SSL_CERT_PEM would
    pick http on installs where it is unset, and the TLS proxy would
    reject the connection ("Server disconnected without sending a
    response").

    Default: always https. The operator override stays as an escape
    hatch for non-TLS configurations.

    The verify=False path that callers use is correct — the agent's
    self-signed cert isn't chain-validatable; the trust boundary is at
    the compose network edge, not the cert.

    PHANTOM_AGENT_INTERNAL_URL is read from /host/.env via
    _host_env_get(), NOT from os.environ. See the matching note in
    _agent_tls_verify(): the compose env block intentionally doesn't
    pass it through, so os.environ.get() would always return "" and an
    operator's .env override would be silently ignored.
    """
    override = (_host_env_get("PHANTOM_AGENT_INTERNAL_URL", "") or "").strip()
    if override:
        return override.rstrip("/")
    return "https://phantom-agent:8080"


# httpx-equivalent verify flag for intra-cluster HTTPS calls. The
# agent's TLS cert is self-signed (per /tls/cert.pem); we don't
# verify here because the connection is within the compose
# internal network — trust boundary is at the docker network edge,
# not the cert chain. Used by the .get/.put/.post calls below.
_INTERNAL_HTTPS_VERIFY = False


def _connector_digest(connector_id: str) -> str | None:
    """Currently-pinned digest for the named connector.

    Source of truth: /host/connector-digests.env, and only that file.
    Connector pins never live in /host/.env.

    Returns None if the pin is missing.
    """
    key = _connector_digest_env_var(connector_id)
    return _read_host_connector_digests_env().get(key) or None


# Maps compose service name → (GHCR package name, container_name).
# The container_name comes from the `container_name:` field in the
# customer compose; we look up containers by that. Order of this dict
# is the order updates are applied.
MANAGED_SERVICES: dict[str, tuple[str, str]] = {
    "xlog":          (f"phantom-xlog{PACKAGE_SUFFIX}",    "xlog"),
    "caldera":       (f"phantom-caldera{PACKAGE_SUFFIX}", "caldera"),
    "phantom-agent": (f"phantom-agent{PACKAGE_SUFFIX}",   "phantom_agent"),
}


# ─── Logging ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("phantom-updater")


# ─── Globals ──────────────────────────────────────────────────────────
# Single-update mutex: prevents two browser tabs from triggering
# concurrent updates against the same daemon. The lock is module-level
# (process-scoped). The updater is single-instance per compose stack
# so this is sufficient.

_update_lock = asyncio.Lock()
_update_active = False
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


# ─── Helpers ──────────────────────────────────────────────────────────


def _docker_client() -> docker.DockerClient:
    """
    Lazy-construct a Docker SDK client. Done per-request so failures
    surface as 503s rather than crashing the whole service at startup
    (e.g. when /var/run/docker.sock isn't mounted yet).
    """
    return docker.from_env()


# Memoized at first use; never changes for the lifetime of the
# container so a module-global is safe.
_COMPOSE_PROJECT_NAME: str | None = None


def _compose_project_name() -> str:
    """Return the docker compose project name THIS container belongs to.

    Why this is needed: when we shell out to `docker compose -f
    /host/docker-compose.yml ... up -d <service>` from inside the
    updater container, compose derives the project name from the
    directory containing the compose file → "host". But the host
    started the stack from /opt/phantom → project "phantom". The
    customer compose pins `container_name: caldera` etc., so the
    existing project-"phantom" caldera owns the name. Compose's
    project-"host" view tries to CREATE a fresh caldera and 409s
    on the name conflict → restart fails with rc=1.

    Reading our own container's `com.docker.compose.project` label
    aligns the project name automatically, so it works for any
    install dir (customer's /opt/phantom → "phantom", a developer's
    ~/dev/phantom → "phantom", a CI worktree → whatever). No
    customer-side env var to set, no installer-side stamping needed.

    Falls back to "phantom" if label lookup fails for any reason —
    that's the right default for the customer installer path which
    is overwhelmingly the deployment shape this code runs in.
    """
    global _COMPOSE_PROJECT_NAME
    if _COMPOSE_PROJECT_NAME is not None:
        return _COMPOSE_PROJECT_NAME
    try:
        # /etc/hostname inside a container is the container's short id
        # (12-hex), which the docker socket can resolve to the full
        # container object.
        own_id = pathlib.Path("/etc/hostname").read_text().strip()
        client = _docker_client()
        c = client.containers.get(own_id)
        proj = c.labels.get("com.docker.compose.project")
        if proj:
            _COMPOSE_PROJECT_NAME = proj
            log.info("compose project detected from labels: %s", proj)
            return proj
    except Exception as exc:
        log.warning(
            "could not auto-detect compose project (%s); "
            "falling back to default 'phantom'",
            exc,
        )
    _COMPOSE_PROJECT_NAME = "phantom"
    return _COMPOSE_PROJECT_NAME


def _parse_image_ref(image_ref: str) -> tuple[str, str, str]:
    """
    Parse 'ghcr.io/ayman-m/phantom-agent-oss:1.2.0' into
    (registry, package, tag). Tolerates short forms like
    'phantom-agent-oss' (no registry, no tag → defaults to 'latest').
    """
    if "/" in image_ref:
        first, rest = image_ref.split("/", 1)
        registry = first if "." in first else ""
        package = rest if registry else image_ref
    else:
        registry = ""
        package = image_ref
    if ":" in package:
        package, tag = package.rsplit(":", 1)
    else:
        tag = "latest"
    return registry, package, tag


def _semver_gt(a: str, b: str) -> bool:
    """True iff a > b as semver tuples. Strings must match N.N.N."""
    if not (_SEMVER_RE.match(a) and _SEMVER_RE.match(b)):
        return False
    return tuple(int(x) for x in a.split(".")) > tuple(
        int(x) for x in b.split(".")
    )


def _current_version_for(service: str) -> dict:
    """
    Inspect the running container for `service` and return its version.
    Returns {service, image, version, digest, container_id, running}
    where `version` is the parsed tag (e.g. "1.2.0") or None if the
    container isn't running or its image has no semver tag.

    Also returns `digest` — the sha256:... content digest of
    the running image, sourced from the image's RepoDigests if the
    image was pulled (vs. built locally). For dev/CI builds with no
    RepoDigests entry, returns None for digest. The /observability/connectors
    panel uses this to show a "running digest" column.
    """
    package, container_name = MANAGED_SERVICES[service]
    client = _docker_client()
    try:
        c = client.containers.get(container_name)
    except NotFound:
        return {
            "service": service,
            "image": None,
            "version": None,
            "digest": None,
            "container_id": None,
            "running": False,
        }
    image_tags = c.image.tags or []
    image_ref = image_tags[0] if image_tags else (c.image.id or "")
    _, _, tag = _parse_image_ref(image_ref)

    # Extract digest from RepoDigests. Format is
    # ['ghcr.io/.../package@sha256:abc...', ...]. Multiple entries
    # possible if the image was tagged from multiple repos; pick the
    # first that matches our REGISTRY/OWNER/package shape.
    digest: str | None = None
    repo_digests = c.image.attrs.get("RepoDigests") or []
    expected_prefix = f"{REGISTRY}/{OWNER}/{package}@"
    for rd in repo_digests:
        if rd.startswith(expected_prefix):
            digest = rd.split("@", 1)[1]
            break
    if digest is None and repo_digests:
        # Fallback: take the first RepoDigest's hash even if the prefix
        # doesn't match (e.g. operator built locally with different tag).
        digest = repo_digests[0].split("@", 1)[1] if "@" in repo_digests[0] else None

    return {
        "service": service,
        "image": image_ref,
        # Don't return non-semver tags as `version` — they confuse the
        # comparison logic. Customers running off `:latest` for some
        # reason will see version=None and `update=False`.
        "version": tag if _SEMVER_RE.match(tag) else None,
        "digest": digest,
        "container_id": c.short_id,
        "running": c.status == "running",
    }


# ─── Manifest-driven update helpers ─────────────────────────────────────

async def _latest_release_version() -> str | None:
    """Return the highest semver tag published as a GitHub Release.

    GitHub Releases carry exactly the customer-installable releases (one
    Release per tag push); GHCR also carries pre-release CI builds and
    manual debug pushes, so its tags are not a source of truth. The
    manifest needed for the upgrade is attached as a Release asset.

    The repository is public, so the lookup is anonymous (no
    Authorization header). Anonymous GitHub API calls are rate limited
    per source IP (60/hour), which is ample for an operator-triggered
    update check.

    Returns 'N.N.N' string or None on error.
    """
    url = f"https://api.github.com/repos/{OWNER}/phantom/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            release = r.json()
    except httpx.HTTPError as e:
        log.error("GitHub Releases API error: %s", e)
        return None
    tag = release.get("tag_name", "").lstrip("v")
    if not _SEMVER_RE.match(tag):
        log.warning("Latest release tag is not semver: %r", tag)
        return None
    return tag


async def _fetch_release_manifest(version: str) -> dict[str, str] | None:
    """Fetch release-manifest-vX.Y.Z.env from the GitHub Release for
    `version` and parse it into a dict of env-var-style key→value.

    Returns None on any error (network, missing asset, parse failure).
    The caller decides what to surface as an SSE error event.

    Authoritative source for digest values during in-app updates. The
    same manifest is embedded in the phantom-installer binary for fresh
    installs; this fetcher is the upgrade path's equivalent.
    """
    asset_name = f"release-manifest-v{version}.env"
    download_url = (
        f"https://github.com/{OWNER}/phantom/releases/download/"
        f"v{version}/{asset_name}"
    )
    headers = {"Accept": "application/octet-stream"}
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(download_url, headers=headers)
            r.raise_for_status()
            content = r.text
    except httpx.HTTPError as e:
        log.error("Manifest fetch error for v%s: %s", version, e)
        return None

    # Parse env-style. Skip blank lines and # comments. Each remaining
    # line should be KEY=VALUE; we split on first `=` only because
    # digest values like sha256:... don't contain `=`.
    parsed: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            log.warning("Skipping malformed manifest line: %r", line)
            continue
        k, v = line.split("=", 1)
        parsed[k.strip()] = v.strip()

    # Validate required keys are present. We need at minimum
    # PHANTOM_VERSION + 5 stack digests; per-instance connectors are
    # validated by phantom-updater at runtime (look up DIGEST_PHANTOM_CONNECTOR_*
    # only when an instance is created). If the stack-tier validation
    # fails, the manifest is corrupted and we shouldn't proceed.
    required = [
        "PHANTOM_VERSION",
        "DIGEST_PHANTOM_AGENT",
        "DIGEST_PHANTOM_XLOG",
        "DIGEST_PHANTOM_CALDERA",
        "DIGEST_PHANTOM_UPDATER",
        "DIGEST_PHANTOM_BROWSER",
    ]
    missing = [k for k in required if k not in parsed]
    if missing:
        log.error("Manifest for v%s is missing required keys: %s",
                  version, missing)
        return None
    if parsed["PHANTOM_VERSION"] != version:
        log.error("Manifest version mismatch: asked for v%s, got v%s",
                  version, parsed["PHANTOM_VERSION"])
        return None
    return parsed


def _apply_manifest_to_env(manifest: dict[str, str]) -> None:
    """Mirror the phantom-installer's manifest-apply logic: strip stale
    PHANTOM_VERSION + DIGEST_PHANTOM_* lines from /host/.env, then
    append the core manifest as a clean block. Per-connector pins
    (DIGEST_PHANTOM_CONNECTOR_*) are not written to .env; they are
    rewritten as a unit into /host/connector-digests.env.

    The updater operates on the customer's install dir, bind-mounted
    read-write. Read-only mode is incompatible with this operation — see
    the note on the volume mount in installer/docker-compose.yml.
    """
    env_path = pathlib.Path(HOST_INSTALL_DIR) / ".env"
    if not env_path.is_file():
        raise RuntimeError(
            f"{env_path} not found — updater cannot apply manifest. "
            "Verify /host is mounted read-write in the updater compose service."
        )

    # Read existing content, strip stale lines.
    existing = env_path.read_text()
    kept_lines: list[str] = []
    for line in existing.splitlines():
        # Match the same patterns the installer strips: lines starting
        # with PHANTOM_VERSION= or DIGEST_PHANTOM_ (with the trailing _
        # ensuring we don't false-positive on PHANTOM_VERSION_<other>).
        if line.startswith("PHANTOM_VERSION="):
            continue
        if line.startswith("DIGEST_PHANTOM_"):
            continue
        kept_lines.append(line)

    # Trim trailing blank lines from the original (they'd accumulate
    # otherwise across repeat updates) and ensure exactly one
    # separator before the manifest block.
    while kept_lines and not kept_lines[-1].strip():
        kept_lines.pop()

    new_lines = list(kept_lines) + [
        "",
        f"# ─── Digest manifest (managed by phantom-updater "
        f"v{manifest['PHANTOM_VERSION']}) ──",
        "# DO NOT EDIT BY HAND. Re-running phantom-installer or the in-app "
        "updater",
        "# strips and rewrites these lines as a unit.",
    ]
    # Preserve a deterministic order for diff-readability.
    connector_prefix = "DIGEST_PHANTOM_CONNECTOR_"
    core_keys = ["PHANTOM_VERSION"] + sorted(
        k for k in manifest
        if k.startswith("DIGEST_PHANTOM_") and not k.startswith(connector_prefix)
    )
    for k in core_keys:
        if k in manifest:
            new_lines.append(f"{k}={manifest[k]}")

    new_lines.append("")  # trailing newline
    env_path.write_text("\n".join(new_lines))

    # Per-connector pins live in their own file, rewritten from scratch.
    connector_keys = sorted(k for k in manifest if k.startswith(connector_prefix))
    digests_path = pathlib.Path(HOST_INSTALL_DIR) / "connector-digests.env"
    digests_path.write_text(
        "\n".join(
            [
                "# Per-instance connector image pins (managed by phantom-updater "
                f"v{manifest['PHANTOM_VERSION']}).",
                "# DO NOT EDIT BY HAND. Re-running phantom-installer or the in-app "
                "updater",
                "# rewrites this file from the version-pinned manifest.",
                *(f"{k}={manifest[k]}" for k in connector_keys),
                "",
            ]
        )
    )
    # Invalidate the in-process caches so the next _running_phantom_version()
    # / _stack_digest() / _connector_digest() call sees the freshly-applied
    # values, not a stale cache hit.
    _invalidate_host_env_cache()
    _invalidate_host_connector_digests_cache()
    log.info("Applied manifest v%s to %s (%d core digests) and %s (%d connector digests)",
             manifest["PHANTOM_VERSION"], env_path,
             sum(1 for k in core_keys if k.startswith("DIGEST_PHANTOM_")),
             digests_path, len(connector_keys))


async def _pull_streaming(
    package: str, ref: str, service_name: str,
) -> AsyncGenerator[dict, None]:
    """
    Pull `<REGISTRY>/<OWNER>/<package>` at the given ref (a tag like
    "1.3.0" OR a digest like "sha256:abc...") and yield progress events
    suitable for SSE forwarding. Each event is a dict like:
      {
        "service": "phantom-agent",
        "package": "phantom-agent-oss",
        "ref": "sha256:abc..." or "1.3.0",
        "ref_kind": "digest" | "tag",
        "raw": {"status": "Downloading", "id": "abc123",
                "progressDetail": {"current": 12345, "total": 67890}},
      }

    Digest pulls use the `name@digest` form (set as repository,
    no tag arg). Tag pulls keep the existing (repository, tag) shape.
    docker-py's `client.api.pull()` accepts both — when the repository
    string contains `@`, the tag arg is ignored.

    docker-py's pull() returns a blocking generator of the dockerd
    pull-event JSON; we run it in a thread and bridge to asyncio via
    a queue so we don't block the event loop.
    """
    client = _docker_client()
    repository = f"{REGISTRY}/{OWNER}/{package}"
    is_digest = ref.startswith("sha256:")
    ref_kind = "digest" if is_digest else "tag"

    # docker-py's `pull(repository, tag)` builds the image reference as
    # `repository:tag` (or `repository@digest` if repository has `@`).
    # For digest pulls we pre-join into the repository arg; for tag
    # pulls we pass them separately.
    if is_digest:
        pull_repository = f"{repository}@{ref}"
        pull_tag = None
    else:
        pull_repository = repository
        pull_tag = ref

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    SENTINEL = object()

    def _producer():
        try:
            for event in client.api.pull(
                repository=pull_repository, tag=pull_tag,
                stream=True, decode=True,
            ):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait, {"error": str(e)},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

    loop.run_in_executor(None, _producer)

    while True:
        event = await queue.get()
        if event is SENTINEL:
            break
        yield {
            "service": service_name,
            "package": package,
            "ref": ref,
            "ref_kind": ref_kind,
            "raw": event,
        }


def _compose_base_args() -> list[str]:
    """Common flags shared by every compose subprocess we spawn."""
    return [
        "docker", "compose",
        # --project-name aligns with the project we're a member of so
        # compose recognizes the existing containers as ours. Without
        # this, compose derives the project from the compose-file
        # directory ("/host" inside us) and treats the running stack
        # as a different project, which then collides on container_name
        # pins. See _compose_project_name() for the full story.
        "--project-name", _compose_project_name(),
        "-f", f"{HOST_INSTALL_DIR}/docker-compose.yml",
        "--env-file", f"{HOST_INSTALL_DIR}/.env",
    ]


def _compose_up_services(services: list[str]) -> tuple[int, str]:
    """
    Run `docker compose ... up -d --no-deps <services>` in the host
    install dir. Returns (exitcode, combined_output).

    Used by the update flow (POST /api/v1/update) — `up -d` is the
    right verb there because that's where compose detects new image
    tags pulled by the updater and recreates the containers with
    them. For containers whose config didn't change, `up -d` is a
    no-op, which is what we want during an update.

    NOT the right verb for the restart endpoint — that needs to
    bounce the container even when nothing about its config has
    changed, so the entrypoint re-runs (re-reads operator-creds,
    re-templates configs, etc.). Use `_compose_restart_service` for
    that path.

    CRITICAL: never include 'phantom-updater' in `services` — that
    would recreate THIS container mid-update and kill the SSE stream
    we're feeding the UI. Compose only acts on the services listed.
    """
    if "phantom-updater" in services:
        raise ValueError("refusing to recreate self")
    cmd = _compose_base_args() + ["up", "-d", "--no-deps", *services]
    log.info("compose up: %s", " ".join(cmd))
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=180,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def _compose_restart_service(service: str) -> tuple[int, str]:
    """
    Run `docker compose ... restart <service>` in the host install dir.
    Returns (exitcode, combined_output).

    Used by the restart endpoint (POST /api/v1/services/{svc}/restart).
    `restart` (NOT `up -d`) is the right verb here: it kills the main
    process inside the existing container with SIGTERM and starts it
    back up, which means the image entrypoint runs again. That's what
    we need for services whose entrypoint re-templates config from a
    sidecar volume (caldera reads /operator-creds/caldera.yaml on
    every startup).

    `up -d --no-deps` would be a no-op here for an already-running
    healthy container — compose sees no config diff and exits 0 with
    "Container caldera Running". The endpoint would return 200 but
    nothing actually restarted (silent failure of the user's actual
    intent).

    CRITICAL: 'phantom-updater' is rejected upstream by the route
    handler — same reason as _compose_up_services.
    """
    cmd = _compose_base_args() + ["restart", service]
    log.info("compose restart: %s", " ".join(cmd))
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


async def _wait_healthy(service: str, timeout_s: int = HEALTHY_TIMEOUT_S) -> bool:
    """
    Poll the docker daemon until `service`'s container reports healthy
    (or `running` for containers without a healthcheck). Returns True
    on healthy, False on timeout.

    We deliberately re-fetch the container each iteration because
    `docker compose up -d` replaces it — the previous Container
    object's id becomes stale.
    """
    _, container_name = MANAGED_SERVICES[service]
    client = _docker_client()
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        try:
            c = client.containers.get(container_name)
            state = c.attrs.get("State") or {}
            health = (state.get("Health") or {}).get("Status")
            if health == "healthy":
                return True
            # Containers without healthchecks: accept "running".
            if health is None and state.get("Status") == "running":
                return True
        except NotFound:
            # Container was just torn down — keep polling for the
            # replacement to come up.
            pass
        await asyncio.sleep(2)
    return False


# ─── Lifespan ─────────────────────────────────────────────────────────


# How often the PERIODIC digest-drift reconcile runs. The startup
# reconcile only catches drift present at boot, but phantom-updater rarely
# restarts, so a connector pin that changes while it keeps running would
# not be reconciled into the running container until the next restart.
# A periodic loop closes that gap. Override via
# PHANTOM_UPDATER_RECONCILE_INTERVAL_S; default 5 minutes.
PERIODIC_RECONCILE_INTERVAL_S = float(
    os.environ.get("PHANTOM_UPDATER_RECONCILE_INTERVAL_S", "300")
)


async def _periodic_drift_reconcile(interval_s: float) -> None:
    """Run `_reconcile_connector_digest_drift()` forever on a timer.

    The startup reconcile only catches drift present at boot. This
    loop picks up pin changes that happen WHILE the updater keeps running
    (a dev-cycle install or an installer run that doesn't recreate the
    updater container), so running connector containers track their pinned
    digest without needing an updater restart. Same reconcile function,
    same safety (only recreates on digest mismatch); a failure in one tick
    is logged and the loop continues.
    """
    while True:
        await asyncio.sleep(interval_s)
        try:
            result = await _reconcile_connector_digest_drift()
            if result["recreated"] or result["failed"]:
                log.info(
                    "periodic digest-drift reconcile: drifted=%d recreated=%d "
                    "unchanged=%d failed=%d",
                    len(result["drifted"]), len(result["recreated"]),
                    len(result["unchanged"]), len(result["failed"]),
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("periodic digest-drift reconcile errored: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup tasks, including the digest-drift auto-reconcile.

    Sequence:
      1. Schedule an async digest-drift reconcile that fires ~30s
         after startup. Backgrounded because: (a) it does HTTP calls
         to ourselves + to the agent, which means we must be serving
         requests already; (b) the agent (which the recreate path
         calls back into for container_url tracking) takes 10-30s to
         come up after phantom-updater. The delay covers both.

    Why background rather than yield-wait: blocking startup on the
    drift reconcile would delay /healthz responses, which can fail
    docker-compose's healthcheck + cascade. Background-tasks fire
    asynchronously and any errors are logged + don't crash the
    process. Operators can call POST /api/v1/connectors/reconcile/digests
    if they want to wait for the result synchronously.
    """
    # Fire-and-forget digest-drift reconcile after a delay.
    # asyncio.create_task without awaiting lets us yield immediately.
    async def _delayed_drift_reconcile() -> None:
        try:
            await asyncio.sleep(30.0)  # let the agent finish booting
            log.info(
                "startup: running auto digest-drift reconcile",
            )
            result = await _reconcile_connector_digest_drift()
            log.info(
                "digest-drift reconcile finished: "
                "drifted=%d recreated=%d unchanged=%d failed=%d",
                len(result["drifted"]),
                len(result["recreated"]),
                len(result["unchanged"]),
                len(result["failed"]),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "startup digest-drift reconcile errored: %s",
                exc,
            )

    asyncio.create_task(_delayed_drift_reconcile())

    # Keep reconciling on a timer. The one-shot above
    # only catches drift present at boot; the updater rarely restarts, so
    # pin changes between restarts need a periodic sweep to land.
    asyncio.create_task(_periodic_drift_reconcile(PERIODIC_RECONCILE_INTERVAL_S))

    yield


app = FastAPI(
    lifespan=lifespan,
    title="phantom-updater",
    version="1.0.0",
    docs_url=None,        # no docs UI — internal API
    redoc_url=None,
    openapi_url=None,
)


# ─── Auth middleware ──────────────────────────────────────────────────


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Validate MCP_TOKEN bearer auth on every endpoint except /healthz."""
    if request.url.path == "/healthz":
        return await call_next(request)
    if not MCP_TOKEN:
        # Fail closed: never run unauthenticated even if the operator
        # forgot to set MCP_TOKEN. The compose default sets one.
        return JSONResponse(
            status_code=401,
            content={"detail": "MCP_TOKEN unset on updater; denying."},
        )
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse(
            status_code=401, content={"detail": "missing bearer token"},
        )
    if auth.removeprefix("Bearer ") != MCP_TOKEN:
        return JSONResponse(
            status_code=401, content={"detail": "invalid token"},
        )
    return await call_next(request)


# ─── Routes ───────────────────────────────────────────────────────────


@app.get("/healthz")
async def healthz():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/api/v1/version/current")
async def version_current():
    """Read currently-running image versions from the docker daemon."""
    try:
        return {svc: _current_version_for(svc) for svc in MANAGED_SERVICES}
    except DockerException as e:
        raise HTTPException(503, f"docker unavailable: {e}")


@app.get("/api/v1/version/check")
async def version_check():
    """
    Compare currently-running stack against the latest GitHub Release.

    Manifest-driven, not GHCR-tag-driven. Steps:
      1. Find the latest released version (highest `v*.*.*` tag with a
         GitHub Release). If we can't query GitHub, return None for
         latest and updates_available=False — the UI shows a graceful
         "couldn't reach GitHub" indicator instead of pretending we're
         current.
      2. If our running PHANTOM_VERSION already matches latest, we're
         up to date at the version level. We still report per-service
         digest comparisons so the UI can show "v1.2.0 → v1.2.0 (no
         change)" rather than just being silent.
      3. Otherwise, fetch the manifest for the latest version and
         compare each service's current digest vs. target digest.
         updates_available is true iff at least one service's digest
         differs.

    Returns:
      {
        running_version: str | None,
        latest_version: str | None,
        updates_available: bool,
        services: {
          svc: {current_version, current_digest, target_digest,
                update: bool, running: bool},
          ...
        },
        checked_at: ISO timestamp,
        error: str | None  (set if the GitHub query failed)
      }
    """
    running_version = _running_phantom_version()
    services: dict[str, dict] = {}

    latest_version = await _latest_release_version()
    if not latest_version:
        # Can't reach GitHub. Still return per-service current state
        # so the UI's diagnostics aren't blank.
        for svc in MANAGED_SERVICES:
            try:
                cur = _current_version_for(svc)
            except DockerException as e:
                log.error("docker error reading %s: %s", svc, e)
                cur = {"version": None, "digest": None, "running": False}
            services[svc] = {
                "current_version": cur.get("version"),
                "current_digest": cur.get("digest"),
                "target_digest": None,
                "update": False,
                "running": cur.get("running", False),
            }
        return {
            "running_version": running_version,
            "latest_version": None,
            "updates_available": False,
            "services": services,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": "could not reach GitHub Releases API",
        }

    # Got a latest version — fetch its manifest to compare digests.
    target_manifest: dict[str, str] | None = None
    if latest_version != running_version:
        target_manifest = await _fetch_release_manifest(latest_version)

    any_update = False
    for svc, (package, _) in MANAGED_SERVICES.items():
        try:
            cur = _current_version_for(svc)
        except DockerException as e:
            log.error("docker error reading %s: %s", svc, e)
            cur = {"version": None, "digest": None, "running": False}
        # Map service name to manifest env-var name.
        # phantom-agent → DIGEST_PHANTOM_AGENT, etc. (centralized
        # in `_stack_digest_env_var`.)
        env_var = _stack_digest_env_var(svc)
        target_digest = target_manifest.get(env_var) if target_manifest else None
        update = bool(
            target_digest and cur.get("digest") != target_digest
        )
        services[svc] = {
            "current_version": cur.get("version"),
            "current_digest": cur.get("digest"),
            "target_digest": target_digest,
            "update": update,
            "running": cur.get("running", False),
        }
        if update:
            any_update = True

    return {
        "running_version": running_version,
        "latest_version": latest_version,
        "updates_available": any_update,
        "services": services,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "error": None,
    }


@app.get("/api/v1/update/status")
async def update_status():
    """Whether an update is currently in progress on this updater."""
    return {"in_progress": _update_active}


def _sse(event: str, data: dict) -> bytes:
    """
    Format an SSE event. Each event MUST end with a blank line — that's
    how the SSE protocol delimits records. Newlines inside the JSON
    payload would also break the protocol; json.dumps escapes them.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


@app.post("/api/v1/update")
async def update_apply():
    """
    Trigger a manifest-driven update.

    Flow:
      1. Resolve target version from latest GitHub Release.
      2. Fetch release-manifest-vX.Y.Z.env from the GH Release.
      3. For each MANAGED_SERVICE, compare current digest vs target
         digest. If unchanged, skip (no recreate). Build to_update list.
      4. Pull each to-update image by digest (digest pulls are no-op
         when the digest is already in the local cache).
      5. Apply manifest to /host/.env (strip stale, append new).
      6. docker compose up -d --no-deps <to_update services>. Compose
         sees the new digests in .env, recreates only those services.
      7. Wait for healthy.

    Concurrent requests get rejected via _update_lock — only one
    update can run at a time per process.

    Event types streamed:
      phase           {phase: "checking" | "fetching_manifest" |
                       "comparing_digests" | "pulling" | "pulled" |
                       "applying_manifest" | "swapping" | "waiting_healthy" |
                       "complete" | "noop", service?, target?, target_version?}
      pull_progress   raw docker pull events with service/package/ref/ref_kind
      error           {phase, detail, ...}
    """
    global _update_active

    # Reject early so the client gets 409, not a stuck SSE stream.
    if _update_lock.locked():
        raise HTTPException(409, "update already in progress")

    async def stream() -> AsyncGenerator[bytes, None]:
        global _update_active
        async with _update_lock:
            _update_active = True
            try:
                # ── Phase 1: resolve target version. ─────────────────
                yield _sse("phase", {"phase": "checking"})
                target_version = await _latest_release_version()
                if not target_version:
                    yield _sse("error", {
                        "phase": "checking",
                        "detail": (
                            "could not reach GitHub Releases API. "
                            "Check network egress to api.github.com "
                            "(anonymous GitHub API calls are rate limited)."
                        ),
                    })
                    return

                running_version = _running_phantom_version()
                if running_version == target_version:
                    yield _sse("phase", {
                        "phase": "noop",
                        "message": (
                            f"already at v{running_version} (latest)"
                        ),
                    })
                    yield _sse("phase", {"phase": "complete"})
                    return

                # ── Phase 2: fetch + validate the manifest. ─────────
                yield _sse("phase", {
                    "phase": "fetching_manifest",
                    "target_version": target_version,
                })
                manifest = await _fetch_release_manifest(target_version)
                if not manifest:
                    yield _sse("error", {
                        "phase": "fetching_manifest",
                        "detail": (
                            f"failed to fetch or validate "
                            f"release-manifest-v{target_version}.env from "
                            f"GitHub Release. The asset may be missing or "
                            f"GitHub may be rate limiting this host."
                        ),
                    })
                    return

                # ── Phase 3: compare digests, decide what to update. ─
                yield _sse("phase", {
                    "phase": "comparing_digests",
                    "target_version": target_version,
                })
                to_update: list[tuple[str, str, str]] = []
                for svc, (package, _) in MANAGED_SERVICES.items():
                    cur = _current_version_for(svc)
                    env_var = _stack_digest_env_var(svc)
                    target_digest = manifest.get(env_var)
                    if target_digest and cur.get("digest") != target_digest:
                        to_update.append((svc, package, target_digest))

                if not to_update:
                    # PHANTOM_VERSION differs but no service's digest
                    # actually changed (e.g. the release pipeline retagged
                    # everything from the previous version with
                    # conditional rebuild). Apply the manifest anyway
                    # so .env reflects the new version label, but
                    # don't touch any container.
                    yield _sse("phase", {
                        "phase": "applying_manifest",
                        "target_version": target_version,
                        "note": "no digest changes; only version label updates",
                    })
                    _apply_manifest_to_env(manifest)
                    yield _sse("phase", {
                        "phase": "noop",
                        "message": (
                            f"v{running_version} → v{target_version}: "
                            "all service digests unchanged. .env updated, "
                            "containers not recreated."
                        ),
                    })
                    yield _sse("phase", {"phase": "complete"})
                    return

                # ── Phase 4: pull each changed image by digest. ──────
                for svc, package, target_digest in to_update:
                    yield _sse("phase", {
                        "phase": "pulling",
                        "service": svc,
                        "target": target_digest[:19] + "…",
                    })
                    async for ev in _pull_streaming(package, target_digest, svc):
                        yield _sse("pull_progress", ev)
                    yield _sse("phase", {
                        "phase": "pulled",
                        "service": svc,
                        "target": target_digest[:19] + "…",
                    })

                # ── Phase 5: apply the manifest to /host/.env. ───────
                # Done AFTER pulling so a pull failure leaves .env
                # intact (operators can retry without partial state).
                yield _sse("phase", {
                    "phase": "applying_manifest",
                    "target_version": target_version,
                })
                try:
                    _apply_manifest_to_env(manifest)
                except Exception as e:
                    yield _sse("error", {
                        "phase": "applying_manifest",
                        "detail": str(e),
                    })
                    return

                # ── Phase 6: swap services via `docker compose up -d`.
                # IMPORTANT ordering: MANAGED_SERVICES is intentionally
                # ordered (xlog first, caldera, phantom-agent last) so
                # phantom-agent's depends_on healthcheck sees its
                # dependencies up before it restarts. _compose_up_services
                # respects MANAGED_SERVICES iteration order.
                update_services = [s[0] for s in to_update]
                yield _sse("phase", {
                    "phase": "swapping",
                    "services": update_services,
                })
                rc, output = _compose_up_services(update_services)
                if rc != 0:
                    yield _sse("error", {
                        "phase": "swapping",
                        "exitcode": rc,
                        "detail": output[-2000:],
                    })
                    return

                # ── Phase 7: wait for each service to be healthy. ────
                for svc, _, _ in to_update:
                    yield _sse("phase", {
                        "phase": "waiting_healthy",
                        "service": svc,
                    })
                    healthy = await _wait_healthy(svc)
                    if not healthy:
                        yield _sse("error", {
                            "phase": "waiting_healthy",
                            "service": svc,
                            "detail": (
                                f"service {svc} did not become healthy "
                                f"within {HEALTHY_TIMEOUT_S}s"
                            ),
                        })
                        return

                yield _sse("phase", {
                    "phase": "complete",
                    "target_version": target_version,
                    "services_updated": update_services,
                })

            except Exception as e:
                # Any unhandled exception is a service-level bug. Log
                # the traceback for ops, surface a sanitized message
                # to the UI.
                log.exception("update failed")
                yield _sse("error", {"detail": str(e)})
            finally:
                _update_active = False

    # Headers chosen for SSE: text/event-stream, no buffering, keep
    # connection alive. Cache-Control:no-cache prevents intermediaries
    # from holding events. X-Accel-Buffering:no is for nginx (no-op
    # if no proxy is in front, which is our default).
    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/services/{service}/restart")
async def restart_service(service: str):
    """Restart a single managed service.

    Used by phantom-agent's /api/setup endpoint after writing operator
    creds to a shared volume — the target service (e.g. caldera) needs
    to come back up so its entrypoint re-templates its config from the
    new file.

    Calls `docker compose restart` (NOT `up -d`). The restart verb
    actually bounces the container — kills the main process with
    SIGTERM and starts it back up — so the image entrypoint runs
    again and re-reads the operator-creds bridge file. `up -d` would
    be a no-op for an already-running healthy container with
    unchanged config (silent failure of the user's actual intent).

    Refuses to act on phantom-updater (would kill self mid-call) and
    on services not in MANAGED_SERVICES (no need to expose arbitrary
    docker-compose action).
    """
    if service == "phantom-updater":
        return JSONResponse(
            status_code=400,
            content={"detail": "refusing to recreate self"},
        )
    if service not in MANAGED_SERVICES:
        return JSONResponse(
            status_code=404,
            content={
                "detail": f"unknown service {service!r}",
                "known": sorted(MANAGED_SERVICES.keys()),
            },
        )

    try:
        rc, output = _compose_restart_service(service)
    except Exception as exc:
        log.exception("restart failed for %s", service)
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
        )
    if rc != 0:
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"compose restart exited {rc}",
                "output": output[-2000:],
            },
        )
    return {"restarted": service, "output": output[-500:]}


# ─── Per-instance connector container lifecycle ────────────────────────
#
# Endpoints used by phantom-agent's /connectors UI (or future
# automation) to start/stop/restart per-instance connector
# containers (see docs/spec-per-instance-connector-containers.md).
#
# Naming convention (matches docs/spec-per-instance-connector-containers.md
# §D6):
#
#   container_name = f"phantom-connector-{connector_id}-{instance_name}"
#
#   image          = f"{REGISTRY}/{OWNER}/phantom-connector-{connector_id}-oss:{VERSION}"
#                    where VERSION defaults to PHANTOM_VERSION env var
#                    (= the running stack's version), falls back to
#                    "latest" if unset.
#
# After start/stop/restart, the endpoint POSTs back to the agent's
# MCP at PUT /api/v1/instances/{id}/container_url to update the
# routing entry the loader's container branch reads at tool-call time.

# Connectors that have a phantom-connector-<id> image published. Used
# to validate the connector_id path param. Mirrors the per-connector
# images the release pipeline publishes; when a new connector ships, add its
# id here.
#
# cortex-docs is module-style (style: "module" in connector.yaml), so
# per-instance container creation isn't exercised from here, but the
# image IS published so the digest manifest can pin it. A future
# container-mode flip is automatic once the style: "container" override
# is added; no additional code changes are needed beyond this set
# membership.
KNOWN_CONNECTORS = {
    "xlog",
    "xsiam",
    "caldera",
    "web",
    "cortex-docs",
    "cortex-content",
    # The agent's container-start path posts to phantom-updater's
    # /api/v1/connectors/<id>/instances/<name>/start, which validates
    # connector_id against THIS set. A connector missing here gets a 400
    # "unknown connector_id" → no container spawns → tool calls later
    # error with "container_url — phantom-updater hasn't started the
    # container yet, or the routing entry was deleted." The new-connector
    # checklist (bundles/spark/connectors/CLAUDE.md) lists THIS file as a
    # required edit.
    "cortex-xdr",
    # The senders the Cortex Analytics trigger skills call. They are
    # bundle connectors pinned by DIGEST_PHANTOM_CONNECTOR_HTTP_SENDER /
    # _WEC_SENDER.
    "http-sender",
    "wec-sender",
}


def _connector_package(connector_id: str) -> str:
    """GHCR package name for a bundled connector's image
    (`phantom-connector-<id>-oss`). The per-instance container is still
    named `phantom-connector-<id>-<instance>`; only the package carries
    the suffix."""
    return f"phantom-connector-{connector_id}{PACKAGE_SUFFIX}"


def _connector_image_ref(connector_id: str, version: str | None = None) -> str:
    """Compose the connector image ref using digest pinning.

    Resolution order:
      1. If `version` arg is set AND matches the running stack's
         PHANTOM_VERSION → use the corresponding DIGEST_PHANTOM_CONNECTOR_<ID>
         from /host/connector-digests.env (written by the installer).
         This is the typical happy path: operator creates a connector
         instance, agent passes no `version`, we pin to the running
         stack's manifest digest.
      2. If `version` arg is set AND differs from running PHANTOM_VERSION
         → unsupported (operator can't legitimately ask for a
         different version's digest because we don't have its manifest).
         Fall back to tag-pinning with a loud warning so the
         drift is observable in /observability/connectors.
      3. If connector-digests.env doesn't have the matching
         DIGEST_PHANTOM_CONNECTOR_<ID> entry → tag fallback with a loud
         warning.

    The function NEVER raises. Returns a usable image ref, with the
    warning logged in failure cases. The observability layer queries
    `image_pinning_for(connector_id)` (below) to surface the pinning
    mode in the connectors panel.
    """
    running_version = _running_phantom_version()
    requested_version = version or running_version

    # Happy path: requested version matches running stack version.
    # Use the digest from /host/connector-digests.env (not os.environ).
    if running_version and requested_version == running_version:
        env_var = _connector_digest_env_var(connector_id)
        digest = _connector_digest(connector_id)
        if digest and digest.startswith("sha256:"):
            return f"{REGISTRY}/{OWNER}/{_connector_package(connector_id)}@{digest}"
        log.warning(
            "%s missing or invalid in /host/connector-digests.env (got: %r); "
            "falling back to tag-pinning. This indicates the install is missing "
            "manifest-managed connector pins — re-run phantom-installer to refresh.",
            env_var, digest,
        )

    # Fallback: tag pinning. Logged loudly so the drift surfaces in
    # observability + structured-log searches. Operators should never
    # be in this path on a clean install.
    v = requested_version or "latest"
    log.warning(
        "Tag-pinning connector %s to v%s. Fallback path; "
        "the connector instance will be recreated on the next stack "
        "upgrade even if its image content didn't change.",
        connector_id, v,
    )
    return f"{REGISTRY}/{OWNER}/{_connector_package(connector_id)}:{v}"


def image_pinning_for(connector_id: str) -> dict:
    """Return {pinning: 'digest'|'tag', digest|tag: '...'} for the given
    connector_id. Used by the /observability/connectors panel to render
    a pinning-mode badge per connector instance.

    Sources from /host/connector-digests.env via the cached reader, not
    env vars. See the module-level "/host/.env reads" block for the
    rationale.
    """
    digest = _connector_digest(connector_id)
    if digest and digest.startswith("sha256:"):
        return {"pinning": "digest", "digest": digest}
    return {
        "pinning": "tag",
        "tag": _running_phantom_version() or "latest",
    }


def _connector_container_name(connector_id: str, instance_name: str) -> str:
    """Container name = phantom-connector-<id>-<instance_name>.

    Both segments are validated against [a-zA-Z0-9_-]+ at the
    endpoint surface so a malicious instance name can't break out
    into shell-meta territory. Operators have free rein over
    instance names within that character class.
    """
    return f"phantom-connector-{connector_id}-{instance_name}"


def _identify_connector_container(container) -> tuple[str, str, str] | None:
    """(connector_id, instance_name, instance_id) of a per-instance connector
    container, or None when it is not one of ours.

    Start stamps `phantom.connector_id` / `phantom.instance_name` /
    `phantom.instance_id`, so a hyphenated id (`cortex-xdr`) is read back
    exactly. Containers started by an older updater carry no labels; for those
    the name `phantom-connector-<id>-<instance>` is matched against the known
    ids, LONGEST FIRST. Splitting at the first hyphen reads
    `phantom-connector-cortex-xdr-X` as connector `cortex`.
    """
    labels = container.labels or {}
    connector_id = labels.get("phantom.connector_id")
    instance_name = labels.get("phantom.instance_name")
    if not (connector_id and instance_name):
        prefix = "phantom-connector-"
        rest = (container.name or "")[len(prefix):] if (container.name or "").startswith(prefix) else ""
        known = next(
            (k for k in sorted(KNOWN_CONNECTORS, key=len, reverse=True) if rest.startswith(k + "-")),
            None,
        )
        if known is None:
            return None
        connector_id, instance_name = known, rest[len(known) + 1:]
    instance_id = labels.get("phantom.instance_id") or ""
    if not instance_id:
        for pair in (container.attrs.get("Config") or {}).get("Env") or []:
            if pair.startswith("INSTANCE_ID="):
                instance_id = pair[len("INSTANCE_ID="):]
                break
    return connector_id, instance_name, instance_id


def _running_image_digest(container, connector_id: str, *, allow_foreign: bool = False) -> str | None:
    """sha256 digest of the image a connector container runs, or None.

    A digest is content-addressed, so it matches the pin whichever registry
    owner the image was pulled under (a container started with a different
    PHANTOM_OWNER must still be seen as drifted or current, never as
    digest-less). When the image object itself is gone
    (pruned while the container kept running) the digest in the container's
    own `Config.Image` ref is used. `allow_foreign` also accepts a RepoDigest
    of any other repository, for diagnostic display only.
    """
    try:
        repo_digests = container.image.attrs.get("RepoDigests") or []
    except NotFound:
        repo_digests = []
    repo = f"{_connector_package(connector_id)}@"
    for rd in repo_digests:
        if rd.startswith(f"{REGISTRY}/{OWNER}/{repo}"):
            return rd.split("@", 1)[1]
    for rd in repo_digests:
        if f"/{repo}" in rd:
            return rd.split("@", 1)[1]
    config_ref = (container.attrs.get("Config") or {}).get("Image") or ""
    if f"/{repo}" in config_ref and "@" in config_ref:
        return config_ref.split("@", 1)[1]
    if allow_foreign and repo_digests and "@" in repo_digests[0]:
        return repo_digests[0].split("@", 1)[1]
    return None


_REGISTRY_AUTH_FAILURE_RE = re.compile(
    r"\b(401|403)\b|denied|unauthori[sz]ed|forbidden|authentication required", re.IGNORECASE,
)


def _is_registry_auth_failure(exc: Exception) -> bool:
    """True when the registry refused the pull outright (401/403/denied).
    Retrying cannot help: the package is not public, or the name is wrong."""
    return getattr(exc, "status_code", None) in (401, 403) or bool(_REGISTRY_AUTH_FAILURE_RE.search(str(exc)))


def _ensure_managed_connector_container(container, connector_id: str) -> None:
    """Refuse to act on a container that is not a managed connector container
    for `connector_id` (HTTP 409).

    stop / status / restart name a container through path segments that are
    already validated against [a-zA-Z0-9_-]+, so the only way to reach the wrong
    container is a name collision with something that is not ours. Ownership is
    decided by the container's own labels (what `start` stamps), NOT by the
    bundle-only KNOWN_CONNECTORS list: an uploaded connector is as managed as a
    bundled one, and gating on that list would make DELETE leave an uploaded
    connector's container running. Containers started by an older updater
    carry no labels; those are matched by name against the known bundle ids,
    which is the trust the updater always had for them.
    """
    labels = container.labels or {}
    if labels.get("phantom.role"):
        managed = (
            labels.get("phantom.role") == "connector-runtime"
            and labels.get("phantom.connector_id") == connector_id
        )
    else:
        ident = _identify_connector_container(container)
        managed = ident is not None and ident[0] == connector_id
    if not managed:
        raise HTTPException(
            409,
            f"container {container.name!r} is not a managed {connector_id!r} "
            "connector container; refusing to touch it",
        )


def _compose_network_name() -> str:
    """The compose default network name = `<project>_default`. The
    connector container needs to attach to this network so the agent
    (also on it) can reach the connector at <container-name>:9000."""
    return f"{_compose_project_name()}_default"


def _compose_data_volume_name() -> str:
    """Volume holding instance_store.db + secrets/. The connector
    container mounts this read-only at /app/data so the runtime
    entrypoint can resolve INSTANCE_ID → config + secrets."""
    return f"{_compose_project_name()}_phantom_mcp_data"


@dataclass(frozen=True)
class PullOutcome:
    """How an image became available. `status` is "pulled" (fresh from the
    registry) or "cached" (the pull failed, the local copy was used); `error`
    says why the pull failed and is only set when `status == "cached"`."""

    status: str
    error: str | None = None


def _pull_with_retry(
    client: docker.DockerClient,
    image: str,
    *,
    max_attempts: int = 5,
    base_delay_s: float = 1.0,
    max_delay_s: float = 30.0,
) -> PullOutcome:
    """Pull a connector image with exponential backoff.

    Returns a PullOutcome whose status is one of:
      "pulled"           — fresh pull from registry succeeded
      "cached"           — pull failed but image is in local cache
                           (offline-deploy success path); `error` says why

    Raises HTTPException(502) when:
      - Pull failed AND image not in local cache (no way to start
        the container)
      - All retry attempts exhausted on a transient error

    Why retry: Phantom customers run on-prem with variable network
    quality (corporate proxies, slow VPNs). A single transient
    DNS / TLS / connection-reset error during `docker pull`
    shouldn't fail the whole start endpoint. The exponential
    backoff (1s → 2s → 4s → 8s → 16s, capped at 30s) gives ~30s
    of total recovery window, then bails.

    Why fall through to local cache: customers may run with the
    registry temporarily unreachable (firewall change, registry
    outage). If the image was previously pulled, the start should
    still work — that's the customer's "we're offline today, but
    we already have what we need" scenario. Surface this to the
    operator via the return value so audit logs show "cached"
    when the registry was down.

    Why not retry forever: if the registry is genuinely
    unreachable AND the image isn't local, no amount of retrying
    helps. Bail at max_attempts so the operator gets a fast,
    actionable error instead of a 5-minute hang.
    """
    import time as _time

    last_exc: Exception | None = None
    delay = base_delay_s
    auth_failure = False
    for attempt in range(1, max_attempts + 1):
        try:
            client.images.pull(image)
            log.info("pulled image %s (attempt %d)", image, attempt)
            return PullOutcome("pulled")
        except DockerException as exc:
            last_exc = exc
            log.warning(
                "image pull attempt %d/%d failed for %s: %s",
                attempt, max_attempts, image, exc,
            )
            # A refused credential is not transient: retrying only burns
            # ~30s and then hides the cause behind a "cached" success.
            # Say what is wrong, once, and stop.
            if _is_registry_auth_failure(exc):
                auth_failure = True
                log.error(
                    "registry denied the pull of %s: the package is not public "
                    "or the image name is wrong. Not retrying. (%s)",
                    image, exc,
                )
                break
            # Last attempt — fall through to cache check below
            if attempt == max_attempts:
                break
            _time.sleep(delay)
            delay = min(delay * 2, max_delay_s)

    reason = (
        f"registry denied access (is the package public?): {last_exc}"
        if auth_failure
        else f"registry unreachable after {max_attempts} attempts: {last_exc}"
    )
    # Retries exhausted (or not worth making). Check local cache as a last resort.
    try:
        client.images.get(image)
        log.warning("image %s started from the local cache: %s", image, reason)
        return PullOutcome("cached", reason[:300])
    except NotFound:
        raise HTTPException(
            502, f"image {image!r} not in local cache and {reason}",
        ) from last_exc


async def _agent_set_container_url(
    instance_id: str, container_url: str | None,
) -> None:
    """Call back to the agent's MCP to update the routing entry.

    This is the contract: phantom-updater starts/stops the container,
    then notifies the agent. The agent's MCP set_container_url
    endpoint (api/instances.py) updates the row; the connector_loader's
    container branch reads it via merged_config()→contextvar at the
    next tool call.

    Best-effort — failures here log a WARNING but don't fail the
    start/stop call. Reason: the container is up (or down); the
    routing entry is a downstream concern that an agent restart or
    a follow-up sync would correct. Hard-failing the start endpoint
    on a transient agent-MCP unreachable would be worse UX than
    succeeding with a warning.
    """
    # TLS-aware default: the agent runs behind a TLS proxy on port 8080.
    agent_url = _resolve_agent_internal_url()
    url = f"{agent_url}/api/v1/instances/{instance_id}/container_url"
    headers = {"Content-Type": "application/json"}
    if MCP_TOKEN:
        headers["Authorization"] = f"Bearer {MCP_TOKEN}"
    body = {"container_url": container_url}
    # Use the centralized helper. Default compose-internal
    # URL has a self-signed cert; verify=False is the architecturally
    # correct setting (trust boundary = docker network alias, not
    # cert chain). Operator override paths can opt in via
    # PHANTOM_TLS_VERIFY=1.
    verify_tls = _agent_tls_verify()
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=verify_tls) as client:
            resp = await client.put(url, json=body, headers=headers)
        if resp.status_code >= 300:
            log.warning(
                "agent set_container_url returned %d for instance %s "
                "(body=%.200s)",
                resp.status_code, instance_id, resp.text,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "could not notify agent of container_url change for instance %s: %s",
            instance_id, exc,
        )


def _normalize_instance_name(name: str) -> str:
    """Normalize an operator-supplied instance name to a docker-safe
    form.

    Operators routinely create instances with names like "Cortex XDR"
    or "Cortex Docs Search" — spaces are valid in the agent's UI and
    in the underlying instances.db. But docker container names can't
    contain spaces, so we normalize whitespace → underscore at every
    use site that constructs a container name.

    Every endpoint that takes an instance name (reconcile, start,
    restart, stop) must normalize it: the agent's database holds the RAW
    name "Cortex XDR", which `_validate_path_segments` would otherwise
    reject with "invalid path segment 'Cortex XDR'; allowed: A-Z, a-z,
    0-9, _, -", leaving instances with spaces in their names unmanageable.

    The normalization is conservative:
      - Whitespace → "_" (so "Cortex XDR" → "Cortex_XDR")
      - Other chars left alone (validator catches them after)

    Idempotent — re-applying produces the same string.
    """
    return re.sub(r"\s+", "_", name)


def _validate_path_segments(*parts: str) -> None:
    """Defense-in-depth: connector_id + instance_name come from URL
    path. FastAPI's path-param parsing is permissive; we explicitly
    validate against shell-meta and dangerous chars before passing
    them into Docker container names.

    Callers should pass instance_name already normalized via
    `_normalize_instance_name` so this validation accepts the
    docker-safe form (spaces have been replaced with underscores by
    that point).
    """
    safe = re.compile(r"^[a-zA-Z0-9_-]+$")
    for p in parts:
        if not safe.match(p):
            raise HTTPException(
                400, f"invalid path segment {p!r}; allowed: A-Z, a-z, 0-9, _, -",
            )


@app.post("/api/v1/connectors/{connector_id}/instances/{instance_name}/start")
async def start_connector_instance(
    connector_id: str, instance_name: str, request: Request,
):
    """Start a per-instance connector container.

    Body (JSON):
        instance_id: str    — the agent's instance row id (UUID)
        version:     str?   — optional image version override
                              (defaults to PHANTOM_VERSION)

    The endpoint:
      1. Validates connector_id is known + path segments are safe.
      2. Removes any existing container with the same name (so
         start is idempotent / equivalent to recreate).
      3. Pulls the image (best-effort — falls back to local cache
         if registry is unreachable; see the retry logic below).
      4. Starts the container, attached to the compose default
         network with the data volume mounted read-only.
      5. POSTs back to the agent's MCP to populate the
         container_url routing entry.
    """
    # Normalize spaces in operator-supplied names BEFORE
    # validation so the start endpoint can manage instances named
    # like "Cortex XDR" (spaces). Container names use underscore;
    # operator UI accepts spaces. See _normalize_instance_name docstring.
    instance_name = _normalize_instance_name(instance_name)
    _validate_path_segments(connector_id, instance_name)

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    instance_id = body.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id.strip():
        raise HTTPException(400, "instance_id (string) required in body")

    # Explicit image_ref support for user-uploaded connectors.
    # The agent's instances.py reads `image:` from connector.yaml (which
    # is required for user uploads, optional for bundle) and passes it
    # through here. When present, skips KNOWN_CONNECTORS gating + the
    # derivation path; uses the explicit ref directly. Bundle connectors
    # leave it empty and fall through to derivation as before.
    explicit_image = body.get("image_ref")
    if isinstance(explicit_image, str) and explicit_image.strip():
        image = explicit_image.strip()
    else:
        if connector_id not in KNOWN_CONNECTORS:
            raise HTTPException(
                400,
                f"unknown connector_id {connector_id!r}; "
                f"allowed bundle ids: {sorted(KNOWN_CONNECTORS)}. "
                f"For user-uploaded connectors, pass image_ref in the "
                f"body — see api/marketplace.py upload route.",
            )
        image = _connector_image_ref(connector_id, body.get("version"))
    container_name = _connector_container_name(connector_id, instance_name)

    client = _docker_client()

    # Remove any existing container with the same name (idempotent
    # restart). The Docker SDK raises NotFound if none exists; that's
    # the happy first-time-start case.
    try:
        existing = client.containers.get(container_name)
        log.info("removing existing container %s before start", container_name)
        try:
            existing.stop(timeout=10)
        except DockerException:
            pass
        existing.remove(force=True)
    except NotFound:
        pass

    # Pull image with exponential backoff. Returns "pulled"
    # on fresh pull success or "cached" when the registry was
    # unreachable but a previous pull still lives in local cache
    # (offline-deploy recovery path). Raises HTTPException(502) when
    # both fail.
    pull = _pull_with_retry(client, image)
    pull_status = pull.status

    # Start the container. Env wiring + volume mount + network
    # attach mirrors what phantom-agent + xlog + phantom-browser
    # already do in customer compose.
    try:
        container = client.containers.run(
            image,
            name=container_name,
            environment={
                "CONNECTOR_ID": connector_id,
                "INSTANCE_ID": instance_id,
                "PORT": "9000",
                "DATA_ROOT": "/app/data",
                # Read PHANTOM_SECRET_KEK from /host/.env (same pattern
                # as PHANTOM_VERSION / DIGEST_PHANTOM_* reads), NOT
                # os.environ: the customer compose's `environment:`
                # block INTENTIONALLY doesn't pass it (docker-compose
                # env-stability invariant: any env block change forces
                # a phantom-updater container recreate on stack
                # upgrade, defeating the digest-pinning preservation).
                # An os.environ read would start connector containers
                # with an EMPTY PHANTOM_SECRET_KEK → the connector-
                # runtime's SecretStoreReader.read() fails with
                # "PHANTOM_SECRET_KEK is not set" → instance.secret_refs
                # all resolve to empty string → connectors error at
                # first tool call with "no apiKey configured."
                "PHANTOM_SECRET_KEK": _host_env_get("PHANTOM_SECRET_KEK", "") or "",
                # TLS-aware default (https://phantom-agent:8080); a
                # plain-http URL makes the connector-container process
                # fail to write audit rows because the agent is behind
                # a TLS proxy.
                "PHANTOM_AUDIT_URL": os.environ.get(
                    "PHANTOM_AUDIT_URL",
                    f"{_resolve_agent_internal_url()}/api/v1/audit",
                ),
                "MCP_TOKEN": MCP_TOKEN,
                "LOG_LEVEL": os.environ.get("LOG_LEVEL", "INFO"),
            },
            volumes={
                _compose_data_volume_name(): {
                    "bind": "/app/data",
                    "mode": "ro",
                },
            },
            network=_compose_network_name(),
            restart_policy={"Name": "unless-stopped"},
            detach=True,
            labels={
                # Tag with the compose project so the agent's UI can
                # filter "containers we manage" vs operator-side
                # containers running on the same host.
                "com.docker.compose.project": _compose_project_name(),
                "phantom.connector_id": connector_id,
                "phantom.instance_id": instance_id,
                "phantom.instance_name": instance_name,
                "phantom.role": "connector-runtime",
                # "pulled" | "cached". Read back by GET /connectors/digests so
                # /observability/connectors can flag a container that started
                # from a stale local copy because the registry pull failed.
                "phantom.image_pull": pull_status,
            },
        )
    except DockerException as exc:
        log.exception("container start failed for %s", container_name)
        raise HTTPException(500, f"container start failed: {exc}") from exc

    # Build the URL the agent's loader will use to reach this container.
    # Compose-network DNS resolves <container_name> to the right IP.
    container_url = f"http://{container_name}:9000"

    # Notify agent of the routing entry. Best-effort.
    await _agent_set_container_url(instance_id, container_url)

    log.info(
        "started connector container: %s (instance_id=%s, image=%s)",
        container_name, instance_id, image,
    )

    return {
        "container_id": container.id,
        "container_name": container_name,
        "container_url": container_url,
        "image": image,
        "image_pull": pull_status,  # "pulled" | "cached"
        # Why the registry pull failed; present only when image_pull == "cached".
        **({"image_pull_error": pull.error} if pull.error else {}),
        "status": "started",
    }


@app.post("/api/v1/connectors/{connector_id}/instances/{instance_name}/stop")
async def stop_connector_instance(connector_id: str, instance_name: str):
    """Stop + remove a per-instance connector container. Also clears
    the agent's routing entry."""
    # Normalize spaces in operator-supplied names BEFORE
    # validation so reconcile/start/stop/restart can manage instances
    # named like "Cortex XDR" (spaces). Container names use underscore;
    # operator UI accepts spaces. See _normalize_instance_name docstring.
    instance_name = _normalize_instance_name(instance_name)
    _validate_path_segments(connector_id, instance_name)

    container_name = _connector_container_name(connector_id, instance_name)
    client = _docker_client()

    # Best-effort: extract instance_id from labels BEFORE we kill the
    # container, so we can still notify the agent even if the operator
    # doesn't pass instance_id in the body.
    instance_id: str | None = None
    try:
        existing = client.containers.get(container_name)
    except NotFound:
        return {"status": "not_running", "container_name": container_name}
    _ensure_managed_connector_container(existing, connector_id)
    instance_id = existing.labels.get("phantom.instance_id")

    try:
        existing.stop(timeout=10)
        existing.remove(force=True)
    except DockerException as exc:
        log.exception("stop failed for %s", container_name)
        raise HTTPException(500, f"stop failed: {exc}") from exc

    if instance_id:
        await _agent_set_container_url(instance_id, None)

    log.info("stopped connector container: %s", container_name)
    return {"status": "stopped", "container_name": container_name}


@app.get("/api/v1/connectors/{connector_id}/instances/{instance_name}/status")
async def status_connector_instance(connector_id: str, instance_name: str):
    """Return Docker-side status for a per-instance connector
    container. Used by the /connectors UI's per-instance status
    badge + by phantom-updater's own readiness checks."""
    # Normalize spaces in operator-supplied names BEFORE
    # validation so reconcile/start/stop/restart can manage instances
    # named like "Cortex XDR" (spaces). Container names use underscore;
    # operator UI accepts spaces. See _normalize_instance_name docstring.
    instance_name = _normalize_instance_name(instance_name)
    _validate_path_segments(connector_id, instance_name)

    container_name = _connector_container_name(connector_id, instance_name)
    client = _docker_client()

    try:
        container = client.containers.get(container_name)
    except NotFound:
        return {
            "container_name": container_name,
            "status": "not_running",
            "container_url": None,
        }
    _ensure_managed_connector_container(container, connector_id)

    # Map docker container Status field to a small set of values the
    # agent UI cares about. Docker reports: created, restarting,
    # running, removing, paused, exited, dead.
    docker_status = (container.status or "").lower()
    health = None
    try:
        health = container.attrs.get("State", {}).get("Health", {}).get("Status")
    except Exception:  # noqa: BLE001
        pass

    if docker_status == "running":
        ui_status = "healthy" if health in ("healthy", None) else (
            "unhealthy" if health == "unhealthy" else "starting"
        )
    elif docker_status in ("restarting", "created"):
        ui_status = "starting"
    else:
        ui_status = "stopped"

    return {
        "container_name": container_name,
        "container_id": container.id,
        "status": ui_status,
        "docker_status": docker_status,
        "health": health,
        "restart_count": container.attrs.get("RestartCount", 0),
        "container_url": f"http://{container_name}:9000",
        "image": (container.image.tags or [container.image.id])[0],
    }


@app.get("/api/v1/connectors/digests")
async def list_connector_digests():
    """Return image-pinning info for every per-instance connector
    container managed by this updater.

    Used by the agent's /api/agent/digests proxy to populate
    the /observability/connectors panel's digest column. Each row
    reflects the actual running container's image (via docker inspect),
    not what the manifest says SHOULD be running. The two normally
    agree, but a divergence (e.g. operator manually swapped an image
    via `docker run`) is operationally interesting and worth surfacing.

    Returns:
      {connectors: [
        {connector_id, instance_id, instance_name, digest, pinned_digest,
         drift, image_pull: 'pulled' | 'cached' | null,
         pinning_mode: 'digest' | 'tag', image_ref},
        ...
      ]}

    `digest` is null when the container is in tag-pinning fallback
    mode (DIGEST_PHANTOM_CONNECTOR_<ID> missing from connector-digests.env) or
    when the container isn't running.
    """
    client = _docker_client()
    rows: list[dict] = []

    # Every per-instance connector container, bundle or uploaded. One container
    # that cannot be read (its image pruned, a daemon hiccup) must not take the
    # whole listing down, so each is handled on its own.
    for container in client.containers.list(
        all=True, filters={"name": "phantom-connector-"}
    ):
        try:
            ident = _identify_connector_container(container)
            if ident is None:
                # Not one of ours (a stray container with the name prefix).
                continue
            connector_id, instance_name, instance_id = ident

            running_digest = _running_image_digest(container, connector_id, allow_foreign=True)
            pinned_digest = _connector_digest(connector_id)
            # Pinning mode: digest if the env var IS set AND matches the
            # running digest; tag otherwise. The image_pinning_for()
            # helper consults the same env var the container was started
            # with — so as long as the operator didn't manually swap, the
            # two agree.
            pinning = image_pinning_for(connector_id)
            try:
                image_ref = (container.image.tags or [container.image.id])[0] or ""
            except NotFound:
                image_ref = (container.attrs.get("Config") or {}).get("Image") or ""

            rows.append({
                "connector_id": connector_id,
                "instance_id": instance_id,
                "instance_name": instance_name,
                "digest": running_digest,
                "pinned_digest": pinned_digest,
                # The running image is not the one the install pins: the
                # container is stale and the drift reconcile has not (yet)
                # recreated it.
                "drift": bool(pinned_digest and running_digest and pinned_digest != running_digest),
                # "pulled" | "cached" | None (container predates the label).
                # "cached" = the registry pull failed and the local copy ran.
                "image_pull": (container.labels or {}).get("phantom.image_pull"),
                "pinning_mode": pinning["pinning"],
                "image_ref": image_ref,
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("digests: skipping %s: %s", container.name, exc)

    return {"connectors": rows}


async def _reconcile_connector_digest_drift() -> dict:
    """Recreate per-instance connector containers whose
    running image digest doesn't match the pinned digest in
    /host/connector-digests.env.

    Why this exists:
    Per-instance connector containers are spawned by phantom-updater
    when the operator first creates an instance via /connectors. After
    that, they stick around — docker-compose's `up -d` doesn't touch
    them because they're not in docker-compose.yml (they're managed
    dynamically by phantom-updater per-instance). Every dev-cycle
    install updates /host/connector-digests.env with new pinned
    digests, but the existing per-instance containers KEEP RUNNING the
    image digest they were originally spawned with. The operator's
    chat tests would then exercise STALE connector code while the agent
    itself is current.

    phantom-updater therefore detects digest drift on startup, on a
    timer, and via this endpoint, and recreates the divergent containers
    automatically. The recreate goes through start_connector_instance
    which already handles the lifecycle (stop+remove existing, pull
    new image, spawn new container, callback agent with the URL).

    Safety:
      - Only recreates when running digest != pinned digest. Fresh
        installs (no prior containers) skip; matched-digest containers
        skip.
      - Sequential, not parallel — one connector at a time so we
        don't thrash the docker daemon or the agent's callback path.
      - Errors per-container are logged + included in the response
        but don't abort the loop.

    Returns: {drifted: [...], recreated: [...], unchanged: [...], failed: [...]}.
    """
    import httpx as _httpx  # noqa: PLC0415
    summary: dict[str, list] = {
        "drifted": [],
        "recreated": [],
        "unchanged": [],
        "failed": [],
    }

    client = _docker_client()
    try:
        containers = client.containers.list(
            all=False, filters={"name": "phantom-connector-"},
        )
    except DockerException as exc:
        log.warning("digest-drift reconcile: docker list failed: %s", exc)
        return summary

    # Need to call start_connector_instance via HTTP to reuse its
    # complete lifecycle (stop + remove + pull + start + agent callback).
    # Self-loopback via localhost:8090 — same port the agent uses.
    self_url = "http://127.0.0.1:8090"
    headers = {"Authorization": f"Bearer {MCP_TOKEN}"} if MCP_TOKEN else {}

    for container in containers:
        name = container.name or ""
        # Each container is judged on its own: one that cannot be read (its
        # image pruned) must not stop the sweep before it reaches the rest.
        try:
            ident = _identify_connector_container(container)
            if ident is None:
                continue
            connector_id, instance_name, instance_id = ident

            # The pin is read from /host/connector-digests.env. An uploaded
            # connector has none, which is what makes it "unchanged" below.
            pinned = _connector_digest(connector_id)
            if not pinned:
                # No pinning configured — operator running in tag-mode, or a
                # user connector. Skip.
                summary["unchanged"].append({
                    "container": name,
                    "reason": "no pinned digest",
                })
                continue

            running_digest = _running_image_digest(container, connector_id)
            if running_digest is None:
                # Never report "unchanged" for a container we could not
                # measure: that is exactly how stale containers hid.
                summary["failed"].append({
                    "container": name,
                    "reason": "cannot determine the running image digest",
                })
                continue

            if running_digest == pinned:
                summary["unchanged"].append({
                    "container": name,
                    "digest": running_digest[:19] + "...",
                })
                continue

            # Drift detected. Need the instance_id to call start.
            if not instance_id:
                log.warning(
                    "digest-drift: %s drifted but has no INSTANCE_ID label; "
                    "skipping recreate (would need agent-side instance lookup)",
                    name,
                )
                summary["failed"].append({
                    "container": name,
                    "reason": "no INSTANCE_ID label — can't safely recreate",
                })
                continue

            drifted_entry = {
                "container": name,
                "connector_id": connector_id,
                "instance_name": instance_name,
                "instance_id": instance_id,
                "running_digest": running_digest[:19] + "...",
                "pinned_digest": pinned[:19] + "...",
            }
            summary["drifted"].append(drifted_entry)

            log.info(
                "digest-drift: %s running=%s pinned=%s — recreating",
                name, running_digest[:19], pinned[:19],
            )
            try:
                async with _httpx.AsyncClient(timeout=_httpx.Timeout(60.0)) as http:
                    resp = await http.post(
                        f"{self_url}/api/v1/connectors/{connector_id}/"
                        f"instances/{instance_name}/start",
                        headers=headers,
                        json={"instance_id": instance_id},
                    )
                if resp.status_code < 300:
                    summary["recreated"].append({**drifted_entry,
                                                  "response": resp.json()})
                else:
                    summary["failed"].append({
                        **drifted_entry,
                        "status_code": resp.status_code,
                        "body": resp.text[:200],
                    })
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "digest-drift: recreate of %s failed: %s", name, exc,
                )
                summary["failed"].append({**drifted_entry, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            log.warning("digest-drift: could not examine %s: %s", name, exc)
            summary["failed"].append({"container": name, "error": f"{type(exc).__name__}: {exc}"})

    return summary


@app.post("/api/v1/connectors/reconcile/digests")
async def reconcile_connector_digest_drift_endpoint():
    """Operator-callable digest-drift reconcile.

    Same logic as the startup-time auto-reconcile, exposed as an
    endpoint for manual trigger when the operator notices a
    connector container is running stale code (e.g. behavior doesn't
    match a recent release's CHANGELOG entry).
    """
    return await _reconcile_connector_digest_drift()


@app.post("/api/v1/connectors/reconcile")
async def reconcile_connector_containers():
    """Ensure every container-style instance has a running container.

    Entry point for the upgrade path: an instance created while its
    connector ran in-process has no container once the connector's
    connector.yaml is style: container. The connector_loader's
    container branch would error with "container_url not set" on
    every tool call until something starts a container.

    This endpoint:
      1. Queries the agent's /api/v1/instances for the full list
         of instances.
      2. For each instance whose connector has style: container in
         its connector.yaml AND no container_url set, calls the
         start endpoint.
      3. Returns a summary of {reconciled: [...], skipped: [...],
         failed: [...]}.

    Idempotent — safe to call repeatedly. Operators (or boot-time
    agent reconciliation) can call this without checking state
    first.

    Auth: same MCP_TOKEN bearer as the rest of /api/v1.

    Body: optional {}; no input parameters today. Future versions
    might accept a connector_id filter.
    """
    # TLS-aware default: the agent runs behind a TLS proxy on port 8080.
    agent_url = _resolve_agent_internal_url()
    headers = {"Authorization": f"Bearer {MCP_TOKEN}"} if MCP_TOKEN else {}

    # Use the centralized helper. Default compose-internal
    # URL has a self-signed cert; verify=False is the architecturally
    # correct setting.
    verify_tls = _agent_tls_verify()

    # Query agent for all instances + each connector's runtime style.
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), verify=verify_tls) as client:
            instances_resp = await client.get(
                f"{agent_url}/api/v1/instances", headers=headers,
            )
        if instances_resp.status_code >= 300:
            raise HTTPException(
                502,
                f"agent /api/v1/instances returned {instances_resp.status_code}: "
                f"{instances_resp.text[:200]}",
            )
        instances = instances_resp.json().get("instances") or []
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            502, f"could not list instances from agent: {exc}",
        ) from exc

    # Cache connector.yaml lookups since multiple instances may share
    # the same connector_id. We CAN'T read connector.yaml directly
    # from this container (the bundle isn't mounted here), so we ask
    # the agent for the runtime style. Fastest path: /api/v1/marketplace
    # endpoint OR a small /api/v1/connectors/<id>/style endpoint.
    # Phase 1 simplification: try a HEAD request to the agent's
    # set_container_url endpoint — if the connector is container-style,
    # the agent's loader will accept the call. Otherwise just trust
    # the per-instance container_url field — if it's NULL and the
    # connector_id is one we have a phantom-connector-<id> image for,
    # we attempt the start.

    reconciled: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []

    for inst in instances:
        cid = inst.get("connector_id")
        name = inst.get("name")
        iid = inst.get("id")
        existing_url = inst.get("container_url")

        if cid not in KNOWN_CONNECTORS:
            # Deliberate: this sweep starts MISSING containers and has to
            # derive the image from the pinned digest. An uploaded connector has
            # no pin and the updater does not know its image; the agent starts
            # those itself, passing image_ref. (stop/status/restart act on an
            # existing container and do not need this list.)
            skipped.append({
                "connector_id": cid, "instance_name": name,
                "reason": "connector_id not in KNOWN_CONNECTORS",
            })
            continue

        if existing_url:
            # Already has a container_url — try to verify the container
            # is actually running. If it is, skip; if not, try start.
            container_name = _connector_container_name(cid, name)
            try:
                client = _docker_client()
                ctn = client.containers.get(container_name)
                if (ctn.status or "").lower() == "running":
                    skipped.append({
                        "connector_id": cid, "instance_name": name,
                        "reason": "already running with container_url",
                    })
                    continue
            except NotFound:
                # container_url set but no container — fall through to start.
                log.info(
                    "instance %s/%s has stale container_url (no container); "
                    "reconciling by starting fresh",
                    cid, name,
                )

        # Call our own start endpoint. Reuses all the validation +
        # image-pull-with-retry + lifecycle logic.
        class _StubReq:
            async def json(self):
                return {"instance_id": iid}

        try:
            result = await start_connector_instance(cid, name, _StubReq())
            reconciled.append({
                "connector_id": cid,
                "instance_name": name,
                "instance_id": iid,
                "container_url": result.get("container_url"),
                "image_pull": result.get("image_pull"),
            })
        except HTTPException as exc:
            failed.append({
                "connector_id": cid,
                "instance_name": name,
                "instance_id": iid,
                "error": f"HTTP {exc.status_code}: {exc.detail}",
            })
        except Exception as exc:  # noqa: BLE001
            failed.append({
                "connector_id": cid,
                "instance_name": name,
                "instance_id": iid,
                "error": str(exc),
            })

    log.info(
        "reconcile complete: reconciled=%d skipped=%d failed=%d",
        len(reconciled), len(skipped), len(failed),
    )
    return {
        "reconciled": reconciled,
        "skipped": skipped,
        "failed": failed,
        "total_instances": len(instances),
    }


@app.post("/api/v1/connectors/{connector_id}/instances/{instance_name}/restart")
async def restart_connector_instance(
    connector_id: str, instance_name: str, request: Request,
):
    """Restart a per-instance connector container. Internally:
    stop → start. The image version is preserved (re-read from the
    existing container's labels) unless overridden in the body —
    this is the typical "kick the container after wedge" path."""
    # Normalize spaces in operator-supplied names BEFORE
    # validation so reconcile/start/stop/restart can manage instances
    # named like "Cortex XDR" (spaces). Container names use underscore;
    # operator UI accepts spaces. See _normalize_instance_name docstring.
    instance_name = _normalize_instance_name(instance_name)
    _validate_path_segments(connector_id, instance_name)

    container_name = _connector_container_name(connector_id, instance_name)
    client = _docker_client()

    # Pull instance_id from labels of the existing container if the
    # caller didn't supply it. Restart should "just work" without
    # needing to know the instance UUID.
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        existing = client.containers.get(container_name)
    except NotFound:
        existing = None
    if existing is not None:
        _ensure_managed_connector_container(existing, connector_id)

    instance_id: str | None = body.get("instance_id") if isinstance(body.get("instance_id"), str) else None
    if not instance_id and existing is not None:
        instance_id = existing.labels.get("phantom.instance_id")
    if not instance_id:
        raise HTTPException(
            400,
            "could not resolve instance_id (no running container; "
            "pass it in the body)",
        )

    # A bundled connector's image is derived from its pin. An uploaded
    # connector has no pin, so the image it was running is reused (or the caller
    # supplies image_ref when nothing is running).
    image_ref: str | None = None
    if isinstance(body.get("image_ref"), str) and body["image_ref"].strip():
        image_ref = body["image_ref"].strip()
    elif connector_id not in KNOWN_CONNECTORS and existing is not None:
        image_ref = (existing.attrs.get("Config") or {}).get("Image") or None

    # Reuse the start handler's logic by constructing a minimal Request-
    # like body. Could refactor into a shared helper later; for Phase 1
    # the duplication is small enough to live with.
    class _StubRequest:
        async def json(self):
            return {"instance_id": instance_id, **({"image_ref": image_ref} if image_ref else {})}

    return await start_connector_instance(
        connector_id, instance_name, _StubRequest(),
    )
