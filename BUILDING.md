# Building Phantom from source

This page says what you can build from a clone, how, and where the source build stops short of the installed product. Where something has not been run, it says so.

**Read this first.** The supported way to run the whole stack is the installer with the published images (see the README). A source build gives you the agent UI, the embedded MCP server, `xlog`, Caldera and `phantom-updater`. The connector containers that the updater starts are **not** built from your tree: it pulls the published connector images (see [Connectors in a source build](#connectors-in-a-source-build)).

## Status of this page

The Dockerfiles and compose files were checked by reading them: every `COPY`/`ADD` source in the service Dockerfiles exists in the build context that the compose file (or the Dockerfile header) names. **No image has been built from this tree**, because the machine it was prepared on has no Docker. Treat the build commands below as the intended path, not as a tested one, until you have run them. The agent build and the test suites in the last section do not need Docker and have been run.

## Prerequisites

- Git, with submodule support.
- Docker Engine 24 or newer and the `docker compose` v2 plugin.
- About 12 GB of free disk for images and volumes.
- For the test suites: Python 3.12 (3.14 is missing some dependencies, such as `strawberry` and `fastapi`, at the pinned versions) and Node.js 20.

## Clone

Caldera is a git submodule. A plain clone leaves `third_party/caldera` empty and the Caldera image cannot build.

```bash
git clone --recurse-submodules https://github.com/ayman-m/phantom.git
cd phantom
# or, in an existing clone:
git submodule update --init --recursive third_party/caldera
```

## What builds, and from which context

| Image | Dockerfile | Build context | Notes |
|---|---|---|---|
| `phantom-agent` | `mcp/agent/Dockerfile` | repo root (`.`) | Next.js build (Node 20), then a Python 3.12 runtime with the embedded MCP. The context must be the repo root because the Dockerfile copies both `mcp/agent/` and `bundles/spark/`. |
| `xlog` | `xlog/Dockerfile` | `./xlog` | Python 3.12. |
| `caldera` | `third_party/caldera/Dockerfile` | `./third_party/caldera` | Needs the submodule. Build args `TZ` and `VARIANT` (`full` by default). |
| `phantom-browser` | `phantom-browser/Dockerfile` | `./phantom-browser` | Headless Chromium sidecar for the `web` connector. Compose profile `browser`. |
| `phantom-updater` | `updater/Dockerfile` | `./updater` | In the source compose file. |
| `phantom-connector-runtime` | `phantom-connector-runtime/Dockerfile` | `./phantom-connector-runtime` | The base image of every connector image. |
| `phantom-connector-<id>` | `bundles/spark/connectors/<id>/Dockerfile` | repo root (`.`) | `FROM ghcr.io/ayman-m/phantom-connector-runtime-oss:<tag>` by default; override with the build args `PHANTOM_RUNTIME_OWNER` and `PHANTOM_RUNTIME_VERSION` to use a runtime image you built yourself. |

The base images are pinned by digest in the Dockerfiles. `bundles/spark/mcp/Dockerfile` is a standalone build of the MCP server; the agent image does not use it.

## Run the source compose file

`docker-compose.yml` at the repo root is the development compose file. It builds `xlog`, `caldera`, `phantom-updater`, `phantom-agent` and (with `--profile browser`) `phantom-browser` and tags them `<name>:local`.

Create a `.env` next to it. These are the values the services need; none of them ships with a default:

```bash
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
```

- `MCP_TOKEN` is shared: the agent and `phantom-updater` both read it from `.env`, so set it here rather than letting the agent generate one.
- `PHANTOM_SECRET_KEK` encrypts the secret store. Keep it: if you lose it, the stored secrets cannot be read.
- `PHANTOM_DEFAULT_ADMIN_PASSWORD` is the first `admin` password. The agent refuses to start on a fresh volume without it. You are asked to change it at first login.
- `XLOG_API_KEY` is what `xlog` enforces and `XLOG_API_TOKEN` is what the agent sends. In the installed stack the second is an alias of the first; in the source compose you set both to the same value. With `XLOG_API_KEY` unset, `xlog` answers 503.
- `CALDERA_RED_PASSWORD` has a placeholder default in the compose file. Set your own.

Then:

```bash
docker compose build
docker compose up -d
```

The UI is served on `https://localhost:3000` with a self-signed certificate that the agent generates into the `phantom_tls` volume. The embedded MCP is published on port 8080 and `xlog` on port 8999. Sign in as `admin`.

The bundle (`bundles/spark/`) is mounted read-only into the agent container, so edits to skills, data sources and connector definitions take effect on a restart without rebuilding the image. Changes to the Next.js or MCP source need `docker compose up -d --build phantom-agent`.

## Connectors in a source build

Every connector in the bundle (`xlog`, `xsiam`, `caldera`, `cortex-content`, `cortex-docs`, `cortex-xdr`, `web`, `http-sender`, `wec-sender`) is declared `style: container`: its tools run in a per-instance container that `phantom-updater` starts through the Docker socket when you create an instance. The source compose file includes the updater with the same contract as `installer/docker-compose.yml`: no host port, the `MCP_TOKEN` bearer on every endpoint except `/healthz`, the Docker socket and the checkout mounted (the checkout at `/host`, where it reads `.env`).

What differs from an installed stack:

- **The connector images are not built from your tree.** The updater has no release manifest here, so it pulls `ghcr.io/ayman-m/phantom-connector-<id>-oss` for the tag in `PHANTOM_VERSION` from `.env`, or `latest` when that is unset, and logs a tag-pinning warning. Your edits under `bundles/spark/connectors/<id>/src` therefore do not reach a running connector until you build that image yourself (build context: the repo root, see the table above) and make the updater use it; that path is not documented because it has not been tried. Use `PHANTOM_OWNER` in `.env` to pull from another registry owner.
- **The updater mounts the checkout read-write and the Docker socket.** That is root-equivalent on the host, as in an installed stack. Do not run a source build on a machine you do not control.
- The first pull of a connector image needs outbound access to `ghcr.io`.

None of this has been run: there is no Docker on the machine this tree was prepared on, and the connector packages are published with the release. Treat it as the intended behaviour, to be confirmed on your first `docker compose up`.

`installer/docker-compose.yml` itself is not a source-build file: it references the published images by digest (`ghcr.io/<owner>/phantom-<name>-oss@${DIGEST_...}`), and the installer writes the digests into `.env`. See [`installer/CLAUDE.md`](installer/CLAUDE.md).

## Build and test without Docker

These do not need Docker:

```bash
# Agent: type-check, lint, production build
cd mcp/agent
npm ci
npx tsc --noEmit
npm run lint
npm run build

# Embedded MCP server tests (use a Python 3.12 virtualenv)
cd bundles/spark/mcp
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio
PYTHONPATH=$PWD/src python -m pytest tests/ -x -q

# xlog and updater tests
cd xlog && pip install -r requirements.txt pytest pytest-asyncio && python -m pytest -x -q
cd updater && pip install -r requirements.txt pytest pytest-asyncio && PYTHONPATH=$PWD/src python -m pytest -x -q

# Bundle validation
pip install pyyaml jsonschema 'mcp[cli]<2'
python3 tooling/validate/validate_all.py
```

`PYTHONPATH=$PWD/src` is required for the MCP and updater suites. Keep `mcp[cli]` below 2: version 2 changes the client API that a few tests and the codebase-search check use. These are the same steps as `.github/workflows/ci.yml`.

## Known rough edges

- `bundles/spark/connectors/web/Dockerfile` installs `playwright>=1.48.0` and `trafilatura>=2.0.0` in a `RUN pip install` line without quotes, so the shell reads `>=...` as a redirect. The packages install, but the version floors are not applied and files named `=1.48.0` and `=2.0.0` are written into the image.
