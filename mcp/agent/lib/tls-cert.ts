/**
 * Self-signed TLS certificate generation, called from the setup
 * route handler when the operator picks "Self-signed (auto-generate)".
 *
 * Approach: shell out to `openssl req -x509`. We could use a pure-Node
 * library (selfsigned, node-forge), but openssl is already in the
 * agent image (the embedded MCP uses it for its own SSL handling),
 * adding an npm dependency would expand the supply-chain surface for
 * the same job, and the openssl invocation here mirrors the bash
 * helper at installer/generate-self-signed-certs.sh — keeping ONE
 * cert-generation idiom across the codebase.
 *
 * Output shape mirrors the bash helper too: PEM strings ready to drop
 * into SSL_CERT_PEM and SSL_KEY_PEM env vars.
 */

import { spawnSync } from "child_process";
import { mkdtempSync, readFileSync, rmSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

export interface SelfSignedCert {
  certPem: string;
  keyPem: string;
  notBefore: string;
  notAfter: string;
  sanList: string[];
}

const DEFAULT_SAN_LIST = [
  "DNS:localhost",
  "DNS:phantom-agent",
  "DNS:xlog",
  "DNS:caldera",
  "DNS:phantom-updater",
  "IP:127.0.0.1",
];

/**
 * Generate a self-signed cert + key pair via openssl. Returns PEM
 * strings (NOT yet \n-escaped — escape for .env at the call site).
 *
 * @param opts.commonName  Subject CN (default "phantom").
 * @param opts.days        Validity period (default 365).
 * @param opts.extraSans   Additional SAN entries (e.g. ["DNS:my.phantom.example"]).
 *                         Default SANs cover compose-internal DNS + localhost.
 *
 * Throws if openssl isn't on PATH or returns non-zero.
 */
export function generateSelfSignedCert(
  opts: { commonName?: string; days?: number; extraSans?: string[] } = {},
): SelfSignedCert {
  const cn = opts.commonName ?? "phantom";
  const days = opts.days ?? 365;
  const sanList = [...DEFAULT_SAN_LIST, ...(opts.extraSans ?? [])];

  // Use a tmpdir with random name; clean up via try/finally so a thrown
  // openssl error doesn't leak the dir.
  const workDir = mkdtempSync(join(tmpdir(), "phantom-tls-"));
  try {
    const certFile = join(workDir, "cert.pem");
    const keyFile = join(workDir, "key.pem");

    const args = [
      "req", "-x509",
      "-newkey", "rsa:4096",
      "-nodes",                // unencrypted private key (service auto-bootstrap)
      "-days", String(days),
      "-keyout", keyFile,
      "-out", certFile,
      "-subj", `/CN=${cn}/O=Phantom/OU=Self-signed`,
      "-addext", `subjectAltName=${sanList.join(",")}`,
      "-addext", "basicConstraints=CA:FALSE",
      "-addext", "keyUsage=digitalSignature,keyEncipherment",
      "-addext", "extendedKeyUsage=serverAuth",
    ];

    const result = spawnSync("openssl", args, { encoding: "utf8" });
    if (result.status !== 0) {
      const stderr = (result.stderr || "").trim();
      throw new Error(
        `openssl req failed (exit ${result.status}): ${stderr || "no stderr"}`,
      );
    }

    const certPem = readFileSync(certFile, "utf8");
    const keyPem = readFileSync(keyFile, "utf8");

    // Pull dates back from the cert for the response payload.
    const dates = spawnSync(
      "openssl",
      ["x509", "-in", certFile, "-noout", "-startdate", "-enddate"],
      { encoding: "utf8" },
    );
    const notBefore =
      dates.stdout.match(/notBefore=(.+)/)?.[1]?.trim() ?? "";
    const notAfter =
      dates.stdout.match(/notAfter=(.+)/)?.[1]?.trim() ?? "";

    return { certPem, keyPem, notBefore, notAfter, sanList };
  } finally {
    rmSync(workDir, { recursive: true, force: true });
  }
}

/**
 * Validate that a string looks like a PEM-encoded certificate.
 * Lightweight regex check + openssl x509 dry-run; doesn't validate
 * trust chain (these are self-signed or operator-provided, no chain
 * to validate against).
 */
export function validateCertPem(pem: string): { valid: true } | { valid: false; error: string } {
  if (!pem.includes("-----BEGIN CERTIFICATE-----")) {
    return { valid: false, error: "Cert PEM missing BEGIN CERTIFICATE marker" };
  }
  if (!pem.includes("-----END CERTIFICATE-----")) {
    return { valid: false, error: "Cert PEM missing END CERTIFICATE marker" };
  }
  // Use openssl's parser as the authoritative validation.
  const result = spawnSync("openssl", ["x509", "-noout", "-text"], {
    input: pem,
    encoding: "utf8",
  });
  if (result.status !== 0) {
    return { valid: false, error: `openssl rejected cert: ${(result.stderr || "").trim() || "parse failed"}` };
  }
  return { valid: true };
}

export function validateKeyPem(pem: string): { valid: true } | { valid: false; error: string } {
  // Either form is fine (PKCS#8 PRIVATE KEY or PKCS#1 RSA PRIVATE KEY).
  if (
    !pem.includes("-----BEGIN PRIVATE KEY-----") &&
    !pem.includes("-----BEGIN RSA PRIVATE KEY-----") &&
    !pem.includes("-----BEGIN EC PRIVATE KEY-----")
  ) {
    return { valid: false, error: "Key PEM missing BEGIN PRIVATE KEY marker" };
  }
  // openssl pkey accepts any of those formats; if it succeeds the key
  // is loadable. Use stdin so we don't need a tmpfile.
  const result = spawnSync(
    "openssl",
    ["pkey", "-in", "/dev/stdin", "-noout"],
    { input: pem, encoding: "utf8" },
  );
  if (result.status !== 0) {
    return { valid: false, error: `openssl rejected key: ${(result.stderr || "").trim() || "parse failed"}` };
  }
  return { valid: true };
}

/**
 * Convert a multi-line PEM into a single line with literal \n escapes,
 * the form that .env files and compose interpolation handle cleanly.
 * Mirrors the awk transform in installer/generate-self-signed-certs.sh.
 */
export function pemToEnvEscape(pem: string): string {
  return pem.split("\n").join("\\n");
}

/**
 * Write cert + key PEM to the shared /tls/ volume. xlog, caldera, and
 * the agent's own tls-proxy all read from these paths — this is the
 * single source of truth for TLS material across the stack (replaced
 * the old SSL_CERT_PEM compose-env passthrough).
 *
 * Path is configurable via PHANTOM_TLS_DIR env (defaults to /tls) so
 * dev/test environments can point at an alternate location without
 * needing a Docker volume.
 *
 * Mode: cert 0644 (readable by all consumer containers), key 0600
 * (privileged). Containers that mount /tls:ro read both fine; the
 * mode is mostly for defense-in-depth when the volume backing store
 * is something with mixed permissions.
 */
export function writeTlsToSharedVolume(certPem: string, keyPem: string): {
  certPath: string;
  keyPath: string;
} {
  const dir = process.env.PHANTOM_TLS_DIR ?? "/tls";
  // mkdirSync is idempotent with recursive=true; no error if exists.
  mkdirSyncSafe(dir);

  const certPath = pathJoin(dir, "cert.pem");
  const keyPath = pathJoin(dir, "key.pem");

  writeFileSyncWithMode(certPath, certPem, 0o644);
  writeFileSyncWithMode(keyPath, keyPem, 0o600);

  return { certPath, keyPath };
}

/**
 * Remove the cert + key from /tls/. Used when the operator picks the
 * "disabled" TLS mode in setup — clears the shared volume so xlog,
 * caldera, and the agent's TLS detection all see "no cert" on next
 * boot and revert to plain HTTP.
 */
export function clearTlsFromSharedVolume(): void {
  const dir = process.env.PHANTOM_TLS_DIR ?? "/tls";
  for (const f of ["cert.pem", "key.pem"]) {
    try {
      unlinkSyncSafe(pathJoin(dir, f));
    } catch {
      // File may not exist if TLS was never set up; that's fine.
    }
  }
}

// ─── Local fs helpers (kept inline so the compile-time deps stay
// small — lib/tls-cert.ts is imported from API routes which have a
// tight bundling budget). ─────────────────────────────────────────

import { mkdirSync, writeFileSync, unlinkSync, chmodSync } from "fs";
import { join as pathJoin } from "path";

function mkdirSyncSafe(p: string): void {
  try { mkdirSync(p, { recursive: true }); } catch { /* exists, fine */ }
}

function writeFileSyncWithMode(p: string, data: string, mode: number): void {
  writeFileSync(p, data);
  chmodSync(p, mode);
}

function unlinkSyncSafe(p: string): void {
  unlinkSync(p);  // throws on missing — caller catches
}
