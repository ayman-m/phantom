# syntax=docker/dockerfile:1
#
# Combined phantom-agent image — ships the Next.js UI AND the bundle's
# embedded MCP server in a single container. This matches the spark-
# agents v1.2 bundle design where `embeddedMcp` is part of the agent's
# trust boundary, not a sibling docker-compose service.
#
# IMPORTANT: this Dockerfile expects the build context to be the REPO
# ROOT (so it can COPY both `mcp/agent/` and `bundles/spark/mcp/`).
# docker-compose.yml's build block sets `context: .` accordingly.
#
# Stages:
#   agent-builder — Next.js build (Node.js 20)
#   mcp-deps      — Python dep install (3.12, isolated)
#   runtime       — Python 3.12 base + Node.js 20 + both copies of source

# ─────────────────────────────────────────────────────────────────
# Stage 1 — Next.js build
# ─────────────────────────────────────────────────────────────────
# Base image pinned by digest. Update via:
#   docker pull node:20-alpine && \
#     docker inspect --format='{{index .RepoDigests 0}}' node:20-alpine
# Why pinned: prevents `docker build --pull` from fetching newer
# upstream layers between source-unchanged builds, which would
# produce a different image digest and force unnecessary container
# recreates on operator installs. See CLAUDE.md § Per-service
# path-filter contract.
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS agent-builder
WORKDIR /build

# Layer-cache npm install separately from source.
COPY mcp/agent/package.json mcp/agent/package-lock.json* ./
RUN npm ci

COPY mcp/agent/ .

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build
# Output lands at /build/.next/standalone (per next.config.ts:
# `output: 'standalone'`) plus /build/.next/static and /build/public.

# ─────────────────────────────────────────────────────────────────
# Stage 2 — Python deps for the embedded MCP
# ─────────────────────────────────────────────────────────────────
# Digest-pinned (see comment above the node base).
FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461 AS mcp-deps
WORKDIR /mcp-build

# Build deps for any native wheels in the embedded-MCP requirements.txt
# (cryptography needs a C toolchain on linux/arm64). Stripped from runtime.
RUN apt-get update \
  && apt-get install -y --no-install-recommends gcc python3-dev libffi-dev \
  && rm -rf /var/lib/apt/lists/*

COPY bundles/spark/mcp/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
# Installed to /root/.local/{lib,bin}; copied wholesale into runtime.

# ─────────────────────────────────────────────────────────────────
# Stage 3 — Combined runtime
# ─────────────────────────────────────────────────────────────────
# Digest-pinned (see comment above the node base).
FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461 AS runtime

# Install Node.js 20 alongside Python, plus curl for the entrypoint's
# MCP-readiness probe + tini for proper PID-1 signal handling.
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
       curl ca-certificates gnupg tini \
  && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*

# Bake Claude Code CLI into the image so /api/chat/cli's first
# invocation doesn't pay the npx download cost. Auth flows through
# ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN at runtime (resolved
# by lib/anthropic-credentials.ts from ProviderStore + env fallback).
# Pinning the version keeps image-digest stability across rebuilds —
# operators upgrading get a deliberate version bump, not a surprise
# from an upstream npm publish.
RUN npm install -g @anthropic-ai/claude-code@^1.0.0 \
  && npm cache clean --force

WORKDIR /app

# Bring Python deps in (installed via --user → /root/.local).
COPY --from=mcp-deps /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy the bundle's MCP source + assets the runtime mounts at boot.
COPY bundles/spark/mcp/src      /app/mcp/src
COPY bundles/spark/mcp/skills   /app/mcp/skills-default
COPY bundles/spark/mcp/resources /app/mcp/resources
COPY bundles/spark/mcp/tests    /app/mcp/tests
# The full bundle directory is also bind-mounted at runtime (see
# docker-compose.yml volumes). The COPY above is for cases where
# someone runs the image without compose.
COPY bundles/spark              /app/bundle

# Copy Next.js standalone build artifacts.
COPY --from=agent-builder /build/.next/standalone /app
COPY --from=agent-builder /build/.next/static /app/.next/static
COPY --from=agent-builder /build/public /app/public

# The combined entrypoint that starts MCP + Next.js together.
COPY mcp/agent/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# tls-proxy.js — TLS-terminating reverse proxy used by entrypoint.sh
# when SSL_CERT_PEM/SSL_KEY_PEM is set. Lives outside Next.js's
# standalone bundle so a separate COPY is needed (next.config.ts's
# `output: 'standalone'` only includes files Next.js itself imports).
# See entrypoint.sh's TLS branch + mcp/agent/tls-proxy.js for details.
COPY mcp/agent/tls-proxy.js /app/tls-proxy.js

# reset-admin CLI invoked from the host via
# `docker exec -it phantom_agent node /app/cli/reset-admin.mjs`.
# The host-side wrapper at scripts/reset_admin.sh shells out to this
# Node ESM module. Pure ESM; no transpilation; uses the Node baked
# into the agent image already.
COPY mcp/agent/cli /app/cli
RUN chmod +x /app/cli/reset-admin.mjs

# Defaults — kept image-side because they're true infrastructure
# constants, not operator config. The MCP_* transport defaults are
# DELIBERATELY NOT set here: the Settings class's stdio default is
# what bare-runtime tests assert against, and the docker-compose
# layer is the right place to set streamable-http for the running
# stack (see docker-compose.yml's phantom-agent.environment with
# `MCP_TRANSPORT=${MCP_TRANSPORT:-streamable-http}`).
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
ENV BUNDLE_ROOT=/app/bundle
ENV DATA_ROOT=/app/data
# PYTHONPATH must include both /app/mcp/src (the MCP server's own
# code) AND /app/bundle (so the bundle's connector source resolves
# as `connectors.<id>.src.connector` per connector.yaml's
# source.entrypoint format).
ENV PYTHONPATH=/app/mcp/src:/app/bundle
ENV PYTHONUNBUFFERED=1

EXPOSE 3000 8080

# tini reaps zombies and forwards signals to our shell entrypoint,
# which in turn forwards them to the MCP + Next.js child processes.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/entrypoint.sh"]
