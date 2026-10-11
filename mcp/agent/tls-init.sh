#!/usr/bin/env bash
# Populate the shared phantom_tls volume with a self-signed cert + key, once.
#
# This is the ONE place that creates TLS material for the stack. Two callers:
#
#   * the `phantom-tls-init` one-shot compose service (this script is its
#     entrypoint), which runs and exits BEFORE xlog and phantom-agent
#     start. Every consumer therefore finds the cert on disk at its own boot;
#     none has to guess, poll for, or reload it.
#   * entrypoint.sh, as a safety net for deployments that run the agent image
#     without the init service (docker-compose.agent-only.yml, `docker run`).
#     It is a no-op when the cert is already there.
#
# Why a separate step and not the agent's own boot: xlog reads
# /tls once, at process start. The agent used to write the cert, but compose
# starts the agent only after xlog is healthy, and xlog only turned healthy
# after giving up on the cert and serving plain HTTP. The cert was written
# about six seconds too late, every time, on a fresh volume.
#
# Idempotent and non-destructive: an existing cert + key pair (including one
# an operator supplied) is never touched. Output goes to stdout only; the key
# is never printed.

set -euo pipefail

TLS_DIR="${PHANTOM_TLS_DIR:-/tls}"
TLS_CERT="$TLS_DIR/cert.pem"
TLS_KEY="$TLS_DIR/key.pem"

log() { printf '[tls-init] %s\n' "$*"; }

mkdir -p "$TLS_DIR"

if [ -f "$TLS_CERT" ] && [ -f "$TLS_KEY" ]; then
  log "reusing existing TLS cert at $TLS_CERT (shared volume)"
  exit 0
fi

# Exactly one of the pair is useless on its own. Keep it aside rather than
# overwrite it, then generate a matched pair.
for f in "$TLS_CERT" "$TLS_KEY"; do
  if [ -f "$f" ]; then
    log "WARN: found $f without its partner; keeping it as $f.orphan and generating a new pair"
    mv "$f" "$f.orphan"
  fi
done

log "no TLS cert at $TLS_DIR/ — generating self-signed cert (TLS-by-default)"
# 2048-bit (vs the operator-facing 4096-bit) since this is short-lived bootstrap
# material; the operator replaces it by writing their own PEM to
# /tls/{cert,key}.pem. Sub-second even on a weak VM. Written to temp names in the
# same directory and renamed, so a reader never sees a half-written pair.
# openssl's messages carry no key material, so they are shown if it fails.
if ! err=$(openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout "$TLS_KEY.tmp" -out "$TLS_CERT.tmp" \
  -subj "/CN=phantom-setup/O=Phantom/OU=Auto-generated" \
  -addext "subjectAltName=DNS:localhost,DNS:phantom-agent,DNS:xlog,DNS:caldera,IP:127.0.0.1" \
  -addext "extendedKeyUsage=serverAuth" 2>&1); then
  log "ERROR: openssl could not create the certificate:"
  printf '%s\n' "$err" >&2
  rm -f "$TLS_KEY.tmp" "$TLS_CERT.tmp"
  exit 1
fi
chmod 600 "$TLS_KEY.tmp"
chmod 644 "$TLS_CERT.tmp"
mv "$TLS_KEY.tmp" "$TLS_KEY"
mv "$TLS_CERT.tmp" "$TLS_CERT"
log "wrote $TLS_CERT + $TLS_KEY"
