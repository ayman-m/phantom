# `installer/` — customer installer template

The phantom-installer build template. Produces a single binary the customer downloads from the GitHub Release and runs on their target host to bring up the Phantom stack at `/opt/phantom/`.

**Repo-wide rules live in the [root CLAUDE.md](../CLAUDE.md)** — change scenarios, image digest pinning, customer onboarding semantics. This file holds only conventions LOCAL to installer authoring.

## Layout

| Path | What it is |
|------|------------|
| `build-phantom-installer.sh` | Builds the `phantom-installer` binary: substitutes the release manifest's digests, the customer compose and the host utilities into `phantom-installer.template.sh`. |
| `phantom-installer.template.sh` | The installer itself. Never run it directly: its placeholders are unsubstituted. |
| `docker-compose.yml` | Customer compose — fixed services, image refs use `@${DIGEST_*}` substitution from the install-time `.env`. |
| `phantom-factory-reset.sh`, `phantom-reset-admin-password.sh` | Host-side recovery utilities, embedded in the installer and written to `/opt/phantom/`. |
| `generate-self-signed-certs.sh` | Self-signed TLS material for the agent. |
| `.env.example` | Reference for the shape of `.env`. The installer writes the real one at install time, with generated secrets and the release manifest's digests. |

## Registry access: public images, no credentials

Every Phantom image is **public** on GHCR (`ghcr.io/ayman-m/phantom-<name>-oss`, plus `phantom-connector-<id>-oss` per bundle connector). The installer therefore has **no registry prompt, no `PHANTOM_REGISTRY_USER`/`PHANTOM_REGISTRY_TOKEN`, no `docker login` and no pull-retry/credential logic**, and `docker compose pull` runs anonymously. Step 4 only checks, warn-only, that the anonymous pull-token endpoint is reachable so a blocked egress is named early.

**Forbidden going forward**: re-introducing any token, PAT or registry-user prompt, env var or `.env` key. If a pull is denied, fix the package visibility on GHCR; do not add credentials. Releases are looked up (by the updater) at `https://github.com/ayman-m/phantom/releases`, also anonymously.

Re-running the installer on an existing install keeps its secrets and refreshes the digest manifest. There is no migration path from earlier pre-release layouts: those installs are replaced, not upgraded.

## Compose: digest pinning contract

`docker-compose.yml` here uses `image: ghcr.io/.../phantom-<svc>-oss@${DIGEST_PHANTOM_<SVC>}` substitution. The matching `${DIGEST_*}` values come from:

| File | Owned by | Content |
|---|---|---|
| `/opt/phantom/.env` | installer at install time | Service credentials + 5 core stack-service digests (`DIGEST_PHANTOM_AGENT`, `DIGEST_PHANTOM_XLOG`, `DIGEST_PHANTOM_CALDERA`, `DIGEST_PHANTOM_UPDATER`, `DIGEST_PHANTOM_BROWSER`) + `PHANTOM_VERSION` marker |
| `/opt/phantom/connector-digests.env` | installer at install time, **phantom-updater reads** | 10 per-connector image pins (`DIGEST_PHANTOM_CONNECTOR_*`) |

**The split is load-bearing:** per-connector containers aren't declared in `docker-compose.yml`, so their digests are NOT compose-substitution variables — they're consumed at runtime by phantom-updater when an operator creates a connector instance.

**Forbidden going forward**:
- Adding `DIGEST_PHANTOM_CONNECTOR_*` writes to `.env` for any reason.
- Adding any connector configuration (instance ID, container URL, baseUrl, secret refs) to `.env`.
- Mixing the two files.

## Cross-subsystem must-update-together list (when changing image-pinning code)

Any change to image-pinning behavior here MUST touch all of:
- the release workflow (generates the manifest)
- `phantom-installer` template (writes `.env`)
- `updater/src/main.py` (reads `/host/connector-digests.env`)
- `mcp/agent/app/help/architecture/page.tsx` (canonical spec)
- `mcp/agent/app/observability/connectors/page.tsx` (operator-visible state)

Skip any of these → silent drift.
