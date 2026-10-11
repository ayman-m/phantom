#!/usr/bin/env bash
# Phantom factory reset
#
# Host-side utility. Wipes all operator-state volumes for the Phantom
# stack and re-runs the installer so the customer returns to the
# fresh-shipped state.
#
# Usage:
#
#   sudo /opt/phantom/phantom-factory-reset
#   sudo /opt/phantom/phantom-factory-reset --yes   # skip confirmation
#   sudo /opt/phantom/phantom-factory-reset --dry-run
#
# # Why this script exists separately from the installer
#
# CLAUDE.md's "Volume management — NEVER in the installer" rule:
# the installer cares about image deployment, this script cares
# about state. Cramming both into one tool conflates two
# responsibilities and produces the kind of `--reset-volumes` flag
# that operators run by accident and then file as a support ticket.
# Separation makes both halves easier to reason about.
#
# # Why this script is host-side (not inside the container)
#
# A container cannot delete the docker volume it has mounted — the
# daemon refuses with a "volume in use" error. Factory reset MUST
# operate from outside the container boundary by definition.
#
# # What this script does
#
#   1. Pre-flight: confirm we're at /opt/phantom and a stack exists.
#   2. List volumes that match the phantom_* naming convention.
#   3. Ask for confirmation (typed "FACTORY RESET" or --yes flag).
#   4. docker compose down --remove-orphans (stops + removes containers).
#   5. docker volume rm <each matching volume> (wipes state).
#   6. Re-run the installer (phantom-installer or phantom-installer-dev)
#      to recreate volumes + bring fresh containers up.
#   7. Report what was wiped + how many seconds the whole thing took.
#
# # What this script does NOT do
#
#   - Touch the .env (preserves PHANTOM_SECRET_KEK +
#     other operator-managed settings). To rotate those, edit .env
#     by hand BEFORE running factory reset.
#   - Delete the install kit itself or this script. If you want to
#     start over from a fresh tarball, `rm -rf /opt/phantom` and
#     re-extract the kit.
#   - Mutate any images on disk. The next install will pull whichever
#     digests the installer has pinned (latest customer release or
#     :dev for the dev installer).

set -euo pipefail

# ─── Config ─────────────────────────────────────────────────────────────
INSTALL_DIR="${PHANTOM_INSTALL_DIR:-/opt/phantom}"
COMPOSE_FILE="${INSTALL_DIR}/docker-compose.yml"
VOLUME_PREFIX="${PHANTOM_VOLUME_PREFIX:-phantom_}"

# Both installer flavors. We pick whichever exists.
RELEASE_INSTALLER="${INSTALL_DIR}/phantom-installer"
DEV_INSTALLER="${INSTALL_DIR}/phantom-installer-dev"

# Modes
ASSUME_YES=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASSUME_YES=1 ;;
    --dry-run|-n) DRY_RUN=1 ;;
    --help|-h)
      sed -n '2,/^set -euo/p' "$0" | sed -e 's/^# \{0,1\}//' -e '$d'
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument '$arg'. Try --help." >&2
      exit 2
      ;;
  esac
done

# ─── Helpers ────────────────────────────────────────────────────────────
say()  { printf '%s\n' "$*"; }
info() { printf '\033[36m→\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# ─── Pre-flight ─────────────────────────────────────────────────────────
need() {
  command -v "$1" >/dev/null 2>&1 || die "'$1' not found in PATH."
}
need docker
docker compose version >/dev/null 2>&1 || die "'docker compose' v2 plugin missing."

if [[ ! -d "$INSTALL_DIR" ]]; then
  die "INSTALL_DIR not found: $INSTALL_DIR
       Set PHANTOM_INSTALL_DIR if your install is elsewhere, OR
       install Phantom first (gh release download + ./phantom-installer)."
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  die "$COMPOSE_FILE not found.
       Factory reset assumes a Phantom install at $INSTALL_DIR. If you
       haven't installed Phantom yet, you don't need to factory-reset —
       just run the installer."
fi

# Resolve which installer to use. The phantom-installer binary is
# part of the shipped package and is self-installed to $INSTALL_DIR/
# at the end of every successful install run (see the installer's
# "Self-install" step at the end of phantom-installer.template.sh).
# Factory-reset depends on that binary to bring the stack back up
# after the wipe.
#
# If the binary is missing, the install is INCOMPLETE — either it
# was deleted manually, the install never finished, or this host
# was carried forward from a pre-self-install installer version.
# Factory-reset refuses to proceed in that state rather than wipe
# volumes and leave the operator with a broken stack.
INSTALLER=""
if [[ -x "$RELEASE_INSTALLER" ]]; then
  INSTALLER="$RELEASE_INSTALLER"
elif [[ -x "$DEV_INSTALLER" ]]; then
  INSTALLER="$DEV_INSTALLER"
else
  die "Phantom installer binary missing from $INSTALL_DIR/.

       Expected one of:
         $RELEASE_INSTALLER     (customer-release flavor)
         $DEV_INSTALLER         (dev flavor)

       The installer is shipped alongside the recovery utilities
       in every Phantom install package and self-installs to
       $INSTALL_DIR/ on first run. Its absence means the install
       is incomplete; factory-reset cannot continue (it depends on
       this binary to bring the stack back up after the wipe).

       To recover:
         1. Download a fresh phantom-installer from
            https://github.com/ayman-m/phantom/releases
         2. Run it (sudo ./phantom-installer) — it will self-install
            into $INSTALL_DIR/ as part of the normal install ceremony
         3. Re-run sudo $INSTALL_DIR/phantom-factory-reset"
fi

# Need root or docker-group membership to manipulate docker volumes.
if ! docker ps >/dev/null 2>&1; then
  die "Cannot reach docker daemon. Either run via sudo, or add your user
       to the docker group: sudo usermod -aG docker \$USER (then re-login)."
fi

# ─── Discover volumes ───────────────────────────────────────────────────
info "Scanning for volumes matching prefix '${VOLUME_PREFIX}'"
mapfile -t VOLUMES < <(docker volume ls --quiet --filter "name=${VOLUME_PREFIX}" 2>/dev/null || true)

if [[ ${#VOLUMES[@]} -eq 0 ]]; then
  ok "No matching volumes found. Stack already fresh — nothing to wipe."
  if [[ -n "$INSTALLER" && "$DRY_RUN" == "0" ]]; then
    info "Running installer to make sure containers are up + healthy"
    exec "$INSTALLER"
  fi
  exit 0
fi

# ─── Show what will be wiped ────────────────────────────────────────────
say ""
say "─────────────────────────────────────────────────────"
say "  Phantom factory reset"
say "─────────────────────────────────────────────────────"
say ""
say "  This will PERMANENTLY DELETE the following docker volumes:"
say ""
for vol in "${VOLUMES[@]}"; do
  # Try to surface volume size as a hint to the operator.
  size=$(docker run --rm -v "${vol}:/v:ro" alpine:3 sh -c 'du -sh /v 2>/dev/null | cut -f1' 2>/dev/null || echo "?")
  say "    • $vol  (~$size)"
done
say ""
say "  After deletion the installer re-runs and Phantom comes up with"
say "  a fresh-shipped state:"
say ""
say "    • All operator memories gone"
say "    • All connector instances + their secrets gone"
say "    • All API keys gone"
say "    • All audit logs, sessions, jobs, notifications gone"
say "    • Skills volume reseeded from the image's bundle defaults"
say "    • TLS certs regenerated"
say "    • Admin credentials reset to the shipped default (you'll be"
say "      prompted to change them at /profile on first login)"
say ""
say "  What does NOT get wiped:"
say ""
say "    • $INSTALL_DIR/.env (PHANTOM_SECRET_KEK preserved)"
say "    • Docker images on disk (next install reuses them)"
say "    • The installer binary or this script"
say ""

if [[ "$DRY_RUN" == "1" ]]; then
  say "  (--dry-run: not actually deleting anything)"
  ok "Dry run complete."
  exit 0
fi

# ─── Confirmation ───────────────────────────────────────────────────────
if [[ "$ASSUME_YES" == "0" ]]; then
  say "  Type 'FACTORY RESET' exactly to proceed, or anything else to abort:"
  printf '  > '
  read -r answer
  if [[ "$answer" != "FACTORY RESET" ]]; then
    die "Aborted. No volumes were deleted."
  fi
else
  say "  --yes flag set; proceeding without prompt."
fi
say ""

START_TIME=$(date +%s)

# ─── Step 1: stop the stack ─────────────────────────────────────────────
info "Stopping stack (docker compose down --remove-orphans)"
( cd "$INSTALL_DIR" && docker compose down --remove-orphans ) || \
  warn "compose down returned non-zero (some containers may already be stopped)"

# ─── Step 2: wipe volumes ───────────────────────────────────────────────
WIPED=0
FAILED=0
for vol in "${VOLUMES[@]}"; do
  if docker volume rm "$vol" >/dev/null 2>&1; then
    ok "Removed volume: $vol"
    WIPED=$((WIPED+1))
  else
    warn "Failed to remove volume: $vol (may still be in use by a container)"
    FAILED=$((FAILED+1))
  fi
done

if [[ "$FAILED" -gt 0 ]]; then
  warn "$FAILED volume(s) could not be removed. Run 'docker ps -a' to find"
  warn "lingering containers, stop them, then re-run this script."
  exit 1
fi

ok "Wiped $WIPED volume(s)"

# ─── Step 3: re-run installer ───────────────────────────────────────────
if [[ -n "$INSTALLER" ]]; then
  info "Running installer ($INSTALLER) to bring Phantom back up"
  say ""
  "$INSTALLER"
else
  warn "No installer present — Phantom stack is currently DOWN."
  warn "Run your installer manually to bring it back up."
fi

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

say ""
ok "Factory reset complete in ${ELAPSED}s. Phantom is back to fresh-shipped state."
say "  Sign in at https://localhost:3000 with the default credentials shown above."
