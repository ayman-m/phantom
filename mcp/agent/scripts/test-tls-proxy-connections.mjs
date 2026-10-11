// tls-proxy must open one upstream connection per request.
//
// With Node's default (pooling) agent, the socket behind a streamed response
// that ends abnormally stays in the pool and the next request reuses it;
// Next answered that request 400 with an empty body. Seen after any /api/chat
// call that failed, such as the one a first-time user makes before adding a
// model provider. This test counts the distinct upstream sockets across
// sequential requests: pooling gives 1, the fix gives one per request.
//
//   node scripts/test-tls-proxy-connections.mjs
import { spawn, spawnSync } from "node:child_process";
import http from "node:http";
import https from "node:https";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const proxyJs = path.join(here, "..", "tls-proxy.js");

if (spawnSync("openssl", ["version"]).status !== 0) {
  console.log("SKIP tls-proxy connection test: openssl not installed");
  process.exit(0);
}

const dir = mkdtempSync(path.join(tmpdir(), "tlsproxy-"));
const cert = path.join(dir, "cert.pem");
const key = path.join(dir, "key.pem");
const gen = spawnSync("openssl", ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
  "-keyout", key, "-out", cert, "-subj", "/CN=localhost"], { encoding: "utf8" });
if (gen.status !== 0) { console.error(gen.stderr); process.exit(1); }

const freePort = () => new Promise((res) => {
  const s = http.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); });
});

let failed = 0;
const check = (name, ok, extra = "") => { console.log(`${ok ? "PASS" : "FAIL"} ${name}${extra ? " | " + extra : ""}`); if (!ok) failed++; };

const upstreamSockets = new Set();
const upstream = http.createServer((req, res) => {
  upstreamSockets.add(req.socket);
  res.writeHead(200, { "content-type": "text/event-stream", connection: "keep-alive" });
  res.write("data: one\n\n");
  res.end();
});
await new Promise((r) => upstream.listen(0, "127.0.0.1", r));
const backendPort = upstream.address().port;
const tlsPort = await freePort();

const proxy = spawn(process.execPath, [proxyJs], {
  env: {
    ...process.env,
    PHANTOM_TLS_PORT: String(tlsPort),
    PHANTOM_TLS_BACKEND_PORT: String(backendPort),
    PHANTOM_TLS_BACKEND_HOST: "127.0.0.1",
    PHANTOM_TLS_CERT_FILE: cert,
    PHANTOM_TLS_KEY_FILE: key,
  },
  stdio: ["ignore", "pipe", "pipe"],
});

const ready = new Promise((res, rej) => {
  proxy.stdout.on("data", (d) => { if (String(d).includes("listening")) res(); });
  proxy.on("exit", (c) => rej(new Error("proxy exited early: " + c)));
  setTimeout(() => rej(new Error("proxy did not start")), 10000);
});

const get = () => new Promise((resolve, reject) => {
  https.get({ host: "127.0.0.1", port: tlsPort, path: "/", rejectUnauthorized: false, agent: false }, (r) => {
    r.resume(); r.on("end", () => resolve(r.statusCode));
  }).on("error", reject);
});

try {
  await ready;
  const codes = [];
  for (let i = 0; i < 4; i++) codes.push(await get());
  check("every request is answered 200", codes.every((c) => c === 200), codes.join(","));
  check("each request used its own upstream connection", upstreamSockets.size === 4, `${upstreamSockets.size} sockets for 4 requests`);
} catch (e) {
  check("proxy test ran", false, String(e));
} finally {
  proxy.kill();
  upstream.close();
  upstream.closeAllConnections?.();
  rmSync(dir, { recursive: true, force: true });
}
process.exit(failed ? 1 : 0);
