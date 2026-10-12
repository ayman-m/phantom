#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/install_agent_bundle.sh <bundle.tar.gz> [target-dir]

Imports a Phantom agent bundle, starts the standalone renderer, and leaves the
UI available at https://localhost:3000. Sign in as `admin` with the
PHANTOM_DEFAULT_ADMIN_PASSWORD from .env.
EOF
}

bundle="${1:-}"
target="${2:-}"

if [ -z "$bundle" ]; then
  usage
  exit 2
fi

if [ -z "$target" ]; then
  target="$(pwd)/phantom-agent"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$script_dir/import_agent_bundle.sh" "$bundle" "$target"

cd "$target"
mkdir -p .phantom-agent
if [ ! -f .env ]; then
  cp .env.template .env
  chmod 600 .env
fi

docker compose up -d phantom-agent

printf 'Phantom UI: https://localhost:3000 (sign in as admin with PHANTOM_DEFAULT_ADMIN_PASSWORD from .env)\n'
