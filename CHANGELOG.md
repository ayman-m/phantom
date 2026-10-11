# Changelog

All notable changes to Phantom are documented here.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each release section is written in operator language, not git-shortlog language. For commit-level granularity, run `git log`.

---

## [v1.0.2] — 2026-10-11 — *Security update*

**Security: the MCP tool endpoint on port 8080 was not authenticated (affects v1.0.0, v1.0.1 and every earlier build).** The embedded MCP server's JSON-RPC endpoint (`/api/v1/stream/mcp`) accepted requests with no credential at all, and Phantom publishes port 8080 on the host. Anyone who could reach that port could list and call all of the agent's tools: run queries through any configured XSIAM or Cortex instance, start and stop log workers, create scheduled jobs, install or upload connectors. The UI and agent API on port 3000, and every REST route on 8080, were already authenticated and were not affected.

- **What changed.** The endpoint now requires `Authorization: Bearer <MCP_TOKEN>` (what the agent itself uses) or an API key that holds the `tools:call` scope. Anything else gets 401 or 403 before a tool is reached.
- **API keys no longer reach beyond their scopes on port 8080.** The REST routes there accepted any valid key at any scope, so a key minted for one purpose, say `audit:read` for a SIEM poller, could also read instances and settings and create jobs. A key is now accepted only where its scope is named (`audit:read` for the audit log, `settings:read` / `settings:write` for settings, `approvals:resolve` for approvals, `tools:call` for the tool endpoint; `*` covers those and nothing more). Everything else on 8080 needs the internal token. The agent API on port 3000 is unchanged.
- **The approval-bypass header** is honoured only from the agent's own token; from an API key it is ignored.
- **If you cannot upgrade yet:** block port 8080 from everything but the host itself (a host firewall rule, or publish it as `127.0.0.1:8080:8080` in `docker-compose.yml`), and treat any key that was ever issued as potentially misused: revoke and re-issue it after upgrading.
- **Client note.** If you call the tool endpoint from your own MCP client, send the token as `Authorization: Bearer <MCP_TOKEN>`.

**Dependencies.** Clears every critical and high dependency alert that GitHub reported on the public repository (2 critical, 9 high, plus the medium and low ones).

**Fixed.**

- **`xlog` runs on current, patched libraries.** It was pinned to 2024-era versions of FastAPI, Starlette, python-multipart, h11 and anyio. It now runs FastAPI 0.143, Starlette 1.7, Pydantic 2, Strawberry GraphQL 0.333, python-multipart 0.0.32, h11 0.16 and anyio 4.14. Three requirements nothing used (`ariadne`, `fastapi-utils`, `fastapi-cli`) were removed because they held the old versions in place.
- **The agent's build tooling no longer carries a vulnerable `postcss`.** Next.js pins its own copy; an npm override now points every copy at the patched release. The audit of production dependencies reports 0 vulnerabilities. One dev-only package (`braces`, used by Tailwind and ESLint) is rated high but has no patched release anywhere and is not part of the shipped image.
- **The request after a failed chat no longer gets an empty 400.** The TLS proxy in front of the UI reused upstream connections, and a chat stream that ended with an error (for example before any model provider is configured) left a connection behind that the next request picked up and Next rejected. Each request now uses its own connection to the backend.
- **Settings refuse a value of the wrong type.** The settings API stored whatever it was given, so a number for a text setting or the text `"false"` for a yes/no setting was saved and then read back as the wrong type. A value must now have the same JSON type as the setting's default; a mismatch is reported in the response's `rejected` list and nothing is stored for that key.
- **`xlog` starts reliably on a fresh database.** Its server runs several processes, and on a brand-new database file they could collide on the first SQLite setup step, killing one worker at startup (the supervisor restarted it). The step now retries briefly while another process holds the lock.

**Docs.** `/help/architecture#authentication` (API keys on the two ports), `/help/user#api-keys` (the scope table, now enforced) and the scope text on `/api-keys`.

---

## [v1.0.1] — 2026-10-11 — *Fresh-install fixes*

Two bugs found by installing v1.0.0 from the public release on a clean host (both made the first log-generation request fail), one hardening of the password change, and a fix for bare tool names.

**Fixed.**

- **A fresh install now serves xlog over HTTPS from the first start.** On an empty install the TLS certificate was created too late: the agent wrote it, but the agent only starts after `xlog` is healthy, and `xlog` had already given up waiting and fallen back to plain HTTP. Every log-generation tool then failed with `[SSL] record layer failure`, and `/api/agent/health` reported `degraded`. A new one-shot step, `phantom_tls_init`, creates the certificate before any of them starts, and never overwrites a certificate you supplied. It appears as `Exited (0)` in `docker compose ps -a`. No action is needed on an existing install: the certificate is already there.
- **Guessing the password through the Change password form is now rate-limited.** The form checks your current password, but unlike sign-in it had no lockout, so a stolen session cookie could be used to guess the password. Five wrong current passwords in a minute now lock the form for 60 seconds (HTTP 429), counted per source address and per session, with a separate counter from sign-in. Sign-in's own lockout also now keys on the address the proxy saw, not on a header the client can set, and attempts are counted before the password check so parallel guesses cannot slip through.
- **A bare tool name works in direct tool calls.** `^run_xql_query query=...` in chat, or a bare name sent to `/api/agent/tool/call`, was refused as "ambiguous" even when only one connector provides the tool, because each tool is advertised under its namespaced name and its legacy flat alias. Those two names are now recognised as the same tool and the namespaced one is used. When two connectors provide a tool with the same name (for example Cortex XDR and XSIAM), you still have to say which one, as before.
- **Generating logs without a vendor schema works again.** Asking the agent for a worker without a data-source schema (the generic path) was always rejected with `Field 'durationSeconds' is not defined by type 'WorkerFakerInput'`. Workers that use a data source's schema were not affected. On the generic path a worker stops after `count` events; `duration_seconds`, `max_events` and `continuous` apply only with a data-source schema, and the tool result now says so.

**Docs.** `/help/architecture#tls-proxy` (new subsection, "Who creates the certificate, and boot order"), a note under `#stack`, and the rate-limit bullet under `#authentication`; `/help/user#authentication` and the change-password journey mention the lockout.

---

## [v1.0.0] — 2026-10-11 — *First public release*

Phantom is a continuous SOC simulation platform for defensive detection engineering. It generates synthetic security telemetry, runs MITRE ATT&CK scenarios end to end, and lets an AI agent orchestrate red and blue workflows against your own detection stack over MCP. Everything it produces is synthetic log data sent only to destinations you control.

This is the first public release, so there is no upgrade path from earlier builds. Install v1.0.0 fresh with the `phantom-installer` from the GitHub Release.

**What you get.**

- **A five-service Docker Compose stack.** `phantom-agent` (the Next.js operator UI with an embedded Python MCP server, one trust boundary), `xlog` (the synthetic-log generator), `caldera` (MITRE Caldera for red-team operations), `phantom-updater` (per-instance connector container lifecycle) and `phantom-browser` (headless Chromium for web research). The installer writes credentials and pins every image by digest.
- **An AI agent in chat.** Describe a goal in plain language and the agent chains MCP tools and skills to reach it, with live tool-call telemetry, saved sessions, memory, knowledge bases, scheduled jobs, tasks, and approval and personality controls for how much it asks before acting on external systems.
- **Synthetic log generation.** The `xlog` engine produces CEF, syslog, LEEF and JSON events with consistent identities, field-level control, throughput reporting and bounded simulation workers.
- **Nearly 300 data sources.** Each describes the shape of one vendor's logs as the Cortex parsing and modeling rules expect them, so events land in the right dataset and map to the data model. Edit, pin, upload or install your own from the marketplace.
- **Scenario-based MITRE ATT&CK telemetry.** Ready-made multi-stage scenarios, plus Caldera operations with bundled abilities and adversaries for the real-endpoint side.
- **Pluggable connectors, one container per instance.** Built in: `xlog`, `xsiam`, `caldera`, `cortex-content`, `cortex-docs`, `cortex-xdr`, `web`, `http-sender` and `wec-sender`. Install them from the marketplace, configure instances in the UI, or upload your own `connector.yaml`.
- **Log destinations.** Send to a syslog or CEF broker, an HTTP collector, Splunk HEC, a webhook, or a Cortex Cribl endpoint.
- **Detection validation.** Skills and tools to run XQL, read alerts, datasets and cases, and check that a synthetic scenario produced the detection you meant to test.
- **Secure by default.** TLS everywhere, an encrypted secret store, PBKDF2 operator login, scoped API keys, and a hard boundary that keeps credentials out of the agent's reach: provider keys, connector secrets and API keys are managed only by you in the UI, never by the agent, including inside a batched plan.
- **Observability.** Metrics, traces, logs, audit events, runtime events, cost, pipeline health and live activity, all in the UI.
- **Operations.** Backup and restore from Settings, a REST API with a downloadable OpenAPI spec, and in-product architecture and user guides with step-by-step user journeys.

**Capability acceptance criteria.** On a fresh install an operator can log in, add a model provider, install a connector, ask the agent to generate logs for a data source, and see the events arrive at their own collector.

**Docs.** `/help/architecture`, `/help/user`, `/help/journeys` and `/help/api` in the running UI.
