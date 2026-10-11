#!/usr/bin/env bash
# Builds the customer-facing single-file installer.
#
# Combines:
#   installer/phantom-installer.template.sh   (the script body)
#   installer/docker-compose.yml              (the compose YAML)
#   installer/phantom-factory-reset.sh        (host-side factory reset)
#   installer/phantom-reset-admin-password.sh (host-side admin-password reset)
#   ${MANIFEST_PATH}                          (digest manifest)
# into a single executable `phantom-installer` file by substituting
# five markers in the template:
#
#   __INSTALLER_COMPOSE_YAML__         ← replaced with the compose YAML
#   __INSTALLER_VERSION__              ← replaced with the literal version
#   __INSTALLER_DIGEST_MANIFEST__      ← replaced with the digest manifest
#   __INSTALLER_FACTORY_RESET_SH__     ← replaced with the factory-reset script
#   __INSTALLER_RESET_PASSWORD_SH__    ← replaced with the reset-admin script
#
# Usage:
#   VERSION=X.Y.Z MANIFEST_PATH=/path/to/release-manifest-vX.Y.Z.env \
#     ./installer/build-phantom-installer.sh
#
# When MANIFEST_PATH is not set (e.g. local dev builds without a full
# release pipeline), an empty placeholder manifest is embedded — the
# installer detects this at runtime and prints a clear error. Customer
# release builds ALWAYS pass MANIFEST_PATH.
#
# Why a Python one-liner for the substitution: sed and awk both have
# special-character handling problems with multi-kilobyte payloads
# that contain shell metacharacters. Python's str.replace is bulletproof.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Recovery utility paths. These are the canonical sources for
# the two host-side scripts that get embedded into the installer binary.
# Both can be overridden via env var for forks or vendored builds.
FACTORY_RESET_SH="${FACTORY_RESET_SH:-$SCRIPT_DIR/phantom-factory-reset.sh}"
RESET_ADMIN_SH="${RESET_ADMIN_SH:-$SCRIPT_DIR/phantom-reset-admin-password.sh}"

VERSION="${VERSION:-}"
if [[ -z "$VERSION" ]]; then
  echo "ERROR: VERSION env var required (e.g. VERSION=X.Y.Z $0)" >&2
  exit 1
fi
# Accept either semver (release builds) or 'dev-<short-sha>'
# (dev installer). Both shapes get baked into the binary's
# version string so operators can `phantom-installer --version` and
# see what they're running. Strict semver is enforced for release
# binaries via the release pipeline's v* tag gate; this script accepts
# both forms because the dev-installer path doesn't have that gate.
if ! printf '%s' "$VERSION" | grep -Eq '^([0-9]+\.[0-9]+\.[0-9]+|dev-[0-9a-f]{7,40})$'; then
  echo "ERROR: VERSION must be N.N.N semver or 'dev-<short-sha>' (got: $VERSION)" >&2
  exit 1
fi

TEMPLATE="$SCRIPT_DIR/phantom-installer.template.sh"
COMPOSE="$SCRIPT_DIR/docker-compose.yml"
OUTPUT_DIR="${OUTPUT_DIR:-$REPO_ROOT/dist}"
# OUTPUT_NAME selects the binary filename. Release builds use
# the default (phantom-installer); dev builds pass
# OUTPUT_NAME=phantom-installer-dev. The script body is identical
# between the two — the divergence lives in the manifest, not here.
OUTPUT_NAME="${OUTPUT_NAME:-phantom-installer}"
OUTPUT="$OUTPUT_DIR/$OUTPUT_NAME"

# Embed the digest manifest. If MANIFEST_PATH is unset or
# missing, fall through with a synthetic placeholder so the installer
# can produce a clear runtime error.
MANIFEST_PATH="${MANIFEST_PATH:-}"
if [[ -n "$MANIFEST_PATH" && -f "$MANIFEST_PATH" ]]; then
  MANIFEST_CONTENTS=$(cat "$MANIFEST_PATH")
  echo "ℹ Embedding digest manifest from $MANIFEST_PATH"
else
  echo "⚠ MANIFEST_PATH unset or missing (got: '$MANIFEST_PATH')." >&2
  echo "  The installer will be built with a placeholder manifest that" >&2
  echo "  fails loudly at install time. Customer-facing release builds" >&2
  echo "  must pass MANIFEST_PATH (the release pipeline does this automatically)." >&2
  MANIFEST_CONTENTS="# PLACEHOLDER MANIFEST — installer was built without MANIFEST_PATH.
# This is expected for local dev builds; customer releases always embed
# a real manifest captured from the release image-push step.
PHANTOM_VERSION=${VERSION}
DIGEST_MANIFEST_MISSING=1"
fi

[[ -f "$TEMPLATE" ]]          || { echo "ERROR: $TEMPLATE missing" >&2; exit 1; }
[[ -f "$COMPOSE" ]]           || { echo "ERROR: $COMPOSE missing" >&2; exit 1; }
[[ -f "$FACTORY_RESET_SH" ]]  || { echo "ERROR: $FACTORY_RESET_SH missing" >&2; exit 1; }
[[ -f "$RESET_ADMIN_SH" ]]    || { echo "ERROR: $RESET_ADMIN_SH missing" >&2; exit 1; }

mkdir -p "$OUTPUT_DIR"

# Substitution. Run via `python3 - <<PY` so the script body lives
# inline (no separate .py file to ship). Note: VERSION + MANIFEST_CONTENTS
# are passed in via env var (not interpolation) so any future change in
# the template's escaping rules can't bleed into the build script.
VERSION="$VERSION" \
  TEMPLATE="$TEMPLATE" \
  COMPOSE="$COMPOSE" \
  FACTORY_RESET_SH="$FACTORY_RESET_SH" \
  RESET_ADMIN_SH="$RESET_ADMIN_SH" \
  MANIFEST_CONTENTS="$MANIFEST_CONTENTS" \
  python3 - "$OUTPUT" <<'PY'
import os
import sys

out_path = sys.argv[1]
version = os.environ["VERSION"]

with open(os.environ["TEMPLATE"]) as f:
    template = f.read()
with open(os.environ["COMPOSE"]) as f:
    compose = f.read()
with open(os.environ["FACTORY_RESET_SH"]) as f:
    factory_reset = f.read()
with open(os.environ["RESET_ADMIN_SH"]) as f:
    reset_admin = f.read()
manifest = os.environ["MANIFEST_CONTENTS"]

# Sanity: each placeholder must appear EXACTLY ONCE in the template.
# A second occurrence (e.g. in a docstring header that mentions the
# marker by name) gets blind-substituted by str.replace() and produces
# a corrupt installer where the embedded payload is duplicated and
# bash tries to execute the second copy as commands. The same
# constraint applies to the digest-manifest marker.
#
# __INSTALLER_RESET_PASSWORD_SH__ is a host wrapper around
# /app/cli/reset-admin.mjs, and __INSTALLER_FACTORY_RESET_SH__ is the
# operator-facing factory-reset utility. The wrapper pattern means the
# credential-write logic lives in exactly one place (the in-container
# CLI); the host script just gives operators a clean invocation shape
# consistent with the factory-reset script's.
markers = (
    "__INSTALLER_COMPOSE_YAML__",
    "__INSTALLER_VERSION__",
    "__INSTALLER_DIGEST_MANIFEST__",
    "__INSTALLER_FACTORY_RESET_SH__",
    "__INSTALLER_RESET_PASSWORD_SH__",
)
for marker in markers:
    n = template.count(marker)
    if n != 1:
        print(f"ERROR: marker '{marker}' must appear EXACTLY ONCE in "
              f"the template (found {n}). Likely a documentation "
              "comment mentions it literally — rephrase so the literal "
              "token only appears at the substitution target.",
              file=sys.stderr)
        sys.exit(1)

# Image refs in the compose are digest-pinned (`@${DIGEST_*}`), not
# version-tag-pinned. The compose is shipped verbatim and the digests
# come from .env (the substitution happens at runtime when docker
# compose interpolates ${DIGEST_*} from the customer's .env).

# Sanity: each embedded payload must not contain ITS OWN heredoc
# terminator, or it'll prematurely close the heredoc. Each payload
# uses its own terminator so they can't collide with each other.
embeddings = (
    (compose,       "_PHANTOM_COMPOSE_HEREDOC_END_",          "compose YAML"),
    (manifest,      "_PHANTOM_DIGEST_MANIFEST_HEREDOC_END_",  "digest manifest"),
    (factory_reset, "_PHANTOM_FACTORY_RESET_HEREDOC_END_",    "factory-reset script"),
    (reset_admin,   "_PHANTOM_RESET_PASSWORD_HEREDOC_END_",   "reset-admin-password script"),
)
for payload, terminator, label in embeddings:
    if terminator in payload:
        print(f"ERROR: {label} contains '{terminator}' literal; "
              "rename the terminator in the template.", file=sys.stderr)
        sys.exit(1)

# Substitutions on the template.
out = template.replace("__INSTALLER_COMPOSE_YAML__", compose)
out = out.replace("__INSTALLER_VERSION__", version)
out = out.replace("__INSTALLER_DIGEST_MANIFEST__", manifest)
out = out.replace("__INSTALLER_FACTORY_RESET_SH__", factory_reset)
out = out.replace("__INSTALLER_RESET_PASSWORD_SH__", reset_admin)

# Sanity: every marker must have been substituted.
for marker in markers:
    if marker in out:
        print(f"ERROR: marker '{marker}' still present after build "
              f"(expected substitution didn't happen).", file=sys.stderr)
        sys.exit(1)

with open(out_path, "w") as f:
    f.write(out)

print(f"wrote {out_path} ({len(out):,} bytes)")
PY

chmod +x "$OUTPUT"

# Verify the output is at least syntactically valid bash.
if ! bash -n "$OUTPUT"; then
  echo "ERROR: generated phantom-installer has syntax errors" >&2
  exit 1
fi

# Compute SHA-256 alongside (matches the existing tarball pattern).
( cd "$OUTPUT_DIR" && sha256sum "$OUTPUT_NAME" > "${OUTPUT_NAME}.sha256" )

echo "✓ phantom-installer built for v$VERSION"
ls -lh "$OUTPUT" "${OUTPUT}.sha256"
