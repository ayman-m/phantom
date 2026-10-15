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

## Publishing images (maintainers)

The published images come from this repository, built by [`.github/workflows/publish-images.yml`](.github/workflows/publish-images.yml). It runs only when a maintainer starts it, on a GitHub-hosted runner, and logs in to GHCR with the run's own `GITHUB_TOKEN`. No secret is stored anywhere.

**What a run does.** Every image whose build context changed since `base_tag` is built from the checkout and pushed as `<tag>`; every image that did not change is not rebuilt, and `<tag>` is added to the image that `base_tag` already points at, so its digest stays identical to `base_tag`'s. Four jobs run in order:

1. **Plan.** Validates the inputs, runs the guard tests, records the digests of `base_tag`, `latest` and `X.Y`, and decides per package, by diffing the checkout against the git tag `v<base_tag>`:
   - `phantom-agent-oss` is built on every run (`mcp/agent/Dockerfile`, repo-root context, no build args).
   - `phantom-connector-runtime-oss` is built when `phantom-connector-runtime/` changed.
   - Each `phantom-connector-<id>-oss` is built when its directory under `bundles/spark/connectors/` or the runtime changed.
   - `phantom-xlog-oss`, `phantom-updater-oss` and `phantom-browser-oss` are built when `xlog/`, `updater/` or `phantom-browser/` changed.
   - `phantom-caldera-oss` is always retagged: it needs the build-time overlay of the Phantom plugin and `default.yml`.
2. **Connector runtime.** Built, import-checked and pushed, or retagged when unchanged. It runs first because every connector image is built `FROM` it at `<tag>`, so a connector can never sit on an older runtime than the one in the same release.
3. **Images.** One job per built package. Each is built into the local daemon, checked **before anything is pushed**, then pushed. The check runs `docker run` on the image: the runtime image imports the runtime modules, and a connector image imports its connector module the way `runtime.entrypoint` does (this is what fails on a connector built on an older runtime). A failing image is not pushed. After the push the job reads the registry back and compares the digest it pushed.
4. **Finish.** Retags the unchanged images, re-reads everything, and writes the job summary with all fifteen digests and how each was produced.

`rebuild=all` builds every buildable image regardless of the diff. Use it the first time after images that this workflow did not build (the earlier retag-only releases left the connector images at their first build), and whenever `base_tag`'s images are not trusted to match its git tag. If the git tag `v<base_tag>` is not in the checkout, everything is built.

**Guards.** The run refuses to start unless `tag` is `X.Y.Z` or `X.Y.Z-rcN` (so never `latest` and never `X.Y`), `base_tag` is `X.Y.Z`, the two differ, and it runs on `main` of `ayman-m/phantom`. Before anything is written it checks that `base_tag` exists on all fifteen packages and that `<tag>` exists on none of them, unless `<tag>` ends in `-rcN`, which may be published again. Only `<tag>` is ever written. It records the digests of `base_tag`, `latest` and `X.Y` first and re-reads them at the end; any change fails the run. The logic is in [`.github/scripts/publish-images.sh`](.github/scripts/publish-images.sh) and its tests in `.github/scripts/test-publish-images.sh` (plain bash with a stub `docker` and a scratch git repository; the workflow runs them first). One of those tests reads every `COPY` line of every Dockerfile and fails when a package copies a path that its change detection does not watch, so a new `COPY` source cannot silently leave an image stale.

**One-time setup.** A job can push to a package only if the package lets this repository in. For each of the fifteen packages, open the package from the Packages tab of the `ayman-m` profile, choose **Package settings**, go to **Manage Actions access**, choose **Add Repository**, pick `ayman-m/phantom`, and set the role to **Write**. The packages:

`phantom-agent-oss`, `phantom-xlog-oss`, `phantom-caldera-oss`, `phantom-updater-oss`, `phantom-browser-oss`, `phantom-connector-runtime-oss`, `phantom-connector-xlog-oss`, `phantom-connector-xsiam-oss`, `phantom-connector-caldera-oss`, `phantom-connector-web-oss`, `phantom-connector-cortex-docs-oss`, `phantom-connector-cortex-content-oss`, `phantom-connector-cortex-xdr-oss`, `phantom-connector-http-sender-oss`, `phantom-connector-wec-sender-oss`.

**Run it.** Publish a candidate first, check it, then the final version. The final run must be on the commit that carries the git tag `vX.Y.Z`, because that tag is what the next release compares against.

```bash
gh workflow run publish-images.yml -R ayman-m/phantom -f tag=1.1.0-rc1 -f base_tag=1.0.3 -f rebuild=all
gh run watch -R ayman-m/phantom
```

**Limits.**
- The agent image and every image built here carry the `org.opencontainers.image.source` label that links the package to this repository, and `org.opencontainers.image.revision` with the commit. Retagged images keep the labels they were built with.
- A failed run leaves whatever it already pushed. A release candidate can simply be run again; a final version is never overwritten, so publish the next patch version instead. Run a candidate with the same inputs before every final tag.
- Builds are not bit-for-bit reproducible where a `requirements.txt` has open version ranges (the connector runtime does), which is why an unchanged package is retagged rather than rebuilt.
- Caldera is not rebuilt here.

## Known rough edges

- `bundles/spark/connectors/web/Dockerfile` installs `playwright>=1.48.0` and `trafilatura>=2.0.0` in a `RUN pip install` line without quotes, so the shell reads `>=...` as a redirect. The packages install, but the version floors are not applied and files named `=1.48.0` and `=2.0.0` are written into the image.
