<table>
  <tr>
    <td width="180" valign="top">
      <img src="logos/phantom-white.gif" alt="PHANTOM logo" width="160">
    </td>
    <td valign="top">
      <h1>PHANTOM</h1>
      <p>Continuous SOC simulation for defensive detection engineering. Generate synthetic security telemetry, run MITRE ATT&amp;CK scenarios, and check that your detections fire, with an AI agent that drives the whole loop.</p>
    </td>
  </tr>
</table>

## What Phantom is

Phantom is a self-hosted platform for building and validating detection content, aimed at Palo Alto Networks Cortex (XSIAM and XDR) but not tied to it. You describe a goal in plain language ("simulate a brute-force logon storm against my identity provider and tell me whether an alert fired"). The agent chains tools and skills to:

- generate log events shaped like a vendor's real logs (CEF, syslog, LEEF or JSON), from nearly 300 data sources;
- run multi-stage MITRE ATT&CK scenarios, and Caldera operations for the real-endpoint side;
- send the events to a destination you choose: a syslog or CEF broker, an HTTP collector, Splunk HEC, a webhook, or a Cribl endpoint;
- query your tenant (XQL, alerts, datasets, cases) to check that parsing, modeling and detection behaved as intended.

## Defensive use only

Phantom exists so that the environments it protects can be defended against real threats. It is a detection-engineering and purple-team tool.

- **All output is synthetic telemetry.** Phantom writes log records that describe events that never happened: connections, logons, scans, transfers. Hosts, users, IPs and domains in those records are fictitious.
- **Output goes to your own tenant.** Events are sent only to the broker, collector or tenant that you configure. Phantom sends no exploits, payloads, email or attack traffic to any third-party system.
- **Attack-shaped logs are the point.** Proving that a detector works means generating telemetry that looks like the attack it detects. That is standard practice in detection engineering.

Use it only against environments you own or are authorised to test. You are responsible for where you point it.

## Architecture in brief

Phantom runs as a Docker Compose stack:

| Service | Role | Host ports |
|---|---|---|
| `phantom-agent` | The operator UI (Next.js) and an embedded MCP server (Python) in one container. This is the single trust boundary for the agent, its tools, its stores and its secrets. | 3000 (UI), 8080 (MCP) |
| `xlog` | The synthetic-log generator (FastAPI and GraphQL). | internal |
| `caldera` | MITRE Caldera, for real-endpoint adversary operations. | 8888 and 8444, plus the Caldera contact ports |
| `phantom-updater` | Starts, stops and reconciles the per-instance connector containers. It has no host port. | none |
| `phantom-browser` | A headless browser sidecar for the `web` connector. Optional (compose profile `browser`). | internal |

Connectors (`xlog`, `xsiam`, `caldera`, `cortex-content`, `cortex-docs`, `cortex-xdr`, `web`, `http-sender`, `wec-sender`) each run in their own container, one per instance, and are installed from the in-app marketplace. Provider credentials, connector secrets and API keys live in an encrypted secret store that the agent has no tools to read or write; you manage them in the UI.

The in-product Architecture and User guides (`/help/architecture`, `/help/user`) are the detailed reference, and [`docs/architecture.md`](docs/architecture.md) has diagrams of the deployment topology and the runtime data flow.

## Get Phantom

### Install with the installer (recommended)

You need a Linux host (Ubuntu, Debian, RHEL, Fedora, Rocky, AlmaLinux or openSUSE; amd64 or arm64) with about 12 GB of free disk. The installer installs Docker Engine and the compose plugin if they are missing.

1. Download `phantom-installer` from the [GitHub Releases](https://github.com/ayman-m/phantom/releases) page for the version you want.
2. Run it on the host with `sudo ./phantom-installer`. It installs to `/opt/phantom`, generates the secrets and a first admin password, pulls the images and starts the stack.
3. Open `https://<host>:3000` and accept the browser warning (the stack generates a self-signed certificate). Sign in as `admin`. The password is printed at the end of a successful install; if you closed the terminal, read it on the host with `sudo grep '^PHANTOM_DEFAULT_ADMIN_PASSWORD=' /opt/phantom/.env`. Phantom sends you to **Profile** to change it first.

#### First setup, in this order

1. **Configure a model provider** on **Providers**: an Anthropic API key, an OpenAI API key, or a Vertex AI service account. One is enough. Press **Test Connection**, then **Save Changes**.
2. **Install the connectors you need** on **Connectors**, **Marketplace** tab. A fresh install lists every connector as available but not installed; open a card and press **Install Connector**.
3. **Create one instance per connector** on **Connectors**, **Instances** tab, **Create Instance**. The installer generated the credentials for the services that ship in the stack, and you read them on the host from `/opt/phantom/.env` (`sudo cat /opt/phantom/.env`, or `sudo grep` for one line):

| Connector | Fields | Where the value comes from |
|---|---|---|
| `xlog` | URL `https://xlog:8000`; secret `apiToken` | `XLOG_API_KEY` in `.env` |
| `caldera` | URL `http://caldera:8888`; secret `apiKey` | `CALDERA_API_KEY` in `.env` |
| `web` | `cdp_url` `http://phantom-browser:9222` | the default is already filled in |
| `xsiam`, `cortex-xdr` | `api_url`, `api_id`; secret `api_key` | created in your own Cortex tenant, see below |
| `http-sender` | **Destination** first: *XSIAM HTTP collector* (`collectorUrl`, `vendor`, `product`; secret `collectorKey`), *Cribl integration* (`criblUrl`; secret `criblToken`) or *Both* | created in your own Cortex tenant (Settings, Data Sources & Integrations) |

Press **Test Connection** on each instance. The first instance of a connector waits for its image to pull.

**Cortex XSIAM and Cortex XDR: create a Standard API key.** In the Cortex console go to **Settings > Configurations > Integrations > API Keys** and choose **New Key**, then set **Security Level** to **Standard**. Do not choose Advanced. Phantom authenticates with the key value and the key ID as plain headers, and an Advanced key needs a per-request signature that Phantom does not compute, so every call would fail with an authentication error. Copy the key value into `api_key` and the **ID** shown in the keys table into `api_id`. Set `api_url` to the API URL of your tenant (`https://api-<tenant>.xdr.<region>.paloaltonetworks.com`, the **Copy API URL** button on the same page); the connector adds the path itself. Give the key a role that allows what you want Phantom to do, for example read access for queries. A `403` with `Datasets not found` means the dataset does not exist, not that the key is wrong; a wrong key returns `401`.

The images are public packages on GitHub Container Registry. Pulling them needs **no account, token or key**:

| Image | Used for |
|---|---|
| `ghcr.io/ayman-m/phantom-agent-oss` | the agent and its embedded MCP |
| `ghcr.io/ayman-m/phantom-xlog-oss` | the log generator |
| `ghcr.io/ayman-m/phantom-caldera-oss` | Caldera |
| `ghcr.io/ayman-m/phantom-updater-oss` | the connector-container manager |
| `ghcr.io/ayman-m/phantom-browser-oss` | the headless browser sidecar |
| `ghcr.io/ayman-m/phantom-connector-runtime-oss` | the base image of every connector container |
| `ghcr.io/ayman-m/phantom-connector-<id>-oss` | one image per connector |

The installer pins each image by digest, so an installed stack runs exactly the content of its release. To upgrade, run the installer of the newer release; your data, secrets and custom content are kept. See [`installer/CLAUDE.md`](installer/CLAUDE.md) for the install contract.

### Build from source

See [`BUILDING.md`](BUILDING.md) for what works from a clone, what each Dockerfile needs, and how connectors behave in a source build (they run the published connector images).

## Documentation

- In the running UI: `/help/architecture`, `/help/user`, `/help/journeys` (click-by-click walkthroughs) and `/help/api`.
- [`docs/architecture.md`](docs/architecture.md): topology and data-flow diagrams.
- [`docs/agent-self-modification.md`](docs/agent-self-modification.md): what the agent may change about itself, and what it may never touch.
- [`docs/api-reference.md`](docs/api-reference.md): the REST surface.
- [`CODEBASE_MAP.md`](CODEBASE_MAP.md): the structural map of the repository.
- [`CHANGELOG.md`](CHANGELOG.md): release notes.

## Repository layout

```
bundles/spark/      the agent bundle: manifest, connectors, providers, prompts,
                    skills, data sources, knowledge bases, and the embedded MCP
                    server source (bundles/spark/mcp)
mcp/agent/          the Next.js operator UI and the agent image
xlog/               the synthetic-log generator
updater/            the connector-container lifecycle daemon
phantom-browser/    the headless browser sidecar
phantom-connector-runtime/   the base image for connector containers
installer/          the installer template and the customer compose file
third_party/caldera MITRE Caldera (git submodule)
docs/               operator and contributor documentation
tooling/            validation and codebase-search helpers
```

## Contributing and development

Each service has its own `CLAUDE.md` with the local conventions. Before sending a change, run the checks:

```bash
# Embedded MCP server tests (Python 3.12 recommended)
cd bundles/spark/mcp && PYTHONPATH=$PWD/src python3 -m pytest tests/

# Agent type-check, lint and production build
cd mcp/agent && npx tsc --noEmit && npm run lint && npm run build

# Bundle content validation (data sources, connectors, skills)
python3 tooling/validate/validate_all.py
```

Bug reports and feature requests go through GitHub issues. Please report security problems privately; see below.

## Security

Report vulnerabilities through GitHub private vulnerability reporting, not through a public issue. See [`SECURITY.md`](SECURITY.md) for how, and for what is in scope.

## License

Phantom is released under the [MIT License](LICENSE). Third-party material that ships in this repository keeps its own licence; see [`NOTICE`](NOTICE).

## Trademarks

Palo Alto Networks, Cortex, XSIAM and XDR are trademarks of Palo Alto Networks, Inc. MITRE ATT&CK is a registered trademark of The MITRE Corporation. All other product names, vendor names and logos mentioned in this repository, including those in the data sources, belong to their respective owners and are used only to identify the products whose log formats Phantom imitates. Phantom is an independent project. It is not affiliated with, sponsored by or endorsed by any of them.
