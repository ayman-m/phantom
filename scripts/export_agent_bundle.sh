#!/usr/bin/env bash
set -euo pipefail

# Phantom agent bundle exporter.
#
# Two output modes (toggle via BUNDLE_MODE):
#
#   full       (default) — all-in-one archive: every Docker image
#              (xlog + caldera + phantom-agent), the full
#              docker-compose.yml, scenarios, full bundle source,
#              every helper script. ~2.3 GB tarball.
#
#   agent-only — slim split-deploy archive: ONLY the phantom-agent
#              image and `docker-compose.agent-only.yml`. The
#              recipient runs the agent on their machine and
#              configures it at first-run to point at remote
#              xlog/caldera/XSIAM via the setup form. ~1.5 GB
#              tarball (no xlog/caldera images, no scenarios,
#              no xlog config). See docs/split-deploy.md.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE_MODE="${BUNDLE_MODE:-full}"
BUNDLE_NAME="${BUNDLE_NAME:-phantom-agent-bundle-$BUNDLE_MODE}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT_DIR/dist/$BUNDLE_NAME}"
ARCHIVE_PATH="${ARCHIVE_PATH:-$ROOT_DIR/dist/$BUNDLE_NAME.tar.gz}"
INCLUDE_STATE="${INCLUDE_STATE:-0}"
REQUIRE_MCP_TOOL_SNAPSHOT="${REQUIRE_MCP_TOOL_SNAPSHOT:-0}"

case "$BUNDLE_MODE" in
  full)
    IMAGES=(
      "xlog:local|xlog-local.tar"
      "phantom-agent:local|phantom-agent-local.tar"
      "caldera:local|caldera-local.tar"
    )
    ;;
  agent-only)
    # Only the agent image. xlog/caldera assumed to run on a
    # separate host; their URLs come from the setup form.
    IMAGES=(
      "phantom-agent:local|phantom-agent-local.tar"
    )
    ;;
  *)
    printf 'Unknown BUNDLE_MODE: %s (must be "full" or "agent-only")\n' "$BUNDLE_MODE" >&2
    exit 2
    ;;
esac

cd "$ROOT_DIR"

rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/images"

# Always-included artifacts: top-level pointer, observability/secret
# bindings, scripts, docs, a2ui assets, logos. Bundle SOURCE itself is
# mode-specific (full mode ships the whole tree; agent-only ships only
# the manifest + verification script — the rest is baked into the
# image already, so duplicating it on disk is wasted bytes).
cp bundles/phantom-agent.bundle.yaml "$OUTPUT_DIR/agent-bundle.yaml"
cp bundles/tool-catalog.yaml "$OUTPUT_DIR/tool-catalog.yaml"
cp bundles/secret-bindings.example.yaml "$OUTPUT_DIR/secret-bindings.example.yaml"
cp bundles/observability.contract.yaml "$OUTPUT_DIR/observability.contract.yaml"

mkdir -p "$OUTPUT_DIR/bundles" "$OUTPUT_DIR/logos" "$OUTPUT_DIR/docs" "$OUTPUT_DIR/scripts" "$OUTPUT_DIR/a2ui"
cp -R logos/. "$OUTPUT_DIR/logos/"
cp -R a2ui/. "$OUTPUT_DIR/a2ui/"
cp docs/agent-bundle-architecture.md "$OUTPUT_DIR/docs/agent-bundle-architecture.md"
# Recipient-facing split-deploy guide (always shipped — informative
# even when the recipient went with the full bundle).
if [ -f "docs/split-deploy.md" ]; then
  cp docs/split-deploy.md "$OUTPUT_DIR/docs/split-deploy.md"
fi
cp scripts/agent_lifecycle.sh "$OUTPUT_DIR/scripts/agent_lifecycle.sh"
cp scripts/install_agent_bundle.sh "$OUTPUT_DIR/scripts/install_agent_bundle.sh"
cp scripts/import_agent_bundle.sh "$OUTPUT_DIR/scripts/import_agent_bundle.sh"
cp scripts/generate_mcp_tool_snapshot.py "$OUTPUT_DIR/scripts/generate_mcp_tool_snapshot.py"
cp scripts/generate_bundle_manifest.py "$OUTPUT_DIR/scripts/generate_bundle_manifest.py"
cp scripts/verify_agent_bundle.py "$OUTPUT_DIR/scripts/verify_agent_bundle.py"
cp scripts/materialize_secret_bindings.py "$OUTPUT_DIR/scripts/materialize_secret_bindings.py"
cp scripts/validate_tool_snapshot.py "$OUTPUT_DIR/scripts/validate_tool_snapshot.py"
cp scripts/bind_secret_provider.py "$OUTPUT_DIR/scripts/bind_secret_provider.py"
# Operator backup/restore tooling — codifies the manual tar
# procedure documented in docs/split-deploy.md so operators have
# a sha256-verified, manifest-described archive instead of a
# raw `tar czf` invocation.
cp scripts/backup_phantom.sh "$OUTPUT_DIR/scripts/backup_phantom.sh"
cp scripts/restore_phantom.sh "$OUTPUT_DIR/scripts/restore_phantom.sh"

# Mode-specific artifacts: compose recipe, bundle source, xlog config,
# scenarios, source-dependent scripts.
if [ "$BUNDLE_MODE" = "full" ]; then
  cp docker-compose.yml "$OUTPUT_DIR/docker-compose.yml"
  # Full bundle ships the entire bundle source for offline development
  # against the same agent declaration that's baked into the image.
  cp -R bundles/spark "$OUTPUT_DIR/bundles/spark"
  # config.yml lives at xlog/config.yml (the log-gen service is xlog).
  cp xlog/config.yml "$OUTPUT_DIR/config.yml"
  mkdir -p "$OUTPUT_DIR/scenarios"
  cp -R xlog/scenarios/ready "$OUTPUT_DIR/scenarios/ready"
  # These two scripts re-export / validate the bundle source tree —
  # only meaningful when the source is present (full mode).
  cp scripts/validate_spark_bundle.py "$OUTPUT_DIR/scripts/validate_spark_bundle.py"
  cp scripts/export_spark_agent_bundle.sh "$OUTPUT_DIR/scripts/export_spark_agent_bundle.sh"
else
  # agent-only: bundle source is fully baked into the phantom-agent
  # image at /app/bundle. Ship only what the operator needs on the
  # host: the manifest (transparency about what the agent declares)
  # and the smoke-test script (verification flow per docs/split-deploy.md).
  cp docker-compose.agent-only.yml "$OUTPUT_DIR/docker-compose.yml"
  mkdir -p "$OUTPUT_DIR/bundles/spark"
  cp bundles/spark/manifest.yaml "$OUTPUT_DIR/bundles/spark/manifest.yaml"
  if [ -f "bundles/spark/README.md" ]; then
    cp bundles/spark/README.md "$OUTPUT_DIR/bundles/spark/README.md"
  fi
  # Hoist the smoke test to top-level scripts/ so the operator runs
  # `scripts/smoke_test.sh` rather than digging into bundles/spark/mcp/scripts/.
  cp bundles/spark/mcp/scripts/smoke_test.sh "$OUTPUT_DIR/scripts/smoke_test.sh"
fi

snapshot_args=("--output" "$OUTPUT_DIR/tool-snapshot.json")
if [ "$REQUIRE_MCP_TOOL_SNAPSHOT" = "1" ]; then
  snapshot_args+=("--required")
fi
python3 scripts/generate_mcp_tool_snapshot.py "${snapshot_args[@]}"
validate_args=(
  --catalog bundles/tool-catalog.yaml
  --snapshot "$OUTPUT_DIR/tool-snapshot.json"
)
# Two independent strictness knobs:
#
#   REQUIRE_MCP_TOOL_SNAPSHOT=1  — snapshot generation must succeed
#                                  (MCP must be reachable). On by default
#                                  in CI.
#   REQUIRE_FULL_TOOL_COVERAGE=1 — validation hard-fails when any
#                                  curated tool is absent from the live
#                                  snapshot. Off by default — CI runners
#                                  rely on persisted instance state from
#                                  prior bootstraps which may be partial
#                                  (some connectors not materialized →
#                                  their tools not advertised). Promote
#                                  to 1 once CI programmatically
#                                  bootstraps instance state.
if [ "$REQUIRE_MCP_TOOL_SNAPSHOT" != "1" ]; then
  validate_args+=("--allow-unavailable")
fi
if [ "${REQUIRE_FULL_TOOL_COVERAGE:-0}" != "1" ]; then
  validate_args+=("--allow-missing")
fi
python3 scripts/validate_tool_snapshot.py "${validate_args[@]}"

for item in "${IMAGES[@]}"; do
  image="${item%%|*}"
  archive="${item##*|}"
  if docker image inspect "$image" >/dev/null 2>&1; then
    docker image save "$image" -o "$OUTPUT_DIR/images/$archive"
  else
    printf 'Image not found locally, skipping archive: %s\n' "$image" >&2
  fi
done

cat > "$OUTPUT_DIR/runtime-metadata.json" <<EOF
{
  "agent_id": "phantom-soc-simulation-agent",
  "bundle_name": "$BUNDLE_NAME",
  "bundle_mode": "$BUNDLE_MODE",
  "created_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "source_commit": "$(git rev-parse HEAD 2>/dev/null || true)",
  "source_branch": "$(git branch --show-current 2>/dev/null || true)",
  "include_state": "$INCLUDE_STATE"
}
EOF

# Slim bundles get a recipient-facing README at the top of the
# tarball so the first thing they see after extracting is a guide
# to running the agent.
if [ "$BUNDLE_MODE" = "agent-only" ]; then
  cat > "$OUTPUT_DIR/README.md" <<'EOF'
# Phantom Agent — Slim Distribution (split-deploy)

This archive contains everything you need to run the Phantom SOC
simulation agent on a host that is **separate** from where xlog and
caldera run. The agent will reach those services over the network
once you provide their URLs in the setup form.

## What's in this archive

```
.
├── README.md                       this file
├── docker-compose.yml              agent-only compose recipe
├── images/
│   └── phantom-agent-local.tar     phantom-agent Docker image (combined UI + embedded MCP)
├── bundles/spark/
│   ├── manifest.yaml               agent declaration (read-only — full source baked into image)
│   └── README.md                   bundle overview
├── docs/split-deploy.md            full split-deploy operator guide
├── scripts/
│   ├── smoke_test.sh               verification suite (run after first boot)
│   ├── verify_agent_bundle.py      checksum + signature verification
│   ├── agent_lifecycle.sh          start/stop/restart/logs helpers
│   └── …                           install, import, materialize-secrets, etc.
├── tool-snapshot.json              expected connector tool list (validated against image)
├── tool-catalog.yaml               curated tool catalog (spec metadata)
├── secret-bindings.example.yaml    template for binding secrets to providers
├── observability.contract.yaml     observability event schema
├── runtime-metadata.json           build provenance (commit SHA, branch, mode)
├── bundle-manifest.json            file inventory + sizes
├── bundle-signature.json           HMAC signature metadata (unsigned by default)
└── checksums.sha256                tamper detection
```

## Quick start

```bash
# 1. Load the agent image (~1.5 GB)
docker load < images/phantom-agent-local.tar

# 2. Bring up the agent
docker compose up -d

# 3. Wait for healthy
until [ "$(docker inspect -f '{{.State.Health.Status}}' phantom_agent)" = "healthy" ]; do
  sleep 2
done

# 4. Open the setup page in a browser
open http://$(hostname):3000   # or visit manually
```

On the setup page, fill in:
  * Your operator UI password (you choose; persisted server-side)
  * Vertex AI / Gemini credentials
  * Caldera URL — `http://<machine-b>:8888` (the host where caldera runs)
  * xlog URL — `http://<machine-b>:8000`
  * XSIAM PAPI URL + auth header + auth ID + playground ID
  * XSIAM webhook endpoint + key

See `docs/split-deploy.md` for the full operator guide, including
network requirements on the xlog/caldera host.
EOF
fi

if [ "$INCLUDE_STATE" = "1" ]; then
  # The state subdirectory for the log-gen service (xlog) is named
  # `phantom` for compatibility with consumers of bundle exports.
  mkdir -p "$OUTPUT_DIR/state/phantom" "$OUTPUT_DIR/state/mcp" "$OUTPUT_DIR/state/caldera"
  if docker ps --format '{{.Names}}' | grep -qx xlog; then
    docker cp xlog:/data/xlog.db "$OUTPUT_DIR/state/phantom/xlog.db" 2>/dev/null || true
  fi
  # MCP state lives inside phantom_agent now (same container).
  if docker ps --format '{{.Names}}' | grep -qx phantom_agent; then
    docker cp phantom_agent:/app/skills "$OUTPUT_DIR/state/mcp/skills" 2>/dev/null || true
    # Instance/secret/audit data store.
    docker cp phantom_agent:/app/data "$OUTPUT_DIR/state/mcp/data" 2>/dev/null || true
  fi
  if docker ps --format '{{.Names}}' | grep -qx caldera; then
    docker cp caldera:/usr/src/app/data "$OUTPUT_DIR/state/caldera/data" 2>/dev/null || true
  fi
fi

# Defensive cleanup: strip macOS AppleDouble sidecars (`._*`), Python
# bytecode caches (`__pycache__`), and Finder metadata (`.DS_Store`)
# that may have leaked in via cp -R from a developer's machine. CI
# runners on Linux don't produce these, but the rsync-from-macOS path
# in CLAUDE.md does. Stripping here keeps the tarball + checksums.sha256
# free of cosmetic noise regardless of who built it.
find "$OUTPUT_DIR" \( -name '._*' -o -name '__pycache__' -o -name '.DS_Store' \) \
  -exec rm -rf {} + 2>/dev/null || true

python3 scripts/generate_bundle_manifest.py "$OUTPUT_DIR"

(
  cd "$OUTPUT_DIR"
  find . -type f ! -name checksums.sha256 -print0 | sort -z | xargs -0 shasum -a 256 > checksums.sha256
)

rm -f "$ARCHIVE_PATH"
# Belt-and-suspenders: tar's --exclude rejects junk that might appear
# between checksum-time and tar-time (defensive, should be a no-op
# given the find -delete above).
tar -C "$(dirname "$OUTPUT_DIR")" \
  --exclude='._*' --exclude='__pycache__' --exclude='.DS_Store' \
  -czf "$ARCHIVE_PATH" "$(basename "$OUTPUT_DIR")"

printf 'Agent bundle directory: %s\n' "$OUTPUT_DIR"
printf 'Agent bundle archive: %s\n' "$ARCHIVE_PATH"
