#!/usr/bin/env bash
# Phantom — operator backup utility.
#
# Captures the persistent state that makes a Phantom deploy
# recoverable on a different host (or after a `docker volume rm`):
#
#   1. phantom_mcp_data volume — sqlite stores: audit log, instance
#      store, secret paths, KB, sessions, memory, jobs.
#   2. phantom_mcp_skills volume — skills library (markdown).
#   3. ./.phantom-agent/ bind-mount directory (if present) — setup
#      form values and generated env snapshot.
#
# Anything else the agent depends on (the Docker image, bundle source,
# remote xlog/caldera URLs the operator typed at first run) is either
# carried in the agent bundle archive or recoverable from the setup
# page. This script captures only what isn't recoverable any other way.
#
# Usage:
#   scripts/backup_phantom.sh [--output DIR] [--label LABEL]
#                             [--data-volume NAME] [--skills-volume NAME]
#                             [--runtime-dir PATH]
#
# Output:
#   <DIR>/phantom-backup-<LABEL>-<UTC-stamp>.tar.gz
#
#   The tarball contains:
#     backup-manifest.json     — provenance + sha256 of inner artifacts
#     data.tar.gz              — phantom_mcp_data contents
#     skills.tar.gz            — phantom_mcp_skills contents (if present)
#     runtime/                 — copy of ./.phantom-agent/ (if present)
#
# Exit codes:
#   0 = backup complete
#   1 = expected resource missing (no data volume found)
#   2 = bad invocation

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

OUTPUT_DIR=""
LABEL="auto"
DATA_VOLUME=""
SKILLS_VOLUME=""
RUNTIME_DIR=""

usage() {
  sed -n '2,33p' "$0"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --output) OUTPUT_DIR="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --data-volume) DATA_VOLUME="$2"; shift 2 ;;
    --skills-volume) SKILLS_VOLUME="$2"; shift 2 ;;
    --runtime-dir) RUNTIME_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

OUTPUT_DIR="${OUTPUT_DIR:-$ROOT_DIR}"
RUNTIME_DIR="${RUNTIME_DIR:-$ROOT_DIR/.phantom-agent}"

mkdir -p "$OUTPUT_DIR"

# Resolve volume names. Compose prefixes named volumes with the
# project name (typically the directory name), so the canonical
# `phantom_mcp_data` becomes e.g. `phantom_phantom_mcp_data`. We
# pattern-match unless the operator passed exact names.
discover_volume() {
  pattern="$1"
  docker volume ls --format '{{.Name}}' \
    | grep -E "(^|_)${pattern}\$" \
    | head -1 || true
}

if [ -z "$DATA_VOLUME" ]; then
  DATA_VOLUME="$(discover_volume phantom_mcp_data)"
fi
if [ -z "$SKILLS_VOLUME" ]; then
  SKILLS_VOLUME="$(discover_volume phantom_mcp_skills)"
fi

if [ -z "$DATA_VOLUME" ]; then
  printf 'ERROR: could not find phantom_mcp_data volume.\n' >&2
  printf '       Pass --data-volume <name> explicitly.\n' >&2
  printf '       Available volumes:\n' >&2
  docker volume ls --format '         {{.Name}}' >&2
  exit 1
fi

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive_name="phantom-backup-${LABEL}-${stamp}.tar.gz"
archive_path="${OUTPUT_DIR}/${archive_name}"
work_dir="$(mktemp -d -t phantom-backup-XXXXXX)"
trap 'rm -rf "$work_dir"' EXIT

printf 'Backing up to %s\n' "$archive_path"
printf '  data volume:   %s\n' "$DATA_VOLUME"
printf '  skills volume: %s\n' "${SKILLS_VOLUME:-<none>}"
printf '  runtime dir:   %s\n' "$RUNTIME_DIR"

# Use a tiny alpine image to read the volume's filesystem and tar it
# out to our work dir. ro mount because we don't want to risk corruption
# from a writable mount during backup.
backup_volume() {
  vol="$1"
  out="$2"
  printf '  archiving volume %s ...\n' "$vol"
  docker run --rm \
    -v "${vol}:/source:ro" \
    -v "${work_dir}:/dest" \
    alpine:3 \
    sh -c "cd /source && tar -czf /dest/$(basename "$out") ."
}

backup_volume "$DATA_VOLUME" "$work_dir/data.tar.gz"
data_sha="$(shasum -a 256 "$work_dir/data.tar.gz" | awk '{print $1}')"
data_size="$(stat -c%s "$work_dir/data.tar.gz" 2>/dev/null || stat -f%z "$work_dir/data.tar.gz")"

skills_sha="null"
skills_size=0
if [ -n "$SKILLS_VOLUME" ]; then
  backup_volume "$SKILLS_VOLUME" "$work_dir/skills.tar.gz"
  skills_sha="\"$(shasum -a 256 "$work_dir/skills.tar.gz" | awk '{print $1}')\""
  skills_size="$(stat -c%s "$work_dir/skills.tar.gz" 2>/dev/null || stat -f%z "$work_dir/skills.tar.gz")"
fi

runtime_present="false"
runtime_sha="null"
runtime_size=0
if [ -d "$RUNTIME_DIR" ]; then
  printf '  archiving runtime dir %s ...\n' "$RUNTIME_DIR"
  # Bind-mount path: tar from local fs (no docker dance needed).
  tar -czf "$work_dir/runtime.tar.gz" -C "$(dirname "$RUNTIME_DIR")" "$(basename "$RUNTIME_DIR")"
  runtime_present="true"
  runtime_sha="\"$(shasum -a 256 "$work_dir/runtime.tar.gz" | awk '{print $1}')\""
  runtime_size="$(stat -c%s "$work_dir/runtime.tar.gz" 2>/dev/null || stat -f%z "$work_dir/runtime.tar.gz")"
fi

# Manifest describes what's in the backup so restore_phantom.sh
# can refuse to restore an incomplete or corrupted archive.
cat > "$work_dir/backup-manifest.json" <<MANIFEST
{
  "format_version": 1,
  "created_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "label": "$LABEL",
  "host": "$(hostname)",
  "source_commit": "$(cd "$ROOT_DIR" && git rev-parse HEAD 2>/dev/null || true)",
  "components": {
    "data": {
      "source_volume": "$DATA_VOLUME",
      "archive": "data.tar.gz",
      "size_bytes": $data_size,
      "sha256": "$data_sha"
    },
    "skills": {
      "source_volume": "${SKILLS_VOLUME:-}",
      "archive": "skills.tar.gz",
      "present": $([ -n "$SKILLS_VOLUME" ] && echo true || echo false),
      "size_bytes": $skills_size,
      "sha256": $skills_sha
    },
    "runtime": {
      "source_path": "$RUNTIME_DIR",
      "archive": "runtime.tar.gz",
      "present": $runtime_present,
      "size_bytes": $runtime_size,
      "sha256": $runtime_sha
    }
  }
}
MANIFEST

# Wrap everything in one outer tarball.
tar -czf "$archive_path" -C "$work_dir" .

outer_sha="$(shasum -a 256 "$archive_path" | awk '{print $1}')"
outer_size="$(stat -c%s "$archive_path" 2>/dev/null || stat -f%z "$archive_path")"

printf '\nBackup complete.\n'
printf '  archive: %s\n' "$archive_path"
printf '  size:    %s bytes\n' "$outer_size"
printf '  sha256:  %s\n' "$outer_sha"
printf '\nRestore on this or another host with:\n'
printf '  scripts/restore_phantom.sh %s\n' "$archive_path"

# KEK reminder. The secrets directory inside `phantom_mcp_data` is
# AES-GCM ciphertext when PHANTOM_SECRET_KEK is set. The KEK lives
# in .env (NOT in this archive — env files have per-deploy values).
# Without the KEK, restoring the tarball gives you encrypted blobs
# you can't decrypt, and you'd have to re-fill the setup form.
if [ -f "$ROOT_DIR/.env" ] && grep -q '^PHANTOM_SECRET_KEK=' "$ROOT_DIR/.env" 2>/dev/null; then
  printf '\n'
  printf '  ⚠  PHANTOM_SECRET_KEK is set — secrets in this backup are\n'
  printf '     encrypted. Store the KEK in your secret manager separately\n'
  printf '     from this tarball. Losing the KEK = losing every secret.\n'
fi
