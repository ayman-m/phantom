# `updater/` — phantom-updater daemon

The `phantom-updater` customer container — manages per-instance connector container lifecycle + stack-level upgrades. No exposed ports; talks to Docker via `/var/run/docker.sock` and to the agent via `PHANTOM_AGENT_INTERNAL_URL`.

**Repo-wide rules live in the [root CLAUDE.md](../CLAUDE.md)** — change scenarios, contained-release discipline. This file holds only conventions LOCAL to phantom-updater.

## Layout

| Path | What it is |
|------|------------|
| `src/main.py` | The daemon — reconciliation loop + endpoint server. |
| `Dockerfile` | Python 3.12 + docker-py + minimal deps. |
| `requirements.txt` | Runtime deps. |
| `tests/` | pytest suite. |

## Role

phantom-updater's primary production role is **per-instance connector container lifecycle management**:
- When an operator creates an instance via `/connectors` → agent → REST, phantom-updater pulls the connector image + starts the container.
- When the operator deletes the instance, phantom-updater stops + removes the container.
- On boot, phantom-updater auto-spawns missing per-instance containers (reconciliation).
- On digest drift (the image referenced by an instance differs from the running container's digest), phantom-updater reconciles by re-creating the container with the new digest.

**Customer upgrades happen via the installer ONLY.**

## Per-instance container naming

`phantom-connector-<connector-id>-<instance-name>` — e.g. `phantom-connector-xsiam-primary-xsiam`. Connect from the agent via:

```
http://phantom-connector-<id>-<name>:9000
```

Network: all containers join `phantom_default` (the compose network). phantom-updater attaches each per-instance container to that network at create time.

## Config-file separation

phantom-updater reads TWO mounted files from the host:

| File | Mount path | Owns |
|---|---|---|
| `/host/.env` | bind mount | Service credentials + the 5 core stack-service digests + `PHANTOM_VERSION` |
| `/host/connector-digests.env` | bind mount | per-connector image pins (one per bundle connector) (`DIGEST_PHANTOM_CONNECTOR_*`) |

**The split is load-bearing:** see [`../installer/CLAUDE.md`](../installer/CLAUDE.md) for the install-side contract.

phantom-updater reads connector pins from `/host/connector-digests.env` only. If a pin is missing there it falls back to tag-pinning with a warning; it never consults `/host/.env`. Applying a release manifest writes the two files separately: core digests and `PHANTOM_VERSION` to `.env`, `DIGEST_PHANTOM_CONNECTOR_*` to `connector-digests.env`.

**Forbidden**: reading connector digests from `.env`. The split is deliberate.

## Registry access (anonymous)

Every Phantom image is **public** on GHCR, so the updater holds no registry credentials: there is no `PHANTOM_REGISTRY_USER`/`PHANTOM_REGISTRY_TOKEN`, no `docker login`, and no `Authorization` header on any outbound call (image pulls, the GitHub Releases lookup, the release-manifest download). Do not add one back; if a pull is denied, the fix is making the package public, not threading a token through.

- **Package names carry `-oss`.** `ghcr.io/<owner>/phantom-<name>-oss` for `agent`, `xlog`, `caldera`, `updater`, `browser`, and `phantom-connector-<id>-oss` for every bundle connector (`PACKAGE_SUFFIX` + `_connector_package()` in `src/main.py`). Container names and compose service names do not change: `phantom-connector-<id>-<instance>` is still the container name.
- **Owner** defaults to `ayman-m` (`PHANTOM_OWNER`). The release lookup is `https://api.github.com/repos/<owner>/phantom/releases/latest` and the manifest is the `release-manifest-vX.Y.Z.env` asset of that release. Both are anonymous, so GitHub rate limits them per source IP.
- A denied pull (401/403/`denied`) is not retried; the error says the package may not be public.

## Tests

```bash
cd updater
pip install -r requirements.txt pytest
PYTHONPATH=$PWD python3 -m pytest -x -q
```

## Architecture-page spec

phantom-updater's behavior is specified in [mcp/agent/app/help/architecture/page.tsx](../mcp/agent/app/help/architecture/page.tsx) `#phantom-updater` section. Any behavior change here MUST be reflected there in the same PR (root § Architecture page is the spec).
