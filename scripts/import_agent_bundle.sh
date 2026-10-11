#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/import_agent_bundle.sh <bundle.tar.gz> [target-dir]

Materializes a Phantom agent bundle for standalone execution:
  1. Unpacks the bundle.
  2. Verifies checksums and optional signature metadata.
  3. Loads included Docker image archives.
  4. Writes a .env.template with required variable names.
  5. Optionally restores exported state when RESTORE_STATE=1.

This script never asks for or writes raw secret values. Bind secrets through your
orchestration platform or create a local .env from the template yourself.
EOF
}

bundle="${1:-}"
target="${2:-}"

if [ -z "$bundle" ]; then
  usage
  exit 2
fi

if [ ! -f "$bundle" ]; then
  printf 'Bundle archive not found: %s\n' "$bundle" >&2
  exit 1
fi

if [ -z "$target" ]; then
  target="$(pwd)/phantom-agent-import"
fi

rm -rf "$target"
mkdir -p "$target"
tar -xzf "$bundle" -C "$target" --strip-components=1

verify_args=("$target")
if [ "${REQUIRE_BUNDLE_SIGNATURE:-0}" = "1" ]; then
  verify_args+=("--require-signature")
fi
python3 "$target/scripts/verify_agent_bundle.py" "${verify_args[@]}"

if [ -d "$target/images" ]; then
  find "$target/images" -name '*.tar' -type f -print0 | while IFS= read -r -d '' image_archive; do
    docker image load -i "$image_archive"
  done
fi

if [ "${MATERIALIZE_SECRET_REFS:-1}" = "1" ] && [ -f "$target/secret-bindings.example.yaml" ]; then
  python3 "$target/scripts/materialize_secret_bindings.py" \
    --template "$target/secret-bindings.example.yaml" \
    --output "$target/.env.secret-refs"
fi

if [ "${BIND_SECRET_PROVIDER:-0}" = "1" ] && [ -f "$target/.env.secret-refs" ]; then
  python3 "$target/scripts/bind_secret_provider.py" \
    --refs "$target/.env.secret-refs" \
    --agent-id "phantom-soc-simulation-agent"
fi

cat > "$target/.env.template" <<'EOF'
# Copy this file to .env and bind values from your secret provider.
# Do not commit .env.
ANIMATED=true
CALDERA_RED_USER=red
CALDERA_URL=http://caldera:8888
CALDERA_VARIANT=full
GEMINI_MODEL=gemini-3.1-pro-preview
LOGGING_DIR=/logs
LOGGING_STORAGE_SIZE=10000000
LOGGING_TRUNCATE_LIMIT=1000000
MCP_HOST=0.0.0.0
MCP_PATH=/api/v1/stream/mcp
MCP_PORT=8080
MCP_URL=http://phantom-mcp:8080/api/v1/stream/mcp
MCP_TOOL_CACHE_TTL_MS=300000
MCP_TRANSPORT=streamable-http
XLOG_URL=http://xlog:8000
PLAYGROUND_ID=
REBUILD_XQL_CHROMA=false
TECHNOLOGY_STACK={}
UI_USER=admin
WORKERS_NUMBER=10
XSIAM_MANDATORY_PARSED_FIELDS=
XSIAM_OPTIONAL_PARSED_FIELDS=
CALDERA_MCP_URL=
XSIAM_MCP_URL=
XLOG_MCP_URL=

# Secret references. Replace locally or inject from your orchestrator.
MCP_TOKEN=
UI_PASSWORD=
GOOGLE_APPLICATION_CREDENTIALS=
CALDERA_RED_PASSWORD=
CALDERA_MCP_TOKEN=
XSIAM_MCP_TOKEN=
XLOG_MCP_TOKEN=
GEMINI_API_KEY=
SSL_CERT_PEM=
SSL_KEY_PEM=
EOF

restore_volume_from_dir() {
  local image="$1"
  local volume="$2"
  local source_dir="$3"
  local target_path="${4:-/target}"

  if [ ! -d "$source_dir" ]; then
    return 0
  fi

  docker volume create "$volume" >/dev/null
  docker run --rm \
    --entrypoint sh \
    -v "${volume}:${target_path}" \
    -v "${source_dir}:/source:ro" \
    "$image" \
    -c "rm -rf '${target_path:?}'/* && cp -a /source/. '${target_path}/'"
  printf 'Restored state into volume %s from %s\n' "$volume" "$source_dir"
}

restore_file_to_volume() {
  local image="$1"
  local volume="$2"
  local source_file="$3"
  local target_path="$4"
  local target_dir
  local target_name

  if [ ! -f "$source_file" ]; then
    return 0
  fi

  target_dir="$(dirname "$target_path")"
  target_name="$(basename "$target_path")"
  docker volume create "$volume" >/dev/null
  docker run --rm \
    --entrypoint sh \
    -v "${volume}:${target_dir}" \
    -v "$(dirname "$source_file"):/source:ro" \
    "$image" \
    -c "cp '/source/${target_name}' '${target_path}'"
  printf 'Restored state file into volume %s:%s from %s\n' "$volume" "$target_path" "$source_file"
}

if [ "${RESTORE_STATE:-0}" = "1" ]; then
  project_name="${COMPOSE_PROJECT_NAME:-$(basename "$target" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-')}"
  project_name="${project_name%-}"
  phantom_volume="${PHANTOM_DATA_VOLUME:-${project_name}_phantom_data}"
  mcp_skills_volume="${PHANTOM_MCP_SKILLS_VOLUME:-${project_name}_phantom_mcp_skills}"
  caldera_data_volume="${CALDERA_DATA_VOLUME:-${project_name}_caldera_data}"

  restore_file_to_volume "phantom:local" "$phantom_volume" "$target/state/phantom/phantom.db" "/data/phantom.db"
  restore_volume_from_dir "phantom-mcp:local" "$mcp_skills_volume" "$target/state/mcp/skills" "/app/skills"
  restore_volume_from_dir "caldera:local" "$caldera_data_volume" "$target/state/caldera/data" "/usr/src/app/data"
else
  if [ -d "$target/state" ]; then
    printf 'State artifacts are staged under %s/state. Set RESTORE_STATE=1 to restore them into Docker volumes.\n' "$target"
  fi
fi

printf 'Imported bundle to: %s\n' "$target"
printf 'Next steps:\n'
printf '  1. cp %s/.env.template %s/.env\n' "$target" "$target"
printf '  2. Start the setup UI with: cd %s && docker compose up -d phantom-agent\n' "$target"
printf '     Secret provider references are in %s/.env.secret-refs\n' "$target"
printf '     Set BIND_SECRET_PROVIDER=1 to register references through scripts/bind_secret_provider.py\n'
printf '  3. Open http://localhost:3000 and complete first-run setup\n'
printf '  4. cd %s && ./scripts/agent_lifecycle.sh apply-setup\n' "$target"
