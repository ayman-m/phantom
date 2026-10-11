#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/install_agent_bundle.sh <bundle.tar.gz> [target-dir]

Imports a Phantom agent bundle, starts the standalone renderer, and leaves the
first-run setup UI available at http://localhost:3000.
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

printf 'Phantom setup UI: http://localhost:3000\n'
printf 'After setup, run: cd %s && ./scripts/agent_lifecycle.sh apply-setup\n' "$target"
