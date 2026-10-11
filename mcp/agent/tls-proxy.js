#!/usr/bin/env node
/**
 * Phantom — minimal TLS-terminating reverse proxy.
 *
 * Used as a sidecar to Next.js when SSL is enabled. Listens on port
 * `PHANTOM_TLS_PORT` (default 3000) over HTTPS and forwards every
 * request unchanged to Next.js on `PHANTOM_TLS_BACKEND_PORT` (default
 * 3001) over plain HTTP on the loopback interface.
 *
 * Why a custom proxy instead of running Next.js directly with HTTPS:
 * Next.js's standalone mode auto-generates `server.js` which uses
 * Node's `http` module. There's no clean override point for the
 * listener type without forking the standalone output. A small
 * external proxy is the cheapest way to terminate TLS without
 * fighting the framework.
 *
 * Why no npm deps: Node's built-in `https`, `http`, and stream
 * primitives cover everything needed. `npm install`-ing http-proxy
 * or similar would add weight + supply-chain surface for a 60-line
 * task. Self-contained file = nothing to maintain in package.json.
 *
 * Streaming behavior:
 * - The proxy uses `req.pipe(upstream)` and `upstream.pipe(res)` so
 *   streamed responses (SSE, large file downloads) flow through with
 *   per-chunk forwarding, not whole-response buffering. Critical for
 *   the in-app updater's SSE progress stream.
 * - Headers are forwarded as-is in both directions. The only addition
 *   is X-Forwarded-* on the way in so Next.js can build correct
 *   absolute URLs (for Set-Cookie, redirects, etc.).
 * - Backpressure is handled automatically by `pipe()`'s default
 *   behavior — if the client is slow, the upstream socket pauses.
 *
 * SSL config — supports either:
 *   PHANTOM_TLS_CERT_FILE / PHANTOM_TLS_KEY_FILE  (paths, preferred)
 *   SSL_CERT_FILE / SSL_KEY_FILE                  (legacy paths, fallback)
 *   SSL_CERT_PEM  / SSL_KEY_PEM                   (inline PEM with \n escapes)
 *
 * The PHANTOM_-prefixed names exist because SSL_CERT_FILE collides with
 * OpenSSL/Python's outbound-trust env semantics — exporting it forces
 * Python's ssl module to use that single PEM as the entire CA bundle,
 * breaking outbound HTTPS calls (Vertex embedder, Gemini, etc.). The
 * entrypoint exports PHANTOM_TLS_CERT_FILE only; SSL_CERT_FILE remains
 * accepted here for back-compat with operator-supplied env files.
 */

const fs = require('node:fs');
const http = require('node:http');
const https = require('node:https');

const TLS_PORT     = parseInt(process.env.PHANTOM_TLS_PORT     || '3000', 10);
const BACKEND_PORT = parseInt(process.env.PHANTOM_TLS_BACKEND_PORT || '3001', 10);
const BACKEND_HOST = process.env.PHANTOM_TLS_BACKEND_HOST || '127.0.0.1';

// ─── PEM resolution ──────────────────────────────────────────────────
// Order: file path first, then inline PEM. Inline PEM gets \n-escapes
// expanded just like xlog and the MCP do.
function normalizePem(s) {
  if (!s) return s;
  s = s.replace(/\\n/g, '\n').replace(/\\r/g, '');
  for (const hdr of [
    '-----BEGIN CERTIFICATE-----',
    '-----END CERTIFICATE-----',
    '-----BEGIN PRIVATE KEY-----',
    '-----END PRIVATE KEY-----',
    '-----BEGIN RSA PRIVATE KEY-----',
    '-----END RSA PRIVATE KEY-----',
  ]) {
    if (hdr.startsWith('-----BEGIN')) {
      s = s.split(hdr).join(hdr + '\n');
    } else {
      s = s.split(hdr).join('\n' + hdr);
    }
  }
  while (s.includes('\n\n')) s = s.split('\n\n').join('\n');
  return s.trim() + '\n';
}

function loadPemMaterial() {
  // PHANTOM_TLS_CERT_FILE is preferred; fall back to SSL_CERT_FILE for
  // legacy installs (see file-header doc on the env-name collision).
  const certPath = process.env.PHANTOM_TLS_CERT_FILE || process.env.SSL_CERT_FILE;
  const keyPath  = process.env.PHANTOM_TLS_KEY_FILE  || process.env.SSL_KEY_FILE;
  const certPem  = process.env.SSL_CERT_PEM;
  const keyPem   = process.env.SSL_KEY_PEM;

  let cert, key;

  if (certPath) {
    cert = fs.readFileSync(certPath, 'utf8');
  } else if (certPem) {
    cert = normalizePem(certPem);
  }

  if (keyPath) {
    key = fs.readFileSync(keyPath, 'utf8');
  } else if (keyPem) {
    key = normalizePem(keyPem);
  }

  if (!cert || !key) {
    console.error('[tls-proxy] FATAL: SSL_CERT_* and SSL_KEY_* must both be set');
    process.exit(1);
  }
  return { cert, key };
}

// ─── Proxy logic ─────────────────────────────────────────────────────
function proxyRequest(clientReq, clientRes) {
  // Build the upstream-bound request. Headers are forwarded as-is
  // except X-Forwarded-* which we set so Next.js can build absolute
  // URLs correctly (for Set-Cookie, redirects, etc.).
  const upstreamHeaders = { ...clientReq.headers };
  upstreamHeaders['x-forwarded-proto']  = 'https';
  upstreamHeaders['x-forwarded-port']   = String(TLS_PORT);
  upstreamHeaders['x-forwarded-for']    = (
    clientReq.headers['x-forwarded-for']
      ? `${clientReq.headers['x-forwarded-for']}, `
      : ''
  ) + clientReq.socket.remoteAddress;

  const upstreamReq = http.request({
    host:    BACKEND_HOST,
    port:    BACKEND_PORT,
    method:  clientReq.method,
    path:    clientReq.url,
    headers: upstreamHeaders,
  });

  // Forward upstream's response back to the client unchanged.
  upstreamReq.on('response', (upstreamRes) => {
    clientRes.writeHead(upstreamRes.statusCode || 502, upstreamRes.headers);
    upstreamRes.pipe(clientRes);
  });

  // Bubble upstream errors to the client. 502 is the canonical
  // "downstream failed" code.
  upstreamReq.on('error', (err) => {
    console.error('[tls-proxy] upstream error:', err.code || err.message);
    if (!clientRes.headersSent) {
      clientRes.writeHead(502, { 'content-type': 'text/plain' });
    }
    clientRes.end('502 Bad Gateway: backend unavailable\n');
  });

  // Forward the client's body to upstream. `pipe()` handles
  // backpressure automatically.
  clientReq.pipe(upstreamReq);
}

// ─── Server boot ─────────────────────────────────────────────────────
const { cert, key } = loadPemMaterial();

const server = https.createServer({ cert, key }, proxyRequest);

server.on('clientError', (err, socket) => {
  // TLS handshake failures, malformed requests, etc. Don't crash —
  // just close the socket and log.
  console.error('[tls-proxy] client error:', err.code || err.message);
  if (!socket.destroyed) {
    try { socket.end('HTTP/1.1 400 Bad Request\r\n\r\n'); } catch {}
    socket.destroy();
  }
});

server.listen(TLS_PORT, '0.0.0.0', () => {
  console.log(
    `[tls-proxy] HTTPS listening on :${TLS_PORT} → ` +
    `http://${BACKEND_HOST}:${BACKEND_PORT}`,
  );
});

// Graceful shutdown — entrypoint.sh sends SIGTERM on container stop.
for (const sig of ['SIGTERM', 'SIGINT']) {
  process.on(sig, () => {
    console.log(`[tls-proxy] received ${sig}, closing server`);
    server.close(() => process.exit(0));
    // Hard timeout in case in-flight requests don't drain quickly.
    setTimeout(() => process.exit(0), 5000).unref();
  });
}
