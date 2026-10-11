#!/usr/bin/env bash
# Generates a self-signed TLS certificate + private key suitable for
# Phantom's self-signed mode. The cert covers every hostname + IP an
# operator might use to reach the stack:
#
#   * localhost, 127.0.0.1            (local browser access)
#   * the host machine's hostname     (from `hostname`)
#   * the host machine's primary IP   (from `hostname -I`)
#   * phantom-agent, xlog, caldera, phantom-updater
#                                     (compose-internal DNS names)
#
# Output formats (controlled by --format):
#   files       — writes cert.pem + key.pem to --out-dir (default: ./certs/)
#   envvar      — prints SSL_CERT_PEM=... + SSL_KEY_PEM=... to stdout
#                 with embedded newlines escaped as \n, ready to paste
#                 into .env or `eval` into the current shell
#   both        — writes files AND prints envvar to stdout
#
# Default format is `both`. Validity is 365 days. The cert is generated
# fresh each run; do NOT call this on an installed Phantom unless you
# intend to rotate certs (active TLS connections will be invalidated).
#
# Usage:
#   ./installer/generate-self-signed-certs.sh
#   ./installer/generate-self-signed-certs.sh --out-dir /opt/phantom/certs
#   ./installer/generate-self-signed-certs.sh --format envvar > /tmp/ssl.env
#   eval "$(./installer/generate-self-signed-certs.sh --format envvar)"

set -euo pipefail

OUT_DIR="./certs"
FORMAT="both"
DAYS=365
KEY_BITS=4096
CN="phantom"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --format)
      FORMAT="$2"
      shift 2
      ;;
    --days)
      DAYS="$2"
      shift 2
      ;;
    --cn)
      CN="$2"
      shift 2
      ;;
    --help|-h)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "ERROR: unknown option '$1' (try --help)" >&2
      exit 1
      ;;
  esac
done

case "$FORMAT" in
  files|envvar|both) ;;
  *) echo "ERROR: --format must be files, envvar, or both" >&2; exit 1 ;;
esac

command -v openssl >/dev/null 2>&1 \
  || { echo "ERROR: openssl not found in PATH" >&2; exit 1; }

# ─── Build the SAN list ──────────────────────────────────────────────
# Compose-internal hostnames are stable; host-side we add whatever the
# OS reports. Using `2>/dev/null || true` so missing tools don't fail.
HOSTNAME_VAL="$(hostname 2>/dev/null || echo "")"
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")"

SANS="DNS:localhost,DNS:phantom-agent,DNS:xlog,DNS:caldera,DNS:phantom-updater,IP:127.0.0.1"
[[ -n "$HOSTNAME_VAL" ]] && SANS="$SANS,DNS:$HOSTNAME_VAL"
[[ -n "$HOST_IP" ]]      && SANS="$SANS,IP:$HOST_IP"

# ─── Generate ────────────────────────────────────────────────────────
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

CERT_FILE="$TMP_DIR/cert.pem"
KEY_FILE="$TMP_DIR/key.pem"

# req -x509 generates a self-signed cert directly (no separate CSR).
# -nodes means "no DES on the key" (i.e. unencrypted private key —
# correct for service auto-bootstrap; the operator can't unlock a
# password-protected key during boot).
openssl req -x509 \
  -newkey "rsa:$KEY_BITS" \
  -nodes \
  -days "$DAYS" \
  -keyout "$KEY_FILE" \
  -out "$CERT_FILE" \
  -subj "/CN=$CN/O=Phantom/OU=Self-signed" \
  -addext "subjectAltName=$SANS" \
  -addext "basicConstraints=CA:FALSE" \
  -addext "keyUsage=digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth" \
  2>/dev/null

# ─── Output ──────────────────────────────────────────────────────────
case "$FORMAT" in
  files|both)
    mkdir -p "$OUT_DIR"
    cp "$CERT_FILE" "$OUT_DIR/cert.pem"
    cp "$KEY_FILE"  "$OUT_DIR/key.pem"
    chmod 600 "$OUT_DIR/key.pem"
    chmod 644 "$OUT_DIR/cert.pem"
    echo "→ Wrote $OUT_DIR/cert.pem + $OUT_DIR/key.pem (mode 644 + 600)" >&2
    ;;
esac

case "$FORMAT" in
  envvar|both)
    # Convert multi-line PEM into a single line with literal \n
    # escapes — the form that `${PHANTOM_VAR:-}` in compose interpolates
    # cleanly AND the form the MCP's normalize_pem() function expects.
    cert_escaped=$(awk 'BEGIN{ORS="\\n"} {print}' "$CERT_FILE" | sed 's/\\n$//')
    key_escaped=$(awk  'BEGIN{ORS="\\n"} {print}' "$KEY_FILE"  | sed 's/\\n$//')
    if [[ "$FORMAT" == "both" ]]; then
      echo "" >&2
      echo "→ Add these to /opt/phantom/.env (or eval them):" >&2
      echo "" >&2
    fi
    printf 'SSL_CERT_PEM="%s"\n' "$cert_escaped"
    printf 'SSL_KEY_PEM="%s"\n'  "$key_escaped"
    ;;
esac

# Sanity output to stderr — the cert's SAN block + validity, so the
# caller can confirm what was generated without having to re-parse.
echo "" >&2
echo "→ Certificate details:" >&2
openssl x509 -in "$CERT_FILE" -noout -subject -dates 2>&1 | sed 's/^/    /' >&2
echo "    SAN: $SANS" >&2
