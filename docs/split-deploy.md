# Phantom — Split-Deploy Guide

> **Audience:** the operator who received a slim Phantom agent
> bundle (`phantom-agent-bundle-agent-only.tar.gz`) and wants to
> run the agent on a machine that is **separate** from where xlog
> and caldera run.

> **Known limitation.** The slim recipe (`docker-compose.agent-only.yml`)
> has no `phantom-updater` service. Every bundle connector runs as a
> per-instance container that `phantom-updater` starts, so connector
> instances cannot start on a host that runs only the slim recipe. The
> installer (see the README) and the root `docker-compose.yml` run the
> updater; use one of those for a working stack. This guide describes the
> slim recipe's intended shape.

This is the right deployment shape when:

- You want one Phantom agent installation that talks to a **shared**
  xlog/caldera deployment another team operates.
- You want to keep the agent on a small, low-privilege host while
  xlog/caldera live on a beefier red-team box.
- You want the agent and the simulation backends to scale, deploy,
  and rotate credentials independently.

If xlog and caldera are running on the same machine as the agent,
use the all-in-one compose recipe (`docker-compose.yml`) instead;
this guide doesn't apply.

---

## Architecture

```
┌──────────────────────────────────┐                ┌──────────────────────────────────┐
│ Machine A — Phantom agent        │  HTTP/HTTPS    │ Machine B — SOC services         │
│                                   │ ─────────────► │                                   │
│  phantom-agent container          │                │  xlog container        :8000     │
│   ├─ Next.js UI         :3000     │                │  caldera container     :8888,    │
│   └─ Embedded MCP       :8080     │                │                       :8443      │
│  └─ Volumes:                      │                │                                   │
│     • /app/data (audit, secrets)  │                └──────────────────────────────────┘
│     • /app/skills                 │                ┌──────────────────────────────────┐
│                                   │                │ XSIAM tenant (external)          │
│                                   │ ─────────────► │  PAPI + webhook                  │
└──────────────────────────────────┘                └──────────────────────────────────┘
```

**Machine A** runs only the `phantom-agent` container. The container
ships both the Next.js UI and the embedded MCP server (per the
spark-agents v1.2 bundle design — the MCP is part of the agent's
trust boundary, not a sibling service).

**Machine B** runs xlog and caldera. They expose their HTTP ports
to Machine A's network so the agent can reach them.

**XSIAM** is external and reached over the public internet.

---

## What you got in the slim bundle

```
phantom-agent-bundle-agent-only.tar.gz/
├── README.md                       quick-start summary
├── docker-compose.yml              agent-only compose recipe
├── images/
│   └── phantom-agent-local.tar     phantom-agent Docker image
├── bundles/spark/
│   ├── manifest.yaml               agent declaration (full source is baked into image)
│   └── README.md                   bundle overview
├── docs/split-deploy.md            this file
├── runtime-metadata.json           build provenance
├── bundle-manifest.json            file inventory
├── bundle-signature.json           HMAC signature metadata (unsigned by default)
├── tool-snapshot.json              expected connector tool list
├── tool-catalog.yaml               curated tool catalog
├── secret-bindings.example.yaml    secret-binding template
├── observability.contract.yaml     observability event schema
├── checksums.sha256                tamper detection
└── scripts/
    ├── smoke_test.sh               Capability verification suite
    ├── verify_agent_bundle.py      checksum + signature verification
    ├── agent_lifecycle.sh          start/stop/restart/logs helpers
    └── …                           install, import, materialize-secrets
```

**The agent's behavior is fully encoded in the image.** The `.env`
file carries only the few values the container needs at boot (see
First-run flow). Everything else operator-supplied (provider and
connector URLs and credentials, settings) is entered in the UI after
first login — no config files to edit, no secrets in CI.

---

## Network requirements

### On Machine A (the agent)
- Outbound HTTP/HTTPS to Machine B's xlog port (default 8000) and
  caldera port (default 8888 / 8443).
- Outbound HTTPS to your XSIAM tenant API + webhook endpoint.
- Outbound HTTPS to `aiplatform.googleapis.com` /
  `generativelanguage.googleapis.com` for Gemini / Vertex AI.
- Inbound port 3000 from your operators' browsers.
- (Optional) Inbound port 8080 from any external SOC tool that
  wants to call MCP admin endpoints. If nothing external needs
  MCP access, drop the port mapping for tighter security.

### On Machine B (xlog + caldera)
- xlog must bind to an interface reachable from Machine A.
  Update Machine B's docker-compose to expose `8000` to its host
  network and ensure firewall allows Machine A's IP through:
  ```yaml
  xlog:
    ports:
      - "0.0.0.0:8000:8000"     # bind to all interfaces
  ```
- caldera same:
  ```yaml
  caldera:
    ports:
      - "0.0.0.0:8888:8888"
      - "0.0.0.0:8443:8443"
  ```
- DNS: either give Machine B a hostname Machine A can resolve, or
  use Machine B's IP directly in the connector instance form.

### Production hardening
- Terminate TLS in front of xlog and caldera (a reverse proxy on
  Machine B with a real certificate, or use the bundled
  `SSL_CERT_PEM` / `SSL_KEY_PEM` for caldera's built-in HTTPS on
  :8443).
- Restrict Machine A's MCP port (8080) to localhost-only or behind
  a VPN — operators rarely need direct MCP admin access.

---

## First-run flow

```bash
# 1. Extract the archive
tar -xzf phantom-agent-bundle-agent-only.tar.gz
cd phantom-agent-bundle-agent-only

# 2. Verify checksums (recommended)
shasum -a 256 -c checksums.sha256

# 3. Load the agent image
docker load < images/phantom-agent-local.tar

# 4. Generate operator-supplied secrets:
#      PHANTOM_DEFAULT_ADMIN_PASSWORD — first password of the `admin`
#                           user. The agent refuses to start on a fresh
#                           volume without it. You are asked to change
#                           it at first login.
#      MCP_TOKEN          — bundle-internal bearer (pin so it stays
#                           stable across restarts).
#      PHANTOM_SECRET_KEK — 32-byte AES-256-GCM key encrypting all
#                           operator-supplied secrets at rest.
#                           Without this, the secrets directory
#                           (Caldera creds, XSIAM auth, Vertex SA)
#                           is plaintext on disk and in the backup
#                           tarball.
{
  echo "PHANTOM_DEFAULT_ADMIN_PASSWORD=$(openssl rand -base64 18)"
  echo "MCP_TOKEN=$(openssl rand -hex 32)"
  echo "PHANTOM_SECRET_KEK=$(openssl rand -base64 32)"
} > .env
chmod 600 .env

# 5. Bring up the agent
docker compose up -d

# 6. Wait for healthy
until [ "$(docker inspect -f '{{.State.Health.Status}}' phantom_agent 2>/dev/null)" = "healthy" ]; do
  sleep 3
done
echo "agent ready"

# 7. Open the UI
echo "→ Open https://$(hostname):3000 in your browser"
```

The UI is served with a self-signed certificate (accept the browser
warning, or supply your own pair on the `phantom_tls` volume). There
is no setup form: sign in as `admin` with the
`PHANTOM_DEFAULT_ADMIN_PASSWORD` from `.env`. The UI sends you to
`/profile` to change it before anything else.

Then add what the agent needs, in order:

1. **Model provider** at `/providers`: your Vertex AI project, region
   and service-account JSON (or a Gemini API key). The provider
   credentials go to the ProviderStore and SecretStore.
2. **One connector instance per service** at `/connectors` (Create
   Instance; the form is rendered from each connector's schema):

| Connector | Fields |
|---|---|
| **caldera** | `baseUrl` `http://<machine-b>:8888`; secret `apiKey` (the red-team API key baked into Caldera at its first boot) |
| **xlog** | `baseUrl` `https://<machine-b>:8000`; secret `apiToken` (the token xlog enforces) |
| **xsiam** | `api_url`, `api_id`, `playgroundId`; secret `api_key` (the PAPI Authorization header value); optional `webhookEndpoint` and secret `webhookKey` (the XSIAM HTTP collector for synthetic logs) |

Each instance is stored in the InstanceStore (secrets in the
SecretStore), and the tool registry reloads when you save it. The
agent's tools (xlog scenarios, caldera operations, XSIAM detection
validation) are then wired against your remote infrastructure.

---

## Verify the deploy

```bash
# Smoke test the full capability surface against your
# new deployment. Reads MCP_TOKEN from inside the running container.
# (The script is hoisted to top-level scripts/ in the slim bundle —
# the bundles/spark/mcp/scripts/ path used by the full bundle is
# baked into the image but not present on the slim host.)
MCP_TOKEN=$(docker compose exec -T phantom-agent printenv MCP_TOKEN) \
  scripts/smoke_test.sh
```

Expected: **31/31 PASS**, with no skips. If any check fails, the
script reports which capability and why.

You can also test connectivity from the agent to Machine B directly:

```bash
docker compose exec -T phantom-agent curl -ksf https://<machine-b>:8000/health
docker compose exec -T phantom-agent curl -sf http://<machine-b>:8888/
```

If either curl hangs or fails, the issue is between Machine A and
Machine B — verify the firewall, the port binding (`0.0.0.0:`
prefix), and the DNS / IP you used in the connector instance.

---

## Updating credentials later

Operator-supplied values live in `/app/data/secrets/` (the SecretStore
inside the persistent `phantom_mcp_data` volume). Each one has its own
page; there is no combined form. To rotate:

- **Your UI password** — `/profile`.
- **Caldera, xlog and XSIAM credentials** — edit the connector instance
  at `/connectors`. The instance store updates atomically; the old
  secret is replaced.
- **Vertex / Gemini credentials** — edit the provider at `/providers`.

The audit log (`/api/v1/audit`) records every credential rotation
with the operator who initiated it.

---

## Backup and recovery

The two volumes that hold operator state:

| Volume | Contents |
|---|---|
| `phantom_mcp_data` | Sqlite stores: audit log, instance store, secret paths, KB, sessions, memory, jobs |
| `phantom_mcp_skills` | Skills library (markdown), seeded from image at first run |

The bind-mounted `./.phantom-agent/` directory (`/app/runtime` in the
container) is retained but unused: nothing in the current stack writes
to it.

**Backup** (use the script — it captures BOTH volumes plus the
`./.phantom-agent/` bind-mount if present, hashes each component, and
writes a manifest so the restore side can refuse a corrupted archive):
```bash
scripts/backup_phantom.sh --label pre-upgrade
# → ./phantom-backup-pre-upgrade-<UTC stamp>.tar.gz
```

**Restore on a new machine:**
```bash
# 1. Bring up the agent compose just to materialize empty volumes
docker compose up -d
docker compose down                       # leaves the volumes empty

# 2. Restore from your backup archive
scripts/restore_phantom.sh phantom-backup-pre-upgrade-<UTC stamp>.tar.gz

# 3. Bring the agent back up — your audit log, KB, instance configs,
#    provider config and secrets are all in place.
docker compose up -d
```

The restore script refuses to overwrite non-empty volumes by default
(safety against silent clobber). Pass `--force` to opt in.

**What's NOT in the backup**: the Docker image itself (carry that via
the agent bundle archive), and any state inside xlog/caldera on
Machine B (those have their own backup story — out of scope for this
guide).

**KEK warning**: when `PHANTOM_SECRET_KEK` is set in `.env`, the
backup tarball contains AES-256-GCM ciphertext for every operator-
supplied secret. The KEK itself is NOT in the tarball (it's in
`.env` which `backup_phantom.sh` does not capture by design — env
files often hold per-deploy values like network addresses you don't
want restored verbatim). **Store the KEK separately in your secret
manager.** Losing it means losing every secret in the backup; you'd
have to re-enter every provider and connector credential on
the restored machine.

The trade-off is intentional: a stolen backup tarball is useless
without the KEK, which is the core security property
encryption-at-rest gives you.

---

## Encryption-at-rest for operator secrets

By default, every operator-supplied secret (Caldera API key, XSIAM
PAPI auth, Vertex service-account JSON, etc.) is encrypted with
AES-256-GCM before touching disk. The encryption key (KEK) lives in
`.env` as `PHANTOM_SECRET_KEK`.

Without `PHANTOM_SECRET_KEK` set, the SecretStore falls back to
plaintext mode for upgrade compatibility. You'll see a startup
warning:

```
SecretStore: PHANTOM_SECRET_KEK is NOT set — secrets stored as
PLAINTEXT on disk.
```

To enable encryption on an existing deploy:

```bash
# 1. Generate a KEK and add to .env (back it up to your secret
#    manager FIRST — losing it loses every secret).
echo "PHANTOM_SECRET_KEK=$(openssl rand -base64 32)" >> .env

# 2. Restart the agent. Existing plaintext files migrate to encrypted
#    automatically on next read of each secret.
docker compose restart phantom-agent
```

Migration is transparent and per-secret: the first read after restart
detects a plaintext file, decodes it, re-writes it as encrypted,
returns the value. Subsequent reads see the encrypted form. No
operator action beyond setting the env var.

**Do NOT remove `PHANTOM_SECRET_KEK` once set on a deploy with
encrypted secrets.** The agent will refuse to read encrypted files
without the KEK rather than return garbage. To go back to plaintext
mode, you'd need to read every secret out (with the KEK), unset the
env var, and re-enter every provider and connector credential.

---

## Troubleshooting

### Container marks itself unhealthy after start
- Check `docker compose logs phantom-agent` for the `[entrypoint]`
  lines. Both processes (MCP + Next.js) should report ready.
- The combined-container healthcheck verifies both ports 3000 and
  8080 are responding. If one is down, the container is unhealthy.

### The UI shows "MCP not configured" or the agent exits at boot
- The SecretStore needs a writable `phantom_mcp_data` mount. Verify it
  is mounted (check `docker inspect phantom_agent`).
- On a fresh volume the agent exits if `PHANTOM_DEFAULT_ADMIN_PASSWORD`
  is missing from `.env`; the `[entrypoint]` log lines say so.

### Tool calls timeout or 502
- Indicates Machine A → Machine B network failure. From inside
  the agent container:
  ```bash
  docker compose exec -T phantom-agent curl -kv https://<machine-b>:8000/health
  ```
  If this fails, fix the network on Machine B before troubleshooting
  the agent further.

### Agent UI loads but `/api/auth/status` 503s
- Indicates the embedded MCP didn't start. Check `docker compose
  logs phantom-agent | grep ERROR` — typically a Python import
  error in the bundle's connector source. The image was likely
  built against a different bundle version than what's currently
  in `/app/bundle`. Rebuild or pull a fresh image.

---

## When to switch to the all-in-one bundle

The all-in-one bundle (`phantom-agent-bundle-full.tar.gz`)
includes xlog and caldera images alongside the agent. Use it when:

- You're a single operator running the whole stack on one host.
- You're doing a demo / proof-of-concept and don't want to set up
  cross-host networking.
- You're standing up a fresh environment where you want xlog and
  caldera to be installed alongside the agent on the same machine.

Switching from split to all-in-one is non-destructive — the
`phantom_mcp_data` volume holding your audit log, KB, sessions,
and instance configs is portable. Just `docker compose down` (no
`-v`) on the slim deploy, copy the volume to the new host, and
`docker compose up -d` with the full compose file.
