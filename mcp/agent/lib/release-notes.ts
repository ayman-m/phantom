/**
 * Release-notes history — bundled with the UI image so the About
 * modal works offline (customer environments may be air-gapped from
 * GitHub).
 *
 * Authoring contract:
 *   * Newest entry first. The modal renders in array order.
 *   * `version` is bare semver (no "v" prefix) so it compares
 *     directly with /api/agent/version.
 *   * `date` is ISO yyyy-mm-dd of the GHCR publish.
 *   * `highlights` are 3-7 bullets, operator-facing language. No
 *     internal commit shorthand. Aim for ~10-15 words each.
 *   * `categories` is optional structure for security-heavy releases
 *     where bullets-only flattens too much detail.
 *   * `headline` flags become visual badges in the modal — use
 *     sparingly. `security: true` adds a red shield. `breaking: true`
 *     adds a yellow warning.
 *
 * When you cut a release: prepend a new entry here in the same PR
 * that creates the tag. The image rebuilt for that tag will then
 * carry its own notes — no fetch from GitHub required.
 */

export interface ReleaseNote {
  version: string;
  date: string;
  title: string;
  highlights: string[];
  categories?: { name: string; items: string[] }[];
  security?: boolean;
  breaking?: boolean;
}

export const RELEASE_NOTES: ReleaseNote[] = [
  {
    version: "1.0.3",
    date: "2026-10-12",
    title: "Session lifetime, walkthrough fixes and corrected help pages.",
    highlights: [
      "New Session lifetime card on Profile: choose 1 to 24 hours; the default stays 2.",
      "Duplicate, model choice, Edit and paused-job times on Jobs now behave; job Description is saved.",
      "Rename and delete use in-app dialogs, and forks nest under their parent session.",
      "Notifications, Tasks, Skills, Knowledge, Providers and Services show only real data; Notifications controls work.",
      "Agent no longer changes the global model when asked; skills it names all exist.",
      "Uploaded connectors appear on Connectors and can be deleted; instance status survives a reload.",
      "Backups keep tested-journey marks; restore skips a section it cannot compare instead of writing blind.",
    ],
  },
  {
    version: "1.0.2",
    date: "2026-10-11",
    title: "Security update.",
    security: true,
    highlights: [
      "The MCP tool endpoint on port 8080 now requires the agent token or an API key with tools:call.",
      "API keys can no longer reach routes beyond their scopes on port 8080.",
      "Dependencies updated: no critical or high alerts remain on the public repository.",
      "The log generator starts reliably on a fresh database.",
      "The request right after a failed chat no longer gets an empty 400.",
      "Settings reject a value whose type differs from the setting's default.",
    ],
  },
  {
    version: "1.0.1",
    date: "2026-10-11",
    title: "Fresh installs generate logs on the first try.",
    highlights: [
      "New installs now start xlog over HTTPS; log generation no longer fails with an SSL error.",
      "A one-shot step creates the TLS certificate first and never replaces one you supplied.",
      "Creating a worker without a data-source schema works again.",
      "The Change password form now locks for a minute after five wrong current passwords.",
      "A bare tool name in a direct tool call no longer fails as ambiguous.",
    ],
  },
  {
    version: "1.0.0",
    date: "2026-10-11",
    title: "First public release of Phantom.",
    highlights: [
      "Chat with an AI agent that generates logs, runs scenarios, and checks your detections.",
      "Nearly 300 data sources shaped to match Cortex parsing and modeling rules.",
      "Scenario-based MITRE ATT&CK telemetry, plus Caldera operations for real endpoints.",
      "Nine built-in connectors, each running in its own container, with a marketplace.",
      "Send to syslog or CEF brokers, HTTP collectors, Splunk HEC, webhooks, or Cribl.",
      "Encrypted secrets, TLS everywhere, scoped API keys, observability, and backup and restore.",
      "The agent can never touch provider keys, connector secrets or API keys, even in a batch.",
    ],
  },
];

/** Convenience: fetch the entry for a specific version, if present. */
export function findRelease(version: string): ReleaseNote | undefined {
  return RELEASE_NOTES.find((r) => r.version === version);
}

/** Convenience: most-recent entry — used as a fallback when the
 *  running version doesn't appear in the static history (e.g. dev
 *  builds, or a release that ships before the notes get committed). */
export function latestRelease(): ReleaseNote {
  return RELEASE_NOTES[0];
}
