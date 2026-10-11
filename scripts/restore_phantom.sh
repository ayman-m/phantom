#!/usr/bin/env bash
# Phantom — operator restore utility.
#
# Reverse of backup_phantom.sh. Reads a backup archive produced by
# that script, recreates the named docker volumes (or rejects the
# restore if they exist non-empty unless --force), and extracts the
# bind-mounted runtime directory.
#
# Designed to be safe by default: the typical failure mode for
# restore tooling is silent overwrite of state the operator forgot
# they had. We refuse to clobber non-empty targets unless the
# operator explicitly opts in via --force.
#
# Usage:
#   scripts/restore_phantom.sh ARCHIVE [--force]
#                              [--data-volume NAME] [--skills-volume NAME]
#                              [--runtime-dir PATH]
#
# Verification:
#   The archive's backup-manifest.json carries the sha256 of every
#   inner artifact. Each is re-hashed before extraction; mismatches
#   abort the restore.
#
# Exit codes:
#   0 = restore complete
#   1 = checksum mismatch / corrupt archive / target volume non-empty
#   2 = bad invocation
#   3 = manifest missing / unsupported format_version

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ARCHIVE=""
FORCE=0
DATA_VOLUME="phantom_mcp_data"
SKILLS_VOLUME="phantom_mcp_skills"
RUNTIME_DIR=""

usage() {
  sed -n '2,33p' "$0"
}

# First positional is the archive path.
if [ "$#" -lt 1 ]; then
  usage >&2
  exit 2
fi
ARCHIVE="$1"; shift

while [ "$#" -gt 0 ]; do
  case "$1" in
    --force) FORCE=1; shift ;;
    --data-volume) DATA_VOLUME="$2"; shift 2 ;;
    --skills-volume) SKILLS_VOLUME="$2"; shift 2 ;;
    --runtime-dir) RUNTIME_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

RUNTIME_DIR="${RUNTIME_DIR:-$ROOT_DIR/.phantom-agent}"

if [ ! -f "$ARCHIVE" ]; then
  printf 'ERROR: archive not found: %s\n' "$ARCHIVE" >&2
  exit 1
fi

work_dir="$(mktemp -d -t phantom-restore-XXXXXX)"
trap 'rm -rf "$work_dir"' EXIT

printf 'Extracting archive ...\n'
tar -xzf "$ARCHIVE" -C "$work_dir"

manifest="$work_dir/backup-manifest.json"
if [ ! -f "$manifest" ]; then
  printf 'ERROR: backup-manifest.json missing — not a phantom backup.\n' >&2
  exit 3
fi

# Lightweight JSON read using python3 (already required for export
# pipeline). Avoids pulling in jq as a dependency.
read_manifest() {
  python3 -c "
import json, sys
m = json.load(open('$manifest'))
fmt = m.get('format_version')
if fmt != 1:
    print(f'unsupported format_version: {fmt}', file=sys.stderr)
    sys.exit(3)
print('LABEL=' + m.get('label', 'unknown'))
print('CREATED_AT=' + m.get('created_at', ''))
print('SOURCE_COMMIT=' + (m.get('source_commit') or ''))
data = m['components']['data']
print('DATA_SHA=' + data['sha256'])
print('DATA_SIZE=' + str(data['size_bytes']))
skills = m['components']['skills']
print('SKILLS_PRESENT=' + ('1' if skills.get('present') else '0'))
print('SKILLS_SHA=' + (skills.get('sha256') or ''))
runtime = m['components']['runtime']
print('RUNTIME_PRESENT=' + ('1' if runtime.get('present') else '0'))
print('RUNTIME_SHA=' + (runtime.get('sha256') or ''))
"
}

eval "$(read_manifest)"

printf 'Backup metadata:\n'
printf '  label:         %s\n' "$LABEL"
printf '  created at:    %s\n' "$CREATED_AT"
printf '  source commit: %s\n' "${SOURCE_COMMIT:-<unknown>}"
printf '  components:    data=yes skills=%s runtime=%s\n' \
  "$([ "$SKILLS_PRESENT" = 1 ] && echo yes || echo no)" \
  "$([ "$RUNTIME_PRESENT" = 1 ] && echo yes || echo no)"

verify_sha() {
  file="$1"
  expected="$2"
  actual="$(shasum -a 256 "$file" | awk '{print $1}')"
  if [ "$actual" != "$expected" ]; then
    printf 'ERROR: sha256 mismatch on %s\n' "$file" >&2
    printf '       expected: %s\n' "$expected" >&2
    printf '       actual:   %s\n' "$actual" >&2
    exit 1
  fi
}

verify_sha "$work_dir/data.tar.gz" "$DATA_SHA"
if [ "$SKILLS_PRESENT" = 1 ]; then
  verify_sha "$work_dir/skills.tar.gz" "$SKILLS_SHA"
fi
if [ "$RUNTIME_PRESENT" = 1 ]; then
  verify_sha "$work_dir/runtime.tar.gz" "$RUNTIME_SHA"
fi

# Refuse to overwrite existing volume content unless --force.
volume_is_empty() {
  vol="$1"
  # Returns 0 if volume doesn't exist OR exists but is empty.
  if ! docker volume inspect "$vol" >/dev/null 2>&1; then
    return 0
  fi
  count="$(docker run --rm -v "${vol}:/v:ro" alpine:3 sh -c 'ls -A /v | wc -l')"
  [ "${count// /}" = "0" ]
}

restore_volume() {
  vol="$1"
  archive="$2"
  if ! volume_is_empty "$vol"; then
    if [ "$FORCE" = 0 ]; then
      printf 'ERROR: volume %s exists and is non-empty.\n' "$vol" >&2
      printf '       Re-run with --force to overwrite, or restore to a fresh volume:\n' >&2
      printf '         docker volume rm %s   # destructive!\n' "$vol" >&2
      exit 1
    fi
    printf '  --force: emptying %s before restore\n' "$vol"
    docker run --rm -v "${vol}:/v" alpine:3 sh -c 'rm -rf /v/* /v/.[!.]* /v/..?* 2>/dev/null; true'
  fi
  docker volume create "$vol" >/dev/null
  printf '  restoring %s ...\n' "$vol"
  docker run --rm \
    -v "${vol}:/dest" \
    -v "${work_dir}:/src:ro" \
    alpine:3 \
    sh -c "cd /dest && tar -xzf /src/$(basename "$archive")"
}

printf '\nRestoring volumes ...\n'
restore_volume "$DATA_VOLUME" "$work_dir/data.tar.gz"
if [ "$SKILLS_PRESENT" = 1 ]; then
  restore_volume "$SKILLS_VOLUME" "$work_dir/skills.tar.gz"
fi

if [ "$RUNTIME_PRESENT" = 1 ]; then
  printf '  restoring runtime dir %s ...\n' "$RUNTIME_DIR"
  if [ -e "$RUNTIME_DIR" ] && [ "$FORCE" = 0 ]; then
    if [ -n "$(ls -A "$RUNTIME_DIR" 2>/dev/null || true)" ]; then
      printf 'ERROR: %s exists and is non-empty.\n' "$RUNTIME_DIR" >&2
      printf '       Re-run with --force to overwrite, or move it aside first.\n' >&2
      exit 1
    fi
  fi
  mkdir -p "$RUNTIME_DIR"
  rm -rf "${RUNTIME_DIR:?}/"* "${RUNTIME_DIR:?}/."[!.]* 2>/dev/null || true
  tar -xzf "$work_dir/runtime.tar.gz" -C "$(dirname "$RUNTIME_DIR")"
fi

printf '\nRestore complete.\n'
printf 'Bring the agent up with:\n'
printf '  docker compose up -d\n'
printf '\n'
printf 'The Phase-5 SecretStore + audit log are intact. UI password,\n'
printf 'connector instance configs, KB embeddings, sessions, memory,\n'
printf 'jobs — all carried over from the source host.\n'
