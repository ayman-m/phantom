#!/usr/bin/env bash
# Phantom — single-file installer for clean VMs.
#
# This file is a TEMPLATE. The release workflow generates the real
# `phantom-installer` from this template + installer/docker-compose.yml,
# substituting two placeholder strings (see lines 222-224 below for
# their literal form). One placeholder receives the compose YAML
# verbatim (with VERSION_DEFAULT pinned to the release tag); the other
# receives the literal release version, e.g. "0.1.0".
#
# IMPORTANT for maintainers: do NOT mention either placeholder by its
# literal token anywhere in this file outside the substitution target
# lines themselves. The build script does a global string replace, so
# any second occurrence (even in a comment) will get substituted with
# the entire compose YAML and break the resulting script.
#
# You should NOT run this template directly — it has the placeholders
# unsubstituted. Build the real installer with:
#   bash installer/build-phantom-installer.sh
# (or just push a release tag and let the workflow handle it).
#
# Customer flow on a fresh Linux VM:
#   chmod +x phantom-installer
#   sudo ./phantom-installer
#
# No registry account, token or `docker login` is involved: every
# Phantom image is public on GHCR and is pulled anonymously.
#
# What the script does, end-to-end:
#   1. Detects OS + verifies sudo
#   2. Installs Docker if missing (via get.docker.com)
#   3. Detects an existing install (re-runs preserve its secrets)
#   4. Checks the registry is reachable (anonymous)
#   5. Auto-generates runtime secrets (MCP_TOKEN, KEK, etc.)
#   6. Writes /opt/phantom/{docker-compose.yml,.env}
#   7. Pulls images, brings the stack up, waits for healthy, prints
#      the URL the operator can open in a browser

set -euo pipefail

# Resolve $0 to an absolute path RIGHT NOW, before any cd changes the
# cwd (step 7 cd's into $INSTALL_DIR, after which a relative $0 like
# `./dist/installer-dev/phantom-installer-dev` won't resolve). The
# post-install self-persist step (end of file) uses this to copy the
# binary into $INSTALL_DIR/.
#
# readlink -f requires every component of the path to exist; if it
# fails (rare — the binary IS running so it must exist), fall through
# to constructing the absolute path from $PWD + dirname($0) + basename
# ($0). Either way, INSTALLER_BINARY_PATH is absolute by the time any
# subsequent cd runs.
case "$0" in
  /*) INSTALLER_BINARY_PATH="$0" ;;
  *)  INSTALLER_BINARY_PATH="$(readlink -f "$0" 2>/dev/null \
        || echo "$(cd "$(dirname "$0")" 2>/dev/null && pwd)/$(basename "$0")")" ;;
esac

# ─── Constants ────────────────────────────────────────────────────────
PHANTOM_VERSION="__INSTALLER_VERSION__"
GHCR_REGISTRY="ghcr.io"
GHCR_OWNER="ayman-m"
INSTALL_DIR="${PHANTOM_INSTALL_DIR:-/opt/phantom}"
# A fresh image pull followed by first-run cold-start work (KB loading
# ~800 entries, connector-schema validation, Next.js compile-on-first-hit)
# can push phantom-agent's first healthy transition past 300s on a
# normally loaded host. The timeout gives genuinely slow-but-working
# installs headroom; a truly broken install still fails clearly via the
# diagnostic-commands message below, just after a realistic wait.
HEALTH_TIMEOUT_SECS=600

# ─── Embedded digest manifest ────────────────────────────────────────
# The release workflow builds this installer with the per-image content digests
# of every phantom-* image at this exact version. The manifest is
# embedded verbatim below; the install/upgrade flow appends it to
# /opt/phantom/.env so docker compose resolves each service's
# `image: ...@${DIGEST_<SVC>}` reference to the matching content blob.
#
# Customer impact: containers are recreated by docker compose iff the
# image content actually changed between versions. Caldera + xlog +
# phantom-browser typically retain in-memory state across upgrades
# that don't touch their source.
#
# If this heredoc is empty or contains DIGEST_MANIFEST_MISSING=1,
# the installer was built without MANIFEST_PATH (a dev-build
# scenario) — the install/upgrade flow will exit with a clear error
# rather than producing a broken stack.
DIGEST_MANIFEST=$(cat <<'_PHANTOM_DIGEST_MANIFEST_HEREDOC_END_'
__INSTALLER_DIGEST_MANIFEST__
_PHANTOM_DIGEST_MANIFEST_HEREDOC_END_
)

# A fork's build may stamp a PHANTOM_OWNER= line into the manifest so
# its installer pulls from the fork's own GHCR namespace instead of
# ayman-m. Official release manifests never carry this line, so
# GHCR_OWNER stays "ayman-m" for the installers published from
# ayman-m/phantom.
_manifest_owner=$(printf '%s\n' "$DIGEST_MANIFEST" | grep '^PHANTOM_OWNER=' | head -1 | cut -d= -f2- || true)
if [[ -n "$_manifest_owner" ]]; then
  GHCR_OWNER="$_manifest_owner"
fi

# ─── Argument parsing ─────────────────────────────────────────────────
# --upgrade-to N.N.N  → on an existing install, rewrite PHANTOM_VERSION
#                       in .env to the given version (default behavior
#                       is to preserve the existing pin). On a fresh
#                       install, install at the given version instead
#                       of the installer's bundled default.
# --help / -h         → print usage and exit.

# Capture the original argv BEFORE the parser consumes it.
# The arg-parsing loop below uses `shift` after each option, so by the
# time we hit the sudo re-exec further down, `$@` is empty and any
# args the user passed would be lost on the second invocation.
ORIGINAL_ARGS=("$@")

UPGRADE_TO=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --upgrade-to)
      [[ -n "${2:-}" ]] || { echo "ERROR: --upgrade-to requires a version (e.g. --upgrade-to 0.1.6)" >&2; exit 1; }
      UPGRADE_TO="$2"
      shift 2
      ;;
    --upgrade-to=*)
      UPGRADE_TO="${1#*=}"
      shift
      ;;
    --help|-h)
      cat <<USAGE
Usage: phantom-installer [--upgrade-to N.N.N]

  No flags                Install Phantom (or upgrade an existing
                          install) at v$PHANTOM_VERSION. This binary is
                          sealed to v$PHANTOM_VERSION — it embeds the
                          digest manifest for that exact version's
                          images. To install a different version,
                          download the corresponding installer binary
                          from the GitHub Release for that version.

  --upgrade-to N.N.N      Backward-compat flag. Must equal v$PHANTOM_VERSION
                          (the binary's sealed version) or the install
                          errors out. Kept for operator scripts that
                          pass the flag explicitly during upgrades; it
                          is redundant — the binary's stamp IS the
                          target version.

  Version sealing         Installers use digest pinning and embed the
                          per-version manifest; one binary = one
                          installable version.

Examples:
  sudo ./phantom-installer                          # → installs v$PHANTOM_VERSION

Release notes and downloads:
  https://github.com/ayman-m/phantom/releases/tag/v$PHANTOM_VERSION
USAGE
      exit 0
      ;;
    *)
      echo "ERROR: unknown option '$1' (try --help)" >&2
      exit 1
      ;;
  esac
done

if [[ -n "$UPGRADE_TO" ]]; then
  if ! printf '%s' "$UPGRADE_TO" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "ERROR: --upgrade-to must be N.N.N semver (got: '$UPGRADE_TO')" >&2
    exit 1
  fi
  # Installer binaries are SEALED to a single version because the
  # digest manifest is embedded at build time: this binary's manifest
  # only describes v$PHANTOM_VERSION's images. We accept the flag for
  # operator scripts but error out if it mismatches the binary version,
  # with a clear pointer to the right download.
  if [[ "$UPGRADE_TO" != "$PHANTOM_VERSION" ]]; then
    cat >&2 <<USAGE_ERR
ERROR: --upgrade-to v$UPGRADE_TO doesn't match this binary's version (v$PHANTOM_VERSION).

Each phantom-installer binary is sealed to a single version
because it embeds the digest manifest for that version's images. To
install v$UPGRADE_TO, download the v$UPGRADE_TO installer binary:

  gh release download v$UPGRADE_TO --repo ayman-m/phantom \\
    --pattern phantom-installer
  chmod +x phantom-installer
  sudo ./phantom-installer
USAGE_ERR
    exit 1
  fi
fi

# ─── Cosmetics ────────────────────────────────────────────────────────
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
  C_BOLD=$'\033[1m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m';  C_DIM=$'\033[2m';   C_RESET=$'\033[0m'
else
  C_BOLD=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_DIM=""; C_RESET=""
fi

say()  { printf "%s%s%s\n" "$C_BOLD" "$*" "$C_RESET"; }
info() { printf "%s→%s %s\n" "$C_DIM" "$C_RESET" "$*"; }
ok()   { printf "%s✓%s %s\n" "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf "%s!%s %s\n" "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()  { printf "%s✗%s %s\n" "$C_RED" "$C_RESET" "$*" >&2; exit 1; }

# ─── Banner ───────────────────────────────────────────────────────────
say ""
say "  Phantom — installer (v$PHANTOM_VERSION)"
say "  ───────────────────────────────────────"
if [[ -n "$UPGRADE_TO" ]]; then
  say "  Upgrade mode → target version v$UPGRADE_TO"
  say "  ───────────────────────────────────────"
fi
say ""

# ─── Step 1: Pre-flight (OS, sudo, etc.) ──────────────────────────────
info "Step 1/7 — pre-flight checks"

# Sudo / root check. We need write access to INSTALL_DIR (default
# /opt/phantom — root-owned by convention) AND access to docker.sock
# (root or docker group). If the caller already has both, we skip
# self-elevation entirely — that lets rootless-docker users and
# pre-created-INSTALL_DIR setups run the installer as their own user.
# This branch fires identically for:
#   - CI runners (runner user owns INSTALL_DIR, in docker group)
#   - Customers with rootless docker who chown their install dir
#   - Customers with podman-docker shim + non-root install dir
# Otherwise re-exec under sudo, preserving env vars callers may set.
if [[ "$(id -u)" -ne 0 ]]; then
  # Test write access without actually writing. `mkdir -p` is
  # idempotent + side-effect-free for an existing writable dir.
  CAN_WRITE_INSTALL_DIR=0
  if mkdir -p "$INSTALL_DIR" 2>/dev/null && [[ -w "$INSTALL_DIR" ]]; then
    CAN_WRITE_INSTALL_DIR=1
  fi
  CAN_ACCESS_DOCKER=0
  if [[ -w /var/run/docker.sock ]] || docker info >/dev/null 2>&1; then
    CAN_ACCESS_DOCKER=1
  fi

  if (( CAN_WRITE_INSTALL_DIR == 1 && CAN_ACCESS_DOCKER == 1 )); then
    info "Running as $(whoami) without elevation (write access to $INSTALL_DIR + docker available)."
  elif command -v sudo >/dev/null 2>&1; then
    info "Re-running under sudo (need root for $INSTALL_DIR + docker)…"
    # Pass ORIGINAL_ARGS (captured before the parser shifted them off)
    # so flags like --upgrade-to actually survive the re-exec. The
    # `${ARRAY[@]+"${ARRAY[@]}"}` idiom is safe under set -u when the
    # array is empty (bash 4.x+).
    exec sudo -E -- "$0" "${ORIGINAL_ARGS[@]+"${ORIGINAL_ARGS[@]}"}"
  else
    die "Not running as root and sudo not available, and current user
       lacks write access to $INSTALL_DIR or cannot reach docker.
       Either (a) re-run as root:  su - root -c '$0'
       or (b) pre-create $INSTALL_DIR and add your user to the
              docker group, then re-run."
  fi
fi

# OS detection. /etc/os-release is the modern standard (systemd
# distros). The Docker convenience script supports a fixed allowlist;
# we mirror it here so we can fail fast on unsupported distros.
if [[ ! -f /etc/os-release ]]; then
  die "Cannot detect OS (no /etc/os-release). This script supports
       Ubuntu, Debian, RHEL, Fedora, Rocky, AlmaLinux, openSUSE."
fi
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}:${ID_LIKE:-}" in
  ubuntu*|debian*|*ubuntu*|*debian*|rhel*|*rhel*|fedora*|*fedora*|\
  centos*|*centos*|rocky*|*rocky*|almalinux*|*almalinux*|\
  opensuse*|*opensuse*|sles*|*sles*)
    ok "OS detected: ${PRETTY_NAME:-${ID}}"
    ;;
  *)
    die "Unsupported OS: ${PRETTY_NAME:-${ID}}.
       Phantom auto-install supports Ubuntu/Debian/RHEL/Fedora/Rocky/
       AlmaLinux/openSUSE. On other distros, install Docker and the
       compose plugin yourself and re-run this installer."
    ;;
esac

# Architecture check. We publish multi-arch images for amd64/arm64.
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64|aarch64|arm64) ok "Architecture: $ARCH" ;;
  *) die "Unsupported architecture: $ARCH (need amd64 or arm64)." ;;
esac

# ─── Step 2: Docker install if missing ────────────────────────────────
info "Step 2/7 — Docker"

if ! command -v docker >/dev/null 2>&1; then
  warn "Docker not found — installing via get.docker.com…"
  warn "(This pulls and runs Docker's official convenience script.)"

  # The convenience script is the canonical way to install Docker
  # Engine + compose plugin on the supported distros. We need curl
  # to fetch it; install curl first if missing.
  if ! command -v curl >/dev/null 2>&1; then
    info "Installing curl first…"
    if command -v apt-get >/dev/null 2>&1; then
      apt-get update -qq && apt-get install -y -qq curl
    elif command -v dnf >/dev/null 2>&1; then
      dnf install -y -q curl
    elif command -v yum >/dev/null 2>&1; then
      yum install -y -q curl
    elif command -v zypper >/dev/null 2>&1; then
      zypper -n install -y curl
    else
      die "Cannot install curl on this distro. Install it manually."
    fi
  fi

  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh
  rm -f /tmp/get-docker.sh

  systemctl enable --now docker || true
  ok "Docker installed: $(docker --version)"
else
  ok "Docker already present: $(docker --version)"
fi

# Verify compose plugin (v2) is available. The convenience script
# installs it; older boxes that pre-date the plugin-era of compose
# may need a manual nudge.
if ! docker compose version >/dev/null 2>&1; then
  die "'docker compose' v2 plugin not available even after install.
       Install manually:
       https://docs.docker.com/compose/install/linux/"
fi
ok "Compose plugin present: $(docker compose version --short 2>/dev/null || docker compose version | head -1)"

# Verify daemon is actually reachable. systemctl enable should have
# started it, but on some hosts (containers, exotic init systems) it
# may not have.
if ! docker info >/dev/null 2>&1; then
  die "docker daemon not reachable.
       Start it manually:  systemctl start docker"
fi
ok "Docker daemon reachable"

# ─── Step 3: Detect existing install (resumable) ──────────────────────
info "Step 3/7 — checking for existing install"

# Reads a value from $INSTALL_DIR/.env. Echoes the value to stdout if
# present and non-empty; returns 1 otherwise. Used to decide which
# steps to skip when re-running on an existing install.
read_env_value() {
  local var="$1"
  local file="$INSTALL_DIR/.env"
  [[ -f "$file" ]] || return 1
  local value
  value=$(grep -E "^${var}=" "$file" 2>/dev/null | head -1 | cut -d= -f2- || true)
  [[ -n "$value" ]] || return 1
  printf '%s' "$value"
}

EXISTING_INSTALL=0
if [[ -f "$INSTALL_DIR/.env" ]]; then
  EXISTING_INSTALL=1
  ok "Existing install detected at $INSTALL_DIR — resuming"
  ok "  (secrets in your .env will be preserved untouched)"
else
  info "Fresh install (no $INSTALL_DIR/.env found)"
fi

# ─── Step 4: Registry reachability (anonymous) ────────────────────────
info "Step 4/7 — registry reachability"

# Every Phantom image is public on GHCR: no account, token or `docker
# login` is needed. This only confirms the anonymous pull-token
# endpoint answers, so a blocked egress shows up here with a clear
# message instead of as a pull error at step 7. It warns rather than
# fails: the docker daemon may reach GHCR through its own proxy
# settings even when this shell cannot.
if curl -fsS -o /dev/null --max-time 15 \
     "https://${GHCR_REGISTRY}/token?service=${GHCR_REGISTRY}&scope=repository:${GHCR_OWNER}/phantom-agent-oss:pull" \
     2>/dev/null; then
  ok "${GHCR_REGISTRY} reachable (images are public; no login needed)"
else
  warn "Could not reach ${GHCR_REGISTRY} from this shell. If the pull at step 7"
  warn "fails, allow outbound HTTPS to ${GHCR_REGISTRY} (and configure the"
  warn "docker daemon's proxy if the host uses one)."
fi

# ─── Step 5: Runtime secrets (reuse or generate) ──────────────────────
info "Step 5/7 — runtime secrets"

if [[ "$EXISTING_INSTALL" == "1" ]]; then
  # Verify all required secrets are still present in .env. We don't
  # need to load their values into bash variables (we won't rewrite
  # .env), just confirm they exist and are non-empty.
  missing_secrets=()
  for var in MCP_TOKEN PHANTOM_SECRET_KEK CALDERA_API_KEY \
             XLOG_API_KEY CALDERA_RED_PASSWORD; do
    if ! read_env_value "$var" >/dev/null; then
      missing_secrets+=("$var")
    fi
  done
  if [[ ${#missing_secrets[@]} -gt 0 ]]; then
    die "Existing $INSTALL_DIR/.env is missing required values: ${missing_secrets[*]}
       Either restore them manually or delete the .env to reset.
       NOTE: deleting .env destroys PHANTOM_SECRET_KEK, which means any
       operator secrets you've stored via the UI become unreadable."
  fi
  ok "Reusing existing secrets from $INSTALL_DIR/.env"

  # Back-fill PHANTOM_DEFAULT_ADMIN_PASSWORD on installs whose .env
  # doesn't carry it yet. This value is consumed by the
  # agent's entrypoint seed step on first boot of a fresh SecretStore;
  # on upgrades with an existing SecretStore it's never consulted. So
  # back-fill on upgrade is harmless + future-proofs against a later
  # factory-reset on this host (which would wipe SecretStore but keep
  # .env, then need the seed value).
  #
  # Both branches (back-fill OR already-present) ALSO assign the
  # value to the bash variable space, so the installer's epilogue
  # banner ("First-time login: …") can substitute it without
  # tripping `set -u`. Bytes-on-disk vs. shell-var-space are separate
  # namespaces; both have to be set on every path.
  if PHANTOM_DEFAULT_ADMIN_PASSWORD=$(read_env_value PHANTOM_DEFAULT_ADMIN_PASSWORD); then
    : # already present in .env (and now in the bash var)
  else
    PHANTOM_DEFAULT_ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)"
    {
      echo ""
      echo "# ─── Bootstrap admin password ────────────────────────────────────────"
      echo "# Auto-generated by phantom-installer (back-fill)."
      echo "# Consumed only when SecretStore is empty (fresh install OR after"
      echo "# phantom-factory-reset). Forced password change at /profile makes"
      echo "# this irrelevant after first login."
      echo "PHANTOM_DEFAULT_ADMIN_PASSWORD=$PHANTOM_DEFAULT_ADMIN_PASSWORD"
    } >> "$INSTALL_DIR/.env"
    ok "Back-filled PHANTOM_DEFAULT_ADMIN_PASSWORD"
  fi
else
  # Fresh install — generate everything. PHANTOM_SECRET_KEK is the only
  # load-bearing one for stored operator data; the others are bundle-
  # internal coordination or first-boot seeds.
  MCP_TOKEN="$(openssl rand -hex 32)"
  PHANTOM_SECRET_KEK="$(openssl rand -base64 32)"
  CALDERA_API_KEY="$(openssl rand -hex 16)"
  XLOG_API_KEY="$(openssl rand -hex 32)"
  CALDERA_RED_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)"
  # Admin bootstrap password. Random per install, so no credential is
  # baked anywhere in any image.
  PHANTOM_DEFAULT_ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)"
  ok "6 runtime secrets generated"
fi

# ─── Step 6: Refresh files ────────────────────────────────────────────
info "Step 6/7 — refreshing $INSTALL_DIR/{docker-compose.yml,.env}"

mkdir -p "$INSTALL_DIR"
chmod 755 "$INSTALL_DIR"

# docker-compose.yml — ALWAYS write fresh. The embedded YAML below is
# sealed at the installer's version (deterministic from VERSION), so
# overwriting on every run is safe and ensures the operator gets
# whatever compose-level fixes the installer version brings. Customers
# are not expected to hand-edit this file; if you do, it'll be replaced
# next time you run the installer.
cat > "$INSTALL_DIR/docker-compose.yml" <<'_PHANTOM_COMPOSE_HEREDOC_END_'
__INSTALLER_COMPOSE_YAML__
_PHANTOM_COMPOSE_HEREDOC_END_
chmod 644 "$INSTALL_DIR/docker-compose.yml"
ok "docker-compose.yml refreshed"

# Host-side recovery utilities, embedded in the installer
# binary the same way the compose YAML is embedded (heredoc with a
# unique terminator). Two scripts ship:
#
#   1. phantom-factory-reset            — wipes phantom_* volumes +
#      re-runs this installer. MUST be host-side because a container
#      can't delete the volume it's mounting.
#
#   2. phantom-reset-admin-password     — thin host wrapper around
#      the in-container `/app/cli/reset-admin.mjs` CLI. Host-side for
#      operator-UX consistency with factory-reset (same invocation
#      shape: sudo /opt/phantom/phantom-<utility>) while the credential
#      write itself stays inside the agent boundary that already owns
#      the SecretStore + audit machinery.
#
# Why embedded here vs. shipped as separate files in the multi-file
# install kit only: the single-file `phantom-installer` is the customer-
# primary distribution path (one binary, gh release download + run).
# Embedding the recovery utilities means operators ALWAYS have them on
# disk at /opt/phantom/ after install — no second download, no
# "wait, where's the script?" support ticket. Both utilities share
# one invocation shape (sudo /opt/phantom/phantom-<utility>).
cat > "$INSTALL_DIR/phantom-factory-reset" <<'_PHANTOM_FACTORY_RESET_HEREDOC_END_'
__INSTALLER_FACTORY_RESET_SH__
_PHANTOM_FACTORY_RESET_HEREDOC_END_
chmod 755 "$INSTALL_DIR/phantom-factory-reset"
ok "phantom-factory-reset refreshed"

cat > "$INSTALL_DIR/phantom-reset-admin-password" <<'_PHANTOM_RESET_PASSWORD_HEREDOC_END_'
__INSTALLER_RESET_PASSWORD_SH__
_PHANTOM_RESET_PASSWORD_HEREDOC_END_
chmod 755 "$INSTALL_DIR/phantom-reset-admin-password"
ok "phantom-reset-admin-password refreshed"

# .env — preserve existing on resume; write fresh on first install.
# The .env is the source of truth for the customer's runtime state
# (secrets, KEK, image-digest pins). Re-runs must NEVER clobber it —
# that would rotate PHANTOM_SECRET_KEK and lock out operator secrets
# stored via the UI.
#
# Version pinning happens via the digest manifest, not via a bare
# PHANTOM_VERSION=tag line. The block below ALWAYS strips any existing
# DIGEST_PHANTOM_* lines + the PHANTOM_VERSION line from the .env
# (regardless of fresh/existing) and re-appends the manifest from the
# embedded heredoc. This means:
#   - Fresh install: heredoc writes secrets, then manifest section
#     appends version + digests in one consistent block.
#   - Re-run / upgrade: existing secrets + KEK preserved, stale digest
#     pins stripped, new digests appended.

if [[ "$EXISTING_INSTALL" == "1" ]]; then
  CURRENT_VERSION=$(read_env_value PHANTOM_VERSION || echo "unknown")
  if [[ "$CURRENT_VERSION" == "$PHANTOM_VERSION" ]]; then
    ok "Already at v$PHANTOM_VERSION — refreshing digest manifest only"
  else
    info "Upgrading $CURRENT_VERSION → $PHANTOM_VERSION (digest manifest will replace)"
  fi
  ok "Existing secrets + KEK in $INSTALL_DIR/.env preserved"
else
  # Heredoc with shell interpolation enabled (no quotes around the
  # delimiter) so the secrets generated above expand. mode 600 because
  # the KEK and the service credentials are sensitive.
  #
  # Note: PHANTOM_VERSION is NOT written here. It lives in the digest
  # manifest section appended below, which is the single source of
  # truth for both the version label AND the per-image digests.
  cat > "$INSTALL_DIR/.env" <<EOF
# Generated by phantom-installer (v$PHANTOM_VERSION) on $(date -u +%Y-%m-%dT%H:%M:%SZ).
# Edit by hand if needed; the in-app updater reads from here too.
#
# The PHANTOM_VERSION line + DIGEST_PHANTOM_* lines at the
# bottom of this file are MANIFEST-MANAGED. Re-running phantom-installer
# (or the in-app updater) strips and re-appends them as a unit. Editing
# them by hand is supported but next install/upgrade will overwrite.

# ─── Internal MCP coordination token ──────────────────────────────────
MCP_TOKEN=$MCP_TOKEN

# ─── Encryption-at-rest KEK for SecretStore ───────────────────────────
# WARNING: losing this makes existing stored operator secrets
# unrecoverable. Back this up alongside your other deployment creds.
PHANTOM_SECRET_KEK=$PHANTOM_SECRET_KEK

# ─── Bootstrap admin password ────────────────────────────────────────
# Seeded into SecretStore on first boot. The agent forces you to change
# it at /profile on first login, after which this value is never
# consulted. If you lose it before changing the password, run
# sudo /opt/phantom/phantom-reset-admin-password from the host.
# No credential is baked into any image.
PHANTOM_DEFAULT_ADMIN_PASSWORD=$PHANTOM_DEFAULT_ADMIN_PASSWORD

# ─── Caldera ──────────────────────────────────────────────────────────
CALDERA_RED_USER=red
CALDERA_RED_PASSWORD=$CALDERA_RED_PASSWORD
CALDERA_API_KEY=$CALDERA_API_KEY

# ─── xlog ─────────────────────────────────────────────────────────────
XLOG_API_KEY=$XLOG_API_KEY

# ─── Operator config (filled in via /providers + /instances after login) ─
# Leaving these blank is fine. The agent boots with default
# admin credentials (admin / value of PHANTOM_DEFAULT_ADMIN_PASSWORD
# above) and the operator configures providers + connector instances
# via the UI after signing in and rotating the default password at
# /profile.
EOF
  chmod 600 "$INSTALL_DIR/.env"
  ok "Wrote $INSTALL_DIR/.env"
fi

# ─── Step 6.5: Apply the digest manifest to .env ──────────────────────
# The customer compose references each image by digest
# (`@${DIGEST_<SVC>}`). Without DIGEST_* values in .env, docker compose
# resolves them to the explicit-invalid fallback and fails loudly. So
# this step is load-bearing: if it doesn't run, the whole stack fails
# to come up.
#
# Pattern: strip any pre-existing PHANTOM_VERSION + DIGEST_PHANTOM_*
# lines (left over from a prior version's manifest), then append the
# embedded manifest as a clean block. Idempotent on repeat runs.
info "Applying digest manifest for v$PHANTOM_VERSION"

# Sanity: refuse to proceed if the embedded manifest is the build-time
# placeholder (i.e. this binary was built without MANIFEST_PATH). That
# would be a dev-build mistake; the release workflow always passes
# the manifest. Failing here protects the operator from a half-broken
# stack with invalid digests.
if printf '%s' "$DIGEST_MANIFEST" | grep -q '^DIGEST_MANIFEST_MISSING=1'; then
  die "This phantom-installer was built without an embedded digest
       manifest (DIGEST_MANIFEST_MISSING=1). It cannot install a
       stack because the customer compose requires per-image digests
       in .env.

       This is a build-time failure, not an operator-fixable runtime
       issue. Download a customer release binary from:
         https://github.com/ayman-m/phantom/releases/tag/v$PHANTOM_VERSION"
fi

# Validate the manifest has the expected keys before we touch .env.
# Minimum bar: PHANTOM_VERSION matches this binary, plus the 4
# always-on stack-service digests are present. DIGEST_PHANTOM_BROWSER
# is deliberately NOT required - phantom-browser is
# profile-gated (only starts when an operator opts into the browser
# profile via `docker compose --profile browser up`), so a release can
# ship without a fresh image for it without blocking install for
# everyone else. Per-instance connector digests are validated by
# phantom-updater at runtime (less load-bearing here because they're
# only needed when the operator creates a connector instance).
_required_keys=(
  "PHANTOM_VERSION=$PHANTOM_VERSION"
  "DIGEST_PHANTOM_AGENT="
  "DIGEST_PHANTOM_XLOG="
  "DIGEST_PHANTOM_CALDERA="
  "DIGEST_PHANTOM_UPDATER="
)
for key in "${_required_keys[@]}"; do
  if ! printf '%s' "$DIGEST_MANIFEST" | grep -q "^${key}"; then
    die "Embedded digest manifest is missing required key matching '${key}'.
         This binary appears corrupted; re-download from:
           https://github.com/ayman-m/phantom/releases/tag/v$PHANTOM_VERSION"
  fi
done

# Ensure the .env ends with a newline before we strip + append (some
# editors leave files without one, which makes the appended block run
# onto the last existing line).
if [[ -s "$INSTALL_DIR/.env" ]] && [[ "$(tail -c 1 "$INSTALL_DIR/.env" | xxd -p 2>/dev/null)" != "0a" ]]; then
  printf '\n' >> "$INSTALL_DIR/.env"
fi

# Strip stale manifest-managed lines AND the comment header block we
# emit alongside them, so re-runs never accumulate orphan comment
# headers while the value lines rotate.
#
# Patterns:
#   * VALUE lines: PHANTOM_VERSION= + DIGEST_PHANTOM_*= (pinned at line
#     start so we never false-positive on DIGEST_PHANTOM_AGENT_DEPRECATED
#     etc. that some future operator script might add).
#   * HEADER comment block: 4 lines emitted by this installer below.
sed -i.bak \
  -e '/^# ─── Digest manifest (managed by /d' \
  -e '/^# DO NOT EDIT BY HAND\./d' \
  -e '/^# strips and rewrites these lines/d' \
  -e "/^# version, download that version's phantom-installer/d" \
  -e '/^# these lines as a unit from the bundled/d' \
  -e '/^PHANTOM_VERSION=/d' \
  -e '/^PHANTOM_OWNER=/d' \
  -e '/^DIGEST_PHANTOM_/d' \
  "$INSTALL_DIR/.env"
rm -f "$INSTALL_DIR/.env.bak"

# Operator config-file separation principle. Per-instance
# connector image digests (DIGEST_PHANTOM_CONNECTOR_*) DO NOT belong
# in .env. .env is for service credentials + the 5 core compose-
# substitution digests that docker-compose interpolates. Connector
# image refs are runtime data phantom-updater uses to spawn dynamic
# instance containers — they live in a dedicated file at
# /opt/phantom/connector-digests.env (mounted into phantom_updater
# as /host/connector-digests.env). The strip above already removed
# DIGEST_PHANTOM_CONNECTOR_* lines from .env via the catch-all
# `DIGEST_PHANTOM_` pattern. The connector-digests.env file is fully
# rewritten below from the embedded manifest.

# Collapse consecutive blank lines that the strip above may leave
# behind (one per stripped block). awk is portable across BSD/GNU
# sed differences in '-s' / squeeze-blanks support.
awk 'NF || prev_nf { print } { prev_nf = NF }' \
  "$INSTALL_DIR/.env" > "$INSTALL_DIR/.env.tmp" \
  && mv "$INSTALL_DIR/.env.tmp" "$INSTALL_DIR/.env"

# Split the embedded manifest into two destinations:
#   * Core (PHANTOM_VERSION + 5 stack-service digests + anything that
#     isn't a per-connector digest) → /opt/phantom/.env. Required by
#     docker-compose's image-ref substitution at stack-up time.
#   * Per-connector digests (DIGEST_PHANTOM_CONNECTOR_*) → /opt/phantom/
#     connector-digests.env. Read by phantom-updater at runtime to
#     spawn dynamic instance containers. NOT a compose substitution.
#
# This satisfies the operator config-file separation principle
# (see CLAUDE.md § Operator config-file separation): .env holds
# credentials + compose substitutions; connector-digests.env holds
# per-instance image pins.
CORE_MANIFEST=$(printf '%s\n' "$DIGEST_MANIFEST" | grep -v '^DIGEST_PHANTOM_CONNECTOR_' || true)
CONNECTOR_MANIFEST=$(printf '%s\n' "$DIGEST_MANIFEST" | grep '^DIGEST_PHANTOM_CONNECTOR_' || true)

# Append the core manifest to .env (compose substitutions + version).
{
  echo ""
  echo "# ─── Digest manifest (managed by phantom-installer v$PHANTOM_VERSION) ──"
  echo "# DO NOT EDIT BY HAND. Re-running the installer (or the in-app updater)"
  echo "# strips and rewrites these lines as a unit. To install a different"
  echo "# version, download that version's phantom-installer binary."
  echo "# Note: per-connector image pins live in"
  echo "# $INSTALL_DIR/connector-digests.env. .env is for credentials"
  echo "# + the 5 core compose-substitution digests only."
  printf '%s\n' "$CORE_MANIFEST"
} >> "$INSTALL_DIR/.env"

chmod 600 "$INSTALL_DIR/.env"

# Write the connector-digests.env file from scratch. Idempotent on
# repeat runs (full rewrite, not append). chmod 644 — the file is
# not sensitive (image digests are public refs), and phantom_updater
# reads it via a read-only bind-mount as a non-root user inside the
# container.
if [[ -n "$CONNECTOR_MANIFEST" ]]; then
  {
    echo "# Per-instance connector image pins (managed by"
    echo "# phantom-installer v$PHANTOM_VERSION). Read by phantom-updater"
    echo "# at runtime to spawn dynamic connector instance containers."
    echo "#"
    echo "# This file is the canonical home for"
    echo "# DIGEST_PHANTOM_CONNECTOR_* values. Per the operator config-"
    echo "# file separation principle (CLAUDE.md), connector image refs"
    echo "# do NOT belong in .env: they aren't docker-compose"
    echo "# substitutions, they're runtime data for phantom-updater."
    echo "#"
    echo "# DO NOT EDIT BY HAND. Re-running the installer rewrites this"
    echo "# file from the version-pinned manifest."
    printf '%s\n' "$CONNECTOR_MANIFEST"
  } > "$INSTALL_DIR/connector-digests.env"
  chmod 644 "$INSTALL_DIR/connector-digests.env"
  _connector_count=$(printf '%s\n' "$CONNECTOR_MANIFEST" | grep -c '^DIGEST_' || true)
else
  # No connector digests in the manifest (a build that did not bundle
  # them). Create an empty
  # placeholder so the volume mount in docker-compose doesn't fail.
  {
    echo "# Per-instance connector image pins. This file is"
    echo "# empty because the installer binary's embedded manifest did"
    echo "# not include DIGEST_PHANTOM_CONNECTOR_* entries. phantom-"
    echo "# updater will fall back to tag-pinning."
  } > "$INSTALL_DIR/connector-digests.env"
  chmod 644 "$INSTALL_DIR/connector-digests.env"
  _connector_count=0
fi

_core_count=$(printf '%s\n' "$CORE_MANIFEST" | grep -c '^DIGEST_' || true)
ok "Digest manifest applied: PHANTOM_VERSION=$PHANTOM_VERSION + $_core_count core + $_connector_count connector digests"

# ─── Step 7: pull + up + wait healthy ─────────────────────────────────
info "Step 7/7 — pulling images and starting the stack"

cd "$INSTALL_DIR"

# Pull all images (anonymous: the images are public). First pull on a fresh box can take several minutes
# (~1 GB total across the four images on amd64).
info "Pulling images (this may take a few minutes on first install)…"
docker compose pull
ok "Images pulled"

# Bring the stack up.
info "Starting Phantom…"
docker compose up -d --remove-orphans
ok "Stack started"

# Wait for phantom-agent's healthcheck. The healthcheck verifies BOTH
# the Next.js UI and the embedded MCP, so green here means everything's
# actually serving traffic.
info "Waiting for phantom-agent to become healthy (up to ${HEALTH_TIMEOUT_SECS}s)…"
deadline=$(( $(date +%s) + HEALTH_TIMEOUT_SECS ))
status="starting"
while [[ "$(date +%s)" -lt "$deadline" ]]; do
  status=$(docker inspect -f '{{.State.Health.Status}}' phantom_agent 2>/dev/null || echo missing)
  case "$status" in
    healthy)
      break
      ;;
    unhealthy)
      warn "phantom-agent reports unhealthy — recent logs:"
      docker compose logs --tail 20 phantom-agent >&2 || true
      ;;
  esac
  sleep 5
done

if [[ "$status" != "healthy" ]]; then
  echo ""
  warn "phantom-agent did not become healthy within ${HEALTH_TIMEOUT_SECS}s."
  warn "Diagnostic commands:"
  warn "    docker compose -f $INSTALL_DIR/docker-compose.yml ps"
  warn "    docker compose -f $INSTALL_DIR/docker-compose.yml logs phantom-agent"
  warn "    docker compose -f $INSTALL_DIR/docker-compose.yml logs phantom-updater"
  exit 1
fi

ok "phantom-agent healthy"

# ─── Self-install: persist this binary to $INSTALL_DIR ───────────────
#
# After the stack is up, copy this installer binary itself to
# $INSTALL_DIR/ under the standard name (phantom-installer for release
# builds, phantom-installer-dev for dev builds — derived from this
# script's basename). This is what makes phantom-factory-reset's
# auto-recovery step work: post-wipe, factory-reset re-runs whichever
# binary it finds at $INSTALL_DIR/phantom-installer{,-dev}.
#
# Why post-install rather than pre: we only persist the binary if the
# install itself succeeded. A broken binary that managed to crash mid-
# install shouldn't get cached for future factory-resets to pick up.
#
# Without a persisted copy the binary would live wherever the operator
# ran it from (~/, /tmp/, a release-downloads folder), and factory-reset
# could not find it to re-run the install.
# Use INSTALLER_BINARY_PATH captured at the very top of this script
# (before the step-7 cd to $INSTALL_DIR). $0 here would be unreliable
# — by this point cwd has changed and a relative $0 won't resolve.
SELF_NAME="$(basename "$INSTALLER_BINARY_PATH")"
if [[ -f "$INSTALLER_BINARY_PATH" ]]; then
  # Only persist if the source path is OUTSIDE $INSTALL_DIR (avoid the
  # cp-self-onto-self error when re-running an already-persisted copy).
  case "$INSTALLER_BINARY_PATH" in
    "$INSTALL_DIR"/*) : ;;  # already there; no-op
    *)
      DEST="$INSTALL_DIR/$SELF_NAME"
      if cp "$INSTALLER_BINARY_PATH" "$DEST" 2>/dev/null && chmod +x "$DEST"; then
        ok "Persisted $SELF_NAME → $DEST (phantom-factory-reset will use this)"
      else
        warn "Could not persist $SELF_NAME to $DEST (continuing — factory-reset will warn but works)"
      fi
      ;;
  esac
else
  warn "Cannot self-persist installer: INSTALLER_BINARY_PATH=$INSTALLER_BINARY_PATH not found"
  warn "(factory-reset will hard-fail until you run a fresh installer)"
fi

# ─── Final message: tell the operator how to open it ─────────────────
# Try to find a non-loopback IPv4 the operator can hit from outside.
# Falls back to "localhost" if we can't determine one (e.g. inside a
# container with no network introspection).
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[[ -z "$HOST_IP" ]] && HOST_IP="localhost"

cat <<EOF

${C_GREEN}  ✓ Phantom v$PHANTOM_VERSION is running.${C_RESET}

  ${C_BOLD}Open in a browser:${C_RESET}    https://$HOST_IP:3000

  ${C_BOLD}Note:${C_RESET}                 The agent uses a self-signed cert. Your
                        browser will warn the first time; accept it
                        to proceed.

  ${C_BOLD}First-time login:${C_RESET}     Sign in with the default credentials:

                            username:  admin
                            password:  $PHANTOM_DEFAULT_ADMIN_PASSWORD

                        The password above is randomly
                        generated per install (no credential is baked
                        into any image). It also lives at
                        $INSTALL_DIR/.env under
                        PHANTOM_DEFAULT_ADMIN_PASSWORD if you need
                        to retrieve it after closing this terminal.

                        The UI will then show a non-dismissible banner
                        and redirect you to /profile. Change the
                        password there — the server revokes your
                        session and you'll be asked to sign in again
                        with the new credentials. After that, the
                        PHANTOM_DEFAULT_ADMIN_PASSWORD value above is
                        never consulted again (your operator-set
                        password lives encrypted in SecretStore).

  ${C_BOLD}Forgot password?${C_RESET}      Run from this host:
                            sudo $INSTALL_DIR/phantom-reset-admin-password

                        Interactive prompts ask for the new password
                        (no current-password required — the trust
                        boundary is your shell access to the host).
                        The script is a thin wrapper around the in-
                        container reset CLI; it handles the docker exec
                        and TTY plumbing for you.

  ${C_BOLD}Factory reset?${C_RESET}        Return to fresh-shipped state (wipes ALL
                        operator state — memories, instances, API keys,
                        audit log, sessions, jobs, notifications;
                        preserves .env so the KEK and service credentials survive):
                            sudo $INSTALL_DIR/phantom-factory-reset

                        The script lists what it'll delete and asks you
                        to type 'FACTORY RESET' before doing anything.
                        --yes skips the prompt, --dry-run shows the plan
                        without wiping. Re-runs the installer at the end
                        so the stack is back up by the time the script
                        returns.

  ${C_BOLD}Configure providers:${C_RESET}  After first login + password change, set
                        up your model provider at /providers (Vertex
                        AI service-account JSON or Gemini API key).
                        Connector instances live at /instances.

  ${C_BOLD}Files on disk:${C_RESET}        $INSTALL_DIR/
                          ├── docker-compose.yml    (don't hand-edit)
                          └── .env                  (your secrets — chmod 600)

  ${C_BOLD}Useful commands:${C_RESET}
    docker compose -f $INSTALL_DIR/docker-compose.yml ps
    docker compose -f $INSTALL_DIR/docker-compose.yml logs -f phantom-agent
    docker compose -f $INSTALL_DIR/docker-compose.yml down

  ${C_BOLD}Future updates:${C_RESET}       download the new phantom-installer binary
                        from the GitHub Releases page and run it with
                        sudo on this host. The installer detects the
                        existing install at $INSTALL_DIR and preserves
                        your secrets, KEK material, and operator state
                        across upgrades — only image digests + the
                        docker-compose.yml are refreshed.

                            https://github.com/ayman-m/phantom/releases

                        Phantom has no in-UI Update button by design;
                        upgrades happen via the installer only so the
                        operator stays in control of each upgrade point.

EOF
