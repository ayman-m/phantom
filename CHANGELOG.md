# Changelog

All notable changes to Phantom are documented here.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each release section is written in operator language, not git-shortlog language. For commit-level granularity, run `git log`.

---

## [v1.0.0] — Unreleased — *First public release*

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
