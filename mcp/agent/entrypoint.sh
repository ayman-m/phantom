#!/usr/bin/env bash
# Combined phantom-agent entrypoint.
#
# Spawns the bundle's embedded MCP server alongside the Next.js agent
# UI in the same container — matching the spark-agents v1.2 bundle
# design where embeddedMcp is part of the agent's trust boundary, not
# a sibling docker-compose service.
#
# Lifecycle:
#   1. Bootstrap skills (if /app/skills is empty/new)
#   2. Generate MCP_TOKEN if not provided (internal coordination only)
#   3. Start the MCP in the background, wait for /ping/ to return 200
#   4. Start Next.js in the foreground, with signal forwarding so a
#      docker stop on the container brings both processes down cleanly
#   5. If either child exits unexpectedly, kill the other and exit
#      with the dead child's exit code (so docker-compose's restart
#      policy can recover the whole agent as a unit)

set -euo pipefail

log() { printf '[entrypoint] %s\n' "$*"; }

# ─── 1. Skills bootstrap ────────────────────────────────────────
#
# Per-release marker-driven merge.
#
# Stamps `${SKILLS_DIR}/.seeded_version` with PHANTOM_VERSION on every
# successful seed/merge. Subsequent boots compare the marker against
# the running release; if they differ, the new release's image-baked
# defaults get merged into the volume (cp -r — overwrites same-named
# files but does NOT delete files only present in the volume, so
# operator-created skills are preserved). If the marker matches,
# the bootstrap is a no-op — operator deletions of default skills
# stick across same-version restarts.
#
# Three trigger paths:
#   FORCE_SKILLS_SYNC=1         operator override (always merges)
#   marker missing or stale     per-release auto-merge (the common
#                               case for upgrade installs — no docker
#                               exec workaround needed)
#   volume empty                fresh-install seed
#
# Without the marker-driven flow (a "volume empty" branch alone), new
# image-default skills would never propagate to existing installs
# without manual `docker exec cp -r ...`. The marker makes
# per-release skill rollouts automatic.
#
# Operator deletions across releases:
#   Delete a default skill on release N + restart same release → marker
#   matches → no merge → deletion sticks. Upgrade to release N+1 → marker
#   stale → merge fires → deleted-but-still-in-image skill comes back.
#   That's the right semantic: upgrading to a new release is opting
#   into its default set. To permanently retire a default, modify the
#   image's skills-default directory or use the bundle's denylist
#   surface (planned).
SKILLS_DIR="/app/skills"
SKILLS_DEFAULT="/app/mcp/skills-default"
SKILLS_MARKER="${SKILLS_DIR}/.seeded_version"
mkdir -p "$SKILLS_DIR"

# Read the running version from env. Falls back to "dev" for local
# builds with no PHANTOM_VERSION baked in; this is fine because
# repeat dev-mode boots will all share the "dev" marker and not
# re-merge unless explicitly forced.
RUNNING_VERSION="${PHANTOM_VERSION:-dev}"
SEEDED_VERSION="$(cat "$SKILLS_MARKER" 2>/dev/null || echo "")"

skills_seed() {
  # Single seed/merge implementation used by all three trigger paths.
  # cp -r is intentionally NOT --update; we want image-default
  # collisions to overwrite (the operator opted into the new
  # release's defaults by upgrading). Non-collision files in the
  # volume (operator-created skills, retired-but-still-on-disk
  # legacy ones) stay because cp doesn't touch them.
  #
  # Deletion-denylist enforcement. Without it, operator-deleted
  # image-default skills would come back on every release upgrade because
  # the marker-mismatch path fires this merge and `cp -r` blindly restores
  # every image-default. The UI's delete-skill action moves the file
  # to `.deleted/<basename>.md` (basename only — category collapses),
  # so we now treat that directory as a per-operator denylist: skills
  # whose basename appears in `.deleted/` get removed from the active
  # category dirs after the merge runs. Customer-created skills with
  # no image-default counterpart are unaffected (they don't appear in
  # `skills-default/`, so they're not restored, so they don't need to
  # be re-removed). The operator's `.deleted/` directory thus becomes
  # a stable denylist that survives release upgrades — which is what
  # the operator's mental model of "I deleted this" implies.
  cp -r "$SKILLS_DEFAULT"/* "$SKILLS_DIR"/ 2>/dev/null || true

  local DENYLIST
  DENYLIST="$(mktemp)"
  if [ -d "$SKILLS_DIR/.deleted" ]; then
    # Each file in .deleted/ is a basename like alpha_and_omega.md.
    # The delete_skill function in skills_crud.py renames using just
    # skill_path.name (basename only), so categories collapse here.
    (cd "$SKILLS_DIR/.deleted" && find . -maxdepth 1 -name '*.md' -exec basename {} \;) \
      > "$DENYLIST" 2>/dev/null || true
  fi

  if [ -s "$DENYLIST" ]; then
    local denied_count=0
    while IFS= read -r dbasename; do
      [ -z "$dbasename" ] && continue
      # Remove any restored copy of this basename from the active
      # category dirs (foundation, scenarios, validation, workflows).
      # Skip .deleted/ itself (don't touch the backup) and plugins/
      # (vendor-managed — operator can't delete plugin skills via the
      # standard delete-skill UI, so deletion-by-basename in that tree
      # could surprise plugin authors).
      find "$SKILLS_DIR" -maxdepth 2 -name "$dbasename" \
        ! -path "$SKILLS_DIR/.deleted/*" \
        ! -path "$SKILLS_DIR/plugins/*" \
        -type f -delete 2>/dev/null && denied_count=$((denied_count + 1))
    done < "$DENYLIST"
    log "deletion-denylist enforced ($(wc -l < "$DENYLIST" | tr -d ' ') entries; restored copies removed)"
  fi
  rm -f "$DENYLIST"

  printf '%s\n' "$RUNNING_VERSION" > "$SKILLS_MARKER" 2>/dev/null || true
}

if [ "${FORCE_SKILLS_SYNC:-}" = "1" ]; then
  log "FORCE_SKILLS_SYNC=1 — re-seeding skills from $SKILLS_DEFAULT (marker → ${RUNNING_VERSION})"
  skills_seed
elif [ -z "$(ls -A "$SKILLS_DIR" 2>/dev/null || true)" ]; then
  log "skills directory empty — seeding from $SKILLS_DEFAULT (marker → ${RUNNING_VERSION})"
  skills_seed
elif [ "$SEEDED_VERSION" != "$RUNNING_VERSION" ]; then
  log "skills volume seeded for '${SEEDED_VERSION:-(none)}'; merging ${RUNNING_VERSION} defaults from $SKILLS_DEFAULT"
  skills_seed
else
  log "skills volume already at ${RUNNING_VERSION} (marker matches; no merge)"
fi

# ─── 2. MCP_TOKEN bootstrap ─────────────────────────────────────
# Bundle-internal coordination between the MCP and the Next.js side.
# When unset, generate a per-boot random value (rotates on every
# restart, which is fine for a single-process container — the Next.js
# side reads the same env var).
if [ -z "${MCP_TOKEN:-}" ]; then
  MCP_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  export MCP_TOKEN
  log "generated MCP_TOKEN (length ${#MCP_TOKEN})"
else
  log "using MCP_TOKEN from environment (length ${#MCP_TOKEN})"
fi

# ─── 2.1. Operator settings ────────────────────────────────────
# There is no setup page and no generated env file. Operator
# settings live in their canonical stores (SecretStore for credentials,
# settings_store for non-secret config); entrypoint reads bundle-internal
# coordination directly from container env above.

# ─── 2.2. TLS-by-default auto-generation ───────────────────────
# Requirement: the stack MUST always have a TLS cert available. This
# covers two scenarios:
#   1. Fresh install: setup page needs HTTPS (chicken-and-egg —
#      operator picks TLS mode through the page, page must already
#      be TLS).
#   2. Upgrade: an install created before TLS-by-default carries a
#      setup.json with no cert; auto-gen on next boot brings it up
#      to spec without operator intervention.
#
# Mechanism: 2048-bit self-signed cert written to /tls/cert.pem +
# /tls/key.pem on the shared phantom_tls volume. xlog and caldera
# read those same files (ro mount) at startup; the agent reads them
# via SSL_CERT_FILE/SSL_KEY_FILE.
#
# When the operator picks "custom" TLS in the setup form, /api/setup
# overwrites /tls/{cert,key}.pem with their PEM. When they pick
# "self-signed", /api/setup keeps the auto-generated material. Either
# way /tls/ is populated, so this entrypoint reuses it on next boot.
PHANTOM_AUTO_TLS=0
TLS_DIR="/tls"
TLS_CERT="$TLS_DIR/cert.pem"
TLS_KEY="$TLS_DIR/key.pem"
SETUP_JSON="/app/runtime/setup.json"

# The shared phantom_tls volume is the single source of truth for
# certs across the stack. When the agent writes /tls/cert.pem +
# /tls/key.pem, xlog (ro mount) reads them at startup and serves
# HTTPS; same for caldera. The agent itself reads them via SSL_CERT_FILE
# below.
#
# Auto-gen runs whenever /tls/ doesn't already have a valid cert + key
# pair. setup.json's existence is intentionally NOT part of the gate:
# TLS-by-default means a cert is always available, irrespective of
# whether the operator has ever opened the setup form. This also fixes
# the upgrade path — installs created before the TLS-by-default change
# carry a legacy setup.json with no cert; on next boot the agent
# generates one and the whole stack moves to HTTPS without operator
# intervention.
#
# Operator opt-out doesn't exist any more: the setup form has no
# "HTTP only" option, and the API route at /api/setup either reuses
# the auto-cert (self-signed mode) or writes the operator's PEM
# (custom mode). Either way /tls/cert.pem is populated.

mkdir -p "$TLS_DIR"

if [ ! -f "$TLS_CERT" ] || [ ! -f "$TLS_KEY" ]; then
  log "no TLS cert at $TLS_DIR/ — generating self-signed cert (TLS-by-default)"
  # 2048-bit (vs the operator-facing 4096-bit) since this is short-
  # lived bootstrap material; gets replaced when the operator picks
  # custom TLS via the setup form. Fast generation (sub-second) keeps
  # boot responsive on weak VMs.
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
    -keyout "$TLS_KEY" -out "$TLS_CERT" \
    -subj "/CN=phantom-setup/O=Phantom/OU=Auto-generated" \
    -addext "subjectAltName=DNS:localhost,DNS:phantom-agent,DNS:xlog,DNS:caldera,IP:127.0.0.1" \
    -addext "extendedKeyUsage=serverAuth" \
    2>/dev/null
  chmod 600 "$TLS_KEY"
  chmod 644 "$TLS_CERT"
  log "wrote $TLS_CERT + $TLS_KEY (shared volume — xlog/caldera will read on next restart)"
  # PHANTOM_AUTO_TLS=1 means "this boot generated the cert," which
  # implies xlog/caldera in the same compose-up cycle haven't seen
  # the cert yet (they started in parallel). The XLOG_URL flip below
  # honors this: on the generation boot we keep xlog on http://, then
  # on the next compose restart xlog reads the cert and the flip kicks
  # in.
  PHANTOM_AUTO_TLS=1
else
  log "reusing existing TLS cert at $TLS_CERT (shared volume)"
fi

# When /tls/ has cert files, point the agent's listener at them via
# the env vars its tls-proxy + MCP both consume. This unifies the
# auto-gen path and operator-supplied path (the API route writes to
# the same /tls/cert.pem on submit).
#
# IMPORTANT — env name choice: we deliberately use PHANTOM_TLS_CERT_FILE
# (not SSL_CERT_FILE) because OpenSSL and Python's ssl module BOTH read
# SSL_CERT_FILE as the path to the trust-store PEM bundle for outbound
# TLS verification. Exporting our single self-signed listener cert as
# SSL_CERT_FILE replaces Python's CA bundle, which makes every outbound
# HTTPS call — Vertex AI embeddings, Gemini, XSIAM PAPI — fail with
# CERTIFICATE_VERIFY_FAILED (since none of those servers are signed by
# our self-signed cert). PHANTOM_TLS_CERT_FILE is a private name only
# our own tls-proxy.js + MCP config read, so it doesn't pollute the
# Python ssl module's trust-store discovery.
if [ -f "$TLS_CERT" ] && [ -f "$TLS_KEY" ]; then
  export PHANTOM_TLS_CERT_FILE="$TLS_CERT"
  export PHANTOM_TLS_KEY_FILE="$TLS_KEY"
  # NODE_EXTRA_CA_CERTS tells Node's https/fetch to trust the self-
  # signed cert in addition to the system CA store. Without this, the
  # agent's own outbound calls to https://localhost:8080 (the embedded
  # MCP — bundle schema fetch, setup proxy, etc.) fail with TLS-handshake
  # errors because Node doesn't recognize the cert chain. Setting this
  # before Next.js starts is essential — Node only reads the var at
  # process boot, not on each fetch. Note: NODE_EXTRA_CA_CERTS *appends*
  # to the system CA store, unlike SSL_CERT_FILE which *replaces* it,
  # so it's safe to use here.
  export NODE_EXTRA_CA_CERTS="$TLS_CERT"
fi
export PHANTOM_AUTO_TLS

# ─── 2.5. Seed admin auth defaults (idempotent) ─────────────────
#
# Boot-time seeding of /ui/auth/admin/password_hash in the
# SecretStore. The default password lives in
# PHANTOM_DEFAULT_ADMIN_PASSWORD (sourced from .env), not in the image.
# No credential is baked anywhere in any Phantom image.
#
# Behavior:
#   - If SecretStore already holds a password hash for the `admin`
#     user, this is a no-op (returns "already_initialized"). The
#     env var is NOT consulted on already-initialized stores —
#     installs that don't carry the env var still work.
#   - If no hash exists (fresh volume), seeds the PBKDF2 hash of
#     $PHANTOM_DEFAULT_ADMIN_PASSWORD, and sets the
#     `credentials_changed=false` flag so the UI shows the "change
#     default password" banner on first login.
#   - If no hash exists AND $PHANTOM_DEFAULT_ADMIN_PASSWORD is unset
#     or empty, the Python seed call raises — the agent refuses to
#     boot with an empty admin credential. Fail-loud per the
#     canonical-state discipline; operator must re-run the installer
#     (which auto-generates the value into .env) or set the env var
#     manually and restart.
#
# Failure mode: if SecretStore can't be initialized (KEK missing,
# data volume read-only, etc.), this command EXITS the container.
# We fail loud rather than fall back to insecure defaults: a silent
# env-plaintext fallback would hide KEK mismatches and empty
# credentials. Loud failure tells the operator exactly what to fix.
#
# Runs BEFORE the MCP server boots so by the time MCP starts, auth.v1
# is fully initialized.
log "auth_store: checking for first-boot seeding..."
SEED_OUTPUT=$(PYTHONPATH=/app/mcp/src python3 -c '
import os, sys, traceback
try:
    from usecase.auth_store import auth_store
    default_pw = os.environ.get("PHANTOM_DEFAULT_ADMIN_PASSWORD", "").strip()
    seeded = auth_store().seed_admin_defaults_if_empty("admin", default_pw)
    print("seeded" if seeded else "already_initialized")
except Exception as exc:
    print("ERROR: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
' 2>&1) || {
  log "FATAL: auth_store seeding failed — refusing to start"
  log "Cause: SecretStore is not initialized or is unreachable, OR"
  log "       fresh install with PHANTOM_DEFAULT_ADMIN_PASSWORD unset."
  log "Inspect the trace above. Common fixes:"
  log "  - Volume mount missing: confirm /app/data is mounted"
  log "  - KEK mismatch: did the operator restore from a backup with a different PHANTOM_SECRET_KEK?"
  log "  - Empty PHANTOM_DEFAULT_ADMIN_PASSWORD on a fresh install:"
  log "      re-run /opt/phantom/phantom-installer — it auto-generates"
  log "      this value into /opt/phantom/.env."
  log "  - Disk full / permissions: check container fs"
  printf '%s\n' "$SEED_OUTPUT"
  exit 1
}

if [ "$SEED_OUTPUT" = "seeded" ]; then
  # Print the actual seeded credentials so an operator who lost the
  # installer-output banner can still recover from docker logs. This
  # is the SAME trust level as .env (root-on-host can read either);
  # printed once per fresh seed only — subsequent boots take the
  # already_initialized branch and emit nothing.
  log "╭──────────────────────────────────────────────────────────────────╮"
  log "│  FIRST BOOT — default admin credentials                          │"
  log "│                                                                  │"
  log "│    username:  admin                                              │"
  log "│    password:  ${PHANTOM_DEFAULT_ADMIN_PASSWORD}"
  log "│                                                                  │"
  log "│  This value is also in /opt/phantom/.env under                   │"
  log "│  PHANTOM_DEFAULT_ADMIN_PASSWORD. After you change the password   │"
  log "│  at /profile on first login, this default is never consulted.    │"
  log "│  If you lose the value, run from the host:                       │"
  log "│    sudo /opt/phantom/phantom-reset-admin-password                │"
  log "╰──────────────────────────────────────────────────────────────────╯"
elif [ "$SEED_OUTPUT" = "already_initialized" ]; then
  log "auth_store: SecretStore already holds admin credentials (no seed needed)"
else
  log "auth_store: unexpected seed output: $SEED_OUTPUT"
fi

# ─── 2.6. Pre-compute TLS env BEFORE MCP boots ─────────────────
#
# The auth_store seeding step (section 2.5 above) runs before this one.
#
# Process env is frozen at exec, so every env var that MCP's Python
# code reads (XLOG_URL, MCP_URL, PHANTOM_TLS_VERIFY,
# PHANTOM_AGENT_INTERNAL_URL, PHANTOM_TLS_ENABLED) must be in its
# final shape before `python -u /app/mcp/src/main.py &` is invoked
# below. MCP starts BEFORE the Next.js spawn block, so the TLS-aware
# values are computed here, which makes both processes see consistent
# URLs. Otherwise:
#   * the JobScheduler's chat dispatch would fall back to
#     localhost:3000 (the TLS proxy) and get disconnected.
#   * phantom_create_data_worker tool calls would reach xlog via
#     http://, and xlog's TLS listener would disconnect mid-handshake
#     ("Server disconnected without sending a response.").
PHANTOM_TLS_ENABLED=0
if [[ -n "${PHANTOM_TLS_CERT_FILE:-}" || -n "${SSL_CERT_FILE:-}" || -n "${SSL_CERT_PEM:-}" ]] \
   && [[ -n "${PHANTOM_TLS_KEY_FILE:-}"  || -n "${SSL_KEY_FILE:-}"  || -n "${SSL_KEY_PEM:-}"  ]]; then
  PHANTOM_TLS_ENABLED=1
fi
export PHANTOM_TLS_ENABLED

if [[ "$PHANTOM_TLS_ENABLED" == "1" ]]; then
  # MCP_URL ALWAYS flips when TLS is on — the embedded MCP shares the
  # same cert/key as the agent's listener, so it serves HTTPS too.
  # This is intra-process and known-correct (same container, same
  # cert). Not a workaround — a deterministic local-only flip.
  export MCP_URL="${MCP_URL/http:/https:}"

  # There is no XLOG_URL probe-then-flip block. Per the
  # canonical setup spec at /help/architecture#setup-wiring, the
  # InstanceStore is the single source of truth for connector URLs.
  # Operators edit baseUrl via /connectors and the next read sees
  # the new value. Both the agent's runtime-config (lib/xlog-url.ts)
  # and the MCP's lifespan resolver (service/phantom_mcp/server.py)
  # read from the InstanceStore on every invocation. No silent env
  # mutation, no probe-then-flip, no hidden self-healing.
  #
  # If xlog flips protocol after a TLS rollout, /api/agent/health
  # surfaces the verbatim failure and the operator updates the
  # InstanceStore via /connectors. That's the spec.

  # CALDERA_URL stays http:// — caldera doesn't terminate TLS yet.
  export PHANTOM_TLS_VERIFY="${PHANTOM_TLS_VERIFY:-0}"

  # MCP→Next.js loopback: Next.js binds port 3001 (plain HTTP) when
  # tls-proxy.js owns 3000 (HTTPS). MCP's internal calls (chat
  # dispatcher, etc.) must target 3001 directly, not 3000.
  export PHANTOM_AGENT_INTERNAL_URL="http://127.0.0.1:3001"
fi

# ─── 3. Start the embedded MCP ──────────────────────────────────
log "starting embedded MCP server (transport=${MCP_TRANSPORT:-streamable-http} port=${MCP_PORT:-8080})..."
python -u /app/mcp/src/main.py &
MCP_PID=$!

# Pick the right probe URL/scheme based on whether SSL is configured.
# When PHANTOM_TLS_CERT_FILE (or legacy SSL_CERT_FILE / inline PEM) is
# set, the MCP terminates TLS on the same port, so http:// would fail
# TLS handshake. -k is needed because self-signed certs don't validate
# against the system CA store.
if [[ -n "${PHANTOM_TLS_CERT_FILE:-}" || -n "${SSL_CERT_FILE:-}" || -n "${SSL_CERT_PEM:-}" ]]; then
  MCP_PROBE_URL="https://127.0.0.1:${MCP_PORT:-8080}/ping/"
  MCP_PROBE_OPTS="-k"
else
  MCP_PROBE_URL="http://127.0.0.1:${MCP_PORT:-8080}/ping/"
  MCP_PROBE_OPTS=""
fi

# Wait for MCP to be ready (or fail fast if it crashes during init).
log "waiting for MCP /ping/ readiness ($MCP_PROBE_URL)..."
MCP_READY=0
for i in $(seq 1 60); do
  if curl -sf $MCP_PROBE_OPTS "$MCP_PROBE_URL" >/dev/null 2>&1; then
    MCP_READY=1
    log "MCP ready after ${i}s"
    break
  fi
  if ! kill -0 "$MCP_PID" 2>/dev/null; then
    log "MCP exited during startup — see logs above for the traceback"
    exit 1
  fi
  sleep 1
done
if [ "$MCP_READY" != "1" ]; then
  log "MCP did not become ready within 60s; killing and exiting"
  kill -TERM "$MCP_PID" 2>/dev/null || true
  exit 1
fi

# ─── 4. Start Next.js (with optional TLS termination) ───────────
# When SSL is configured (either SSL_CERT_FILE/SSL_KEY_FILE paths or
# SSL_CERT_PEM/SSL_KEY_PEM inline PEM), the agent serves HTTPS via a
# tiny TLS-terminating proxy in front of Next.js:
#
#   browser → tls-proxy.js (HTTPS, public port 3000)
#                       │
#                       └──→ Next.js (HTTP, loopback, port 3001)
#
# tls-proxy.js is built-in-Node only (no npm deps); see /app/tls-proxy.js
# for details. It pipes streams through unchanged so SSE responses
# (e.g. the in-app updater progress stream) flow without buffering.
#
# When SSL is NOT configured, Next.js binds port 3000 directly as before.
#
# When TLS is on:
#   * Internal compose-network URLs flip to https:// (XLOG_URL,
#     CALDERA_URL, MCP_URL) so the agent's connectors talk TLS to
#     their respective services. Each service terminates its own TLS
#     using the same cert/key material.
#   * PHANTOM_TLS_VERIFY defaults to "0" — agent's HTTP clients skip
#     cert verification on internal calls. Acceptable for self-signed
#     mode; flip to "1" when operators install certs from a real CA.

cd /app

PROXY_PID=""

if [[ "$PHANTOM_TLS_ENABLED" == "1" ]]; then
  # PHANTOM_TLS_ENABLED + URL flips were set in section 2.4 (BEFORE
  # MCP boot) so MCP inherits the right values. Just log the resolved
  # state here so operators can confirm via `docker compose logs`.
  log "TLS enabled — internal URLs already flipped (see env block above)"
  log "  XLOG_URL=$XLOG_URL"
  log "  MCP_URL=$MCP_URL"
  log "  CALDERA_URL=$CALDERA_URL  (stays http:// — caldera TLS pending)"
  log "  PHANTOM_TLS_VERIFY=$PHANTOM_TLS_VERIFY (0 = skip verify, 1 = enforce)"
  log "  PHANTOM_AUTO_TLS=$PHANTOM_AUTO_TLS"

  # Next.js on internal HTTP port (loopback).
  log "starting Next.js on internal HTTP port 3001..."
  PORT=3001 HOSTNAME=127.0.0.1 node server.js &
  NODE_PID=$!

  # PHANTOM_AGENT_INTERNAL_URL is exported earlier (before MCP boot)
  # so MCP's JobScheduler picks it up at startup. Re-asserting it here
  # would be a no-op; documenting the dependency is sufficient.
  # ──── Why we need it (kept here for searchability) ────
  # SSR internal calls (server component fetching its own /api/agent/*
  # handlers) need an absolute URL because Node fetch can't resolve
  # relative paths. The default fallback is http://localhost:3000 —
  # which is wrong in TLS mode (3000 is the tls-proxy, HTTPS-only;
  # SSR fetch with http:// hits TLS handshake, hangs ~60s, fails as
  # ERR_SSL_HTTP_REQUEST). Pointing PHANTOM_AGENT_INTERNAL_URL at the
  # internal Next.js port (3001, plain HTTP) bypasses the proxy
  # entirely for in-process round-trips. External browser traffic
  # still goes through tls-proxy and is unaffected.

  # Wait for Next.js to actually be ready before starting the proxy —
  # otherwise the first proxied request hits "connection refused."
  for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:3001/api/auth/status" >/dev/null 2>&1; then
      log "Next.js ready (internal :3001)"
      break
    fi
    if ! kill -0 "$NODE_PID" 2>/dev/null; then
      log "Next.js exited during startup"
      exit 1
    fi
    sleep 1
  done

  log "starting tls-proxy.js on public HTTPS port ${PORT:-3000}..."
  PHANTOM_TLS_PORT="${PORT:-3000}" \
  PHANTOM_TLS_BACKEND_PORT=3001 \
  PHANTOM_TLS_BACKEND_HOST=127.0.0.1 \
    node /app/tls-proxy.js &
  PROXY_PID=$!
else
  log "TLS not configured — starting Next.js on port ${PORT:-3000} (HTTP)"
  node server.js &
  NODE_PID=$!
fi

# ─── 5. Signal forwarding + child supervision ───────────────────
shutdown() {
  local sig="$1"
  log "received SIG${sig} — forwarding to children"
  kill -TERM "$MCP_PID" "$NODE_PID" ${PROXY_PID:-} 2>/dev/null || true
  wait "$MCP_PID" 2>/dev/null || true
  wait "$NODE_PID" 2>/dev/null || true
  [[ -n "${PROXY_PID:-}" ]] && wait "$PROXY_PID" 2>/dev/null || true
  exit 0
}
trap 'shutdown TERM' TERM
trap 'shutdown INT' INT

# Wait for whichever child exits first. `wait -n` is bash-only.
if [[ -n "${PROXY_PID:-}" ]]; then
  log "all children running (mcp=$MCP_PID node=$NODE_PID proxy=$PROXY_PID); supervising"
  set +e
  wait -n "$MCP_PID" "$NODE_PID" "$PROXY_PID"
  DEAD_CHILD_EXIT=$?
  set -e
else
  log "all children running (mcp=$MCP_PID node=$NODE_PID); supervising"
  set +e
  wait -n "$MCP_PID" "$NODE_PID"
  DEAD_CHILD_EXIT=$?
  set -e
fi

# Identify which one died and report.
if ! kill -0 "$MCP_PID" 2>/dev/null; then
  log "MCP (pid $MCP_PID) exited with code $DEAD_CHILD_EXIT"
elif ! kill -0 "$NODE_PID" 2>/dev/null; then
  log "Next.js (pid $NODE_PID) exited with code $DEAD_CHILD_EXIT"
elif [[ -n "${PROXY_PID:-}" ]] && ! kill -0 "$PROXY_PID" 2>/dev/null; then
  log "tls-proxy (pid $PROXY_PID) exited with code $DEAD_CHILD_EXIT"
fi

# Bring the others down so docker-compose's restart policy can
# recover the whole agent as a unit.
log "stopping the other child(ren)"
kill -TERM "$MCP_PID" "$NODE_PID" ${PROXY_PID:-} 2>/dev/null || true
wait 2>/dev/null || true
exit "$DEAD_CHILD_EXIT"
