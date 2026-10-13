# Phantom — All-in-One Quickstart

> **Audience:** the single operator (or demo author) who wants the
> whole Phantom stack — agent, xlog, caldera — running on **one host**.

For the deployment shape where the agent runs separately from xlog/caldera, see [`split-deploy.md`](split-deploy.md).

---

## What you get

```
┌────────────────────────────────────────────────────────────────────┐
│ One Docker host                                                    │
│                                                                    │
│  ┌──────────────────────────────┐    ┌──────────────────────────┐  │
│  │ phantom-agent                │    │ xlog                     │  │
│  │  ├─ Next.js UI         :3000 │◄──►│ FastAPI + Strawberry     │  │
│  │  └─ Embedded MCP       :8080 │    │  GraphQL log generator   │  │
│  └──────────────────────────────┘    │           :8000          │  │
│                                       └──────────────────────────┘  │
│                                                                    │
│                       ┌──────────────────────────────┐             │
│                       │ caldera                      │             │
│                       │  MITRE Caldera 5.3.0 :8888   │             │
│                       └──────────────────────────────┘             │
└────────────────────────────────────────────────────────────────────┘
```

`phantom-agent` ships both the Next.js UI and the embedded MCP per the spark-agents v1.2 bundle design (one image, two processes, single trust boundary).

---

## Prerequisites

- Docker Engine 24+ with `docker compose` v2.
- ~12 GB free disk for images + volumes.
- A web browser (the UI is served over HTTPS with a self-signed certificate).
- (Recommended) An API key for a model provider: Anthropic (Claude) or OpenAI, **OR** a GCP service-account JSON for Vertex AI (Gemini). One is enough; none is tied to Google.
- (Recommended) An XSIAM tenant with PAPI credentials + a webhook collector if you want to send simulated logs there.

You don't need to install Caldera separately — this stack builds it from the pinned 5.3.0 source submodule.

---

## First-run flow

```bash
# 1. Clone with the Caldera submodule
git clone https://github.com/ayman-m/phantom.git
cd phantom
git submodule update --init --recursive third_party/caldera

# 2. Generate the operator-supplied secrets:
#      MCP_TOKEN          — bundle-internal coordination token. Pin
#                           in .env to keep it stable across restarts.
#      PHANTOM_DEFAULT_ADMIN_PASSWORD — first password of the `admin`
#                           user. The agent refuses to start on a fresh
#                           volume without it. Change it at first login.
#      XLOG_API_KEY       — bearer token xlog enforces (xlog answers
#                           503 without it). The agent sends the same
#                           value as XLOG_API_TOKEN.
#      PHANTOM_SECRET_KEK — 32-byte AES-256-GCM key for encrypting
#                           secrets at rest. Without this, every
#                           operator-supplied secret (Caldera creds,
#                           XSIAM auth, Vertex SA JSON, etc.) is
#                           stored as plaintext on disk.
#      CALDERA_RED_PASSWORD, CALDERA_API_KEY — the Caldera red-team
#                           password and API key Caldera is started
#                           with; you enter the same values on the
#                           caldera connector instance later.
{
  echo "MCP_TOKEN=$(openssl rand -hex 32)"
  echo "PHANTOM_SECRET_KEK=$(openssl rand -base64 32)"
  echo "PHANTOM_DEFAULT_ADMIN_PASSWORD=$(openssl rand -base64 18)"
  XLOG_KEY=$(openssl rand -hex 32)
  echo "XLOG_API_KEY=$XLOG_KEY"
  echo "XLOG_API_TOKEN=$XLOG_KEY"
  echo "CALDERA_RED_PASSWORD=$(openssl rand -base64 18)"
  echo "CALDERA_API_KEY=$(openssl rand -hex 24)"
} > .env
chmod 600 .env

# 3. Bring up the stack
docker compose up -d

# 4. Wait for healthy (~60 seconds for first boot, less on subsequent)
until [ "$(docker inspect -f '{{.State.Health.Status}}' phantom_agent 2>/dev/null)" = "healthy" ]; do
  sleep 3
done

# 5. Open the UI
echo "→ Open https://$(hostname):3000 in your browser"
```

The UI uses a self-signed certificate that the stack generates on first boot; accept the browser warning. There is no setup form: sign in as `admin`. The installer prints the password when it finishes; you can also read it on the host with `sudo grep '^PHANTOM_DEFAULT_ADMIN_PASSWORD=' /opt/phantom/.env` (`/opt/phantom/.env` also holds the other generated credentials; `sudo cat` shows them all). The UI sends you to `/profile` to change the password first. Then, in order:

1. **A model provider** at `/providers`: an Anthropic API key, an OpenAI API key, or the Vertex AI project, region and service-account JSON. Any one is enough; press Test Connection, then Save Changes. Memory and knowledge-base search use Vertex embeddings, so without a Vertex provider they use a keyword-style stand-in (chat is unaffected).
2. **Install the connectors you need** at `/connectors`, **Marketplace** tab. Every connector starts as available but not installed; open its card and press **Install Connector**.
3. **A connector instance per service** at `/connectors`, **Instances** tab (Create Instance; the form is rendered from the connector's schema):

| Connector | Fields |
|---|---|
| **caldera** | `baseUrl` `http://caldera:8888` (the compose-service hostname); secret `apiKey` (the `CALDERA_API_KEY` from `.env`) |
| **xlog** | `baseUrl` `https://xlog:8000` (xlog serves HTTPS on the compose network); secret `apiToken` (the `XLOG_API_KEY` from `.env`) |
| **web** | `cdp_url` `http://phantom-browser:9222` (already the default) |
| **xsiam** | `api_url` (your tenant's API URL, no path), `api_id` and `playgroundId`; secret `api_key` (a **Standard** API key, see below); optional `webhookEndpoint` and secret `webhookKey` (the XSIAM HTTP collector for synthetic logs) |
| **cortex-xdr** | `api_url`, `api_id`; secret `api_key` (a **Standard** API key, see below) |

**Cortex XSIAM and XDR need a Standard API key.** In the Cortex console open **Settings > Configurations > Integrations > API Keys**, choose **New Key**, and set **Security Level** to **Standard**. Do not choose Advanced: Phantom sends the key and its ID as plain `Authorization` and `x-xdr-auth-id` headers and does not compute the per-request signature an Advanced key requires, so every call would be refused. Paste the key value into `api_key`, the key's **ID** into `api_id`, and the **Copy API URL** value into `api_url` (for example `https://api-<tenant>.xdr.<region>.paloaltonetworks.com`; the connector adds `/public_api/v1`). A `401` means the key or ID is wrong; a `403` with `Datasets not found` means the dataset does not exist.

Each instance is stored in the InstanceStore, its secrets in the SecretStore, and the tool registry reloads when you save it. Every connector runs as its own container, started by `phantom-updater` on the first save, so the first instance of each connector waits for an image pull.

---

## Verify the deploy

```bash
# Smoke test the full capability surface against your stack.
MCP_TOKEN=$(docker compose exec -T phantom-agent printenv MCP_TOKEN) \
  ./bundles/spark/mcp/scripts/smoke_test.sh
```

Expected: **31/31 PASS**, no skips. If any check fails, the script reports which capability and why.

You can also confirm each service is reachable:

```bash
docker compose exec -T phantom-agent curl -ksf https://localhost:3000/api/auth/status
docker compose exec -T phantom-agent curl -ksf https://localhost:8080/ping/
docker compose exec -T xlog python -c "import urllib.request,ssl; urllib.request.urlopen('https://localhost:8000/health', timeout=5, context=ssl._create_unverified_context())"
docker compose exec -T caldera curl -sf http://localhost:8888/
```

---

## Common operations

### Apply settings overrides

```bash
TOKEN=$(docker compose exec -T phantom-agent printenv MCP_TOKEN)
curl -k -X PUT https://localhost:8080/api/v1/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"updates": {"defaultLogFormat": "CEF"}, "actor": "operator"}'
```

Settings are persisted to `<data_root>/settings.db` and survive restarts.

### Mint a scoped API key for an external integration

```bash
TOKEN=$(docker compose exec -T phantom-agent printenv MCP_TOKEN)
curl -k -X POST https://localhost:8080/api/v1/api_keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"label":"siem-poller","scopes":["audit:read"],"actor": "operator"}'
# Response includes "key": "phantom_ak_..." — copy it now; not recoverable.
```

### Update credentials later

Each credential has its own page: `/profile` for your UI password, `/providers` for the model providers (Vertex, Anthropic, OpenAI), and `/connectors` for connector instance credentials (edit the instance). The stores update atomically; the replaced secret is deleted from the SecretStore. The audit log records every rotation with the operator who initiated it.

### Backup before upgrades

```bash
scripts/backup_phantom.sh --label pre-upgrade
# → ./phantom-backup-pre-upgrade-<UTC stamp>.tar.gz
```

### Upgrading to a new release

Every upgrade uses the **new release's installer** — there is no in-UI update button and
re-running an old installer reinstalls the old version (each installer binary is sealed to
one release):

```bash
# 1. Download phantom-installer from the GitHub Release for the target version
# 2. Run it on the Phantom host:
sudo ./phantom-installer
```

The installer detects the existing install at `/opt/phantom`, prints
`Upgrading <old> → <new>`, pulls the new images by digest, and restarts only the services
whose image content changed.

**What an upgrade preserves (everything that is yours):**

- **Credentials & secrets** — `.env` is never rewritten: UI admin password, `MCP_TOKEN`,
  `PHANTOM_SECRET_KEK`, and all generated secrets survive verbatim.
- **Your content** — jobs, skills you created, connector instances, KB entries, sessions,
  memories, audit log, xlog scenarios (all live in named volumes, which are never wiped).
- **Skills you deleted** — deletions are recorded in a `.deleted/` denylist that survives
  upgrades; deleted default skills do not come back.
- **Data sources you edited or pinned** — bundle fixes flow to installed sources, but an
  edited source keeps your edited schema and a pinned source is left exactly as pinned.

**What an upgrade overwrites (by design):**

- Image digests + `docker-compose.yml` (don't hand-edit the compose file — changes there
  don't survive).
- Default/platform skills — updated versions replace the previous defaults. If you want to
  customize a default skill, save it as a NEW file; in-place edits to default skill files
  are overwritten on upgrade.

### Stop the stack

```bash
docker compose down
# Volumes (phantom_mcp_data, phantom_mcp_skills) persist.
# Add -v to drop them — destructive.
```

---

## When to switch to split-deploy

The agent-only bundle (`phantom-agent-bundle-agent-only.tar.gz`) is right when:

- You want one Phantom agent installation that talks to a **shared** xlog/caldera deployment another team operates.
- You want to keep the agent on a small, low-privilege host while xlog/caldera live on a beefier red-team box.
- You want the agent and the simulation backends to scale, deploy, and rotate credentials independently.

Switching from all-in-one to split is non-destructive — see [`split-deploy.md`](split-deploy.md) for the topology and `docker-compose.agent-only.yml` for the slim recipe.

---

## Troubleshooting

### Container marks itself unhealthy

```bash
docker compose logs phantom-agent | grep ERROR
```

Common causes:
- `phantom_mcp_data` volume not writable (filesystem permissions on the host)
- Embedded MCP failed to import a connector source — usually means the image was built against a different bundle version than what's currently in `/app/bundle`. Rebuild or pull a fresh image.

### Smoke test reports T9.x or T10.x failures

Both phases require connector instances + a model provider. If you have not added them yet, the corresponding tools won't be advertised and these tests will be the first to fail. Add the missing provider at `/providers` and instances at `/connectors`, then rerun the smoke test.

### "MCP_TOKEN is not configured" at the API surface

The entrypoint normally generates an ephemeral MCP_TOKEN if `.env` doesn't pin one. If the agent starts but the token never gets set, check `docker logs phantom_agent | grep MCP_TOKEN` for the entrypoint's bootstrap line.
