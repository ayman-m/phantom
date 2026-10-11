# Security policy

## Reporting a vulnerability

Please report security problems **privately**. Do not open a public issue, discussion or pull request for them.

Use GitHub private vulnerability reporting:

1. Go to the repository's **Security** tab.
2. Choose **Report a vulnerability** (or open `https://github.com/ayman-m/phantom/security/advisories/new`).
3. Describe the problem, the version or image digest you tested, and the steps to reproduce it.

Phantom is maintained by one person, so replies are best effort. You will get an acknowledgement in the advisory thread, and fixes are published as a new release with a CHANGELOG entry. Please give a reasonable time to fix a problem before you disclose it.

Do not include real credentials, tenant URLs or customer data in a report. Redact them, or use a throwaway install.

## Supported versions

Only the latest release is supported. Upgrade by running the installer of the newer release.

## Scope

In scope:

- The code and container images built from this repository: `phantom-agent` (the UI and the embedded MCP server), `xlog`, `phantom-updater`, `phantom-browser`, the connector images and the installer.
- Authentication and session handling for the operator UI and the REST API, API-key scopes, and the encrypted secret store.
- **The agent credential guardrail.** The chat agent must never be able to read, write, mint or rotate credentials (provider keys, connector secrets, API keys), directly or through another tool such as a batched action. A way to make the agent do that is a vulnerability.
- Leaks of secrets into logs, audit events, responses, backups or images.
- Container escape or privilege escalation through the compose stack, including the `phantom-updater` Docker socket mount.
- Injection, path traversal, SSRF or unsafe deserialisation in the services above.

Out of scope:

- Findings that need an already compromised host, a user with root or Docker access on the host, or a stolen admin session.
- The content of the synthetic logs. Attack-shaped events are the purpose of the tool. Phantom sends them only to destinations you configure.
- Missing hardening on the Docker host, the network or the Cortex tenant that you operate.
- The self-signed certificate that a fresh install generates. Replace it with your own if browsers warn.
- Third-party software that Phantom ships or builds, such as MITRE Caldera, Chromium, Python and npm packages. Report those to their own projects. If Phantom pins a vulnerable version, tell us.
- Denial of service by an authenticated operator who asks the log generator for more volume than is sensible. The generator has rate ceilings, but they are guard rails, not a security boundary.
- Automated scanner output without a demonstrated impact.

## What a good report contains

- The affected component and version (image digest or `PHANTOM_VERSION`).
- What an attacker needs first (network position, account, API-key scope).
- The impact you demonstrated.
- A minimal reproduction.
