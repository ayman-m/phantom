#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}"

cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage: scripts/agent_lifecycle.sh <command>

Commands:
  start       Start the Phantom agent runtime with Docker Compose.
  stop        Stop the Phantom agent runtime.
  restart     Restart the Phantom agent runtime.
  status      Show Compose service status.
  health      Run local health probes against the Compose network ports.
  logs        Follow Compose logs.
  apply-setup Copy first-run setup values into .env and recreate the stack.
  export      Build an agent bundle archive.
EOF
}

health_probe() {
  name="$1"
  url="$2"
  if curl -fsS --max-time 5 "$url" >/dev/null; then
    printf '%s ok %s\n' "$name" "$url"
  else
    printf '%s failed %s\n' "$name" "$url" >&2
    return 1
  fi
}

command="${1:-}"
case "$command" in
  start)
    docker compose -f "$COMPOSE_FILE" up -d
    ;;
  stop)
    docker compose -f "$COMPOSE_FILE" down
    ;;
  restart)
    docker compose -f "$COMPOSE_FILE" down
    docker compose -f "$COMPOSE_FILE" up -d
    ;;
  status)
    docker compose -f "$COMPOSE_FILE" ps
    ;;
  health)
    health_probe phantom http://localhost:8999/health
    health_probe phantom-mcp http://localhost:8080/ping/
    health_probe phantom-agent http://localhost:3000/api/auth/status
    health_probe caldera http://localhost:8888/
    ;;
  logs)
    docker compose -f "$COMPOSE_FILE" logs -f
    ;;
  apply-setup)
    generated_env="$ROOT_DIR/.phantom-agent/.env.generated"
    if [ ! -f "$generated_env" ]; then
      printf 'No generated setup env found at %s\n' "$generated_env" >&2
      exit 1
    fi
    cp "$generated_env" "$ROOT_DIR/.env"
    chmod 600 "$ROOT_DIR/.env"
    docker compose -f "$COMPOSE_FILE" up -d --force-recreate
    ;;
  export)
    "$ROOT_DIR/scripts/export_agent_bundle.sh"
    ;;
  *)
    usage
    exit 2
    ;;
esac
