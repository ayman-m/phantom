# Changelog

All notable changes to Phantom are documented here.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each release section is written in operator language, not git-shortlog language. For commit-level granularity, run `git log`.

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
