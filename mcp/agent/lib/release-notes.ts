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
    version: "1.1.0",
    date: "Unreleased", // set to the ISO publish date when v1.1.0 is tagged
    title: "Organization: one company behind every generated log.",
    highlights: [
      "Every log now uses one fictitious company, so Cortex can group alerts from Okta, Windows, firewalls and cloud into one case.",
      "Phantom Lab ships built in: 50 people, their workstations, servers, VLANs and cloud accounts; edit it, import your own, or switch.",
      "The agent reads the organization before it generates and can add people, hosts and networks from chat.",
      "Connectors read the active organization live; a save or a switch needs no restart.",
      "The Cortex setup panel lists the internal ranges and domain suffix to enter in Network Configuration.",
      "cie-sender, wec-sender and http-sender settings for domains and host counts are gone: edit the organization instead.",
      "Architecture → Analytics Trigger Coverage lists every alert-triggering skill, what it takes to fire it, and what still doesn't.",
    ],
  },
  {
    version: "1.0.6",
    date: "2026-10-15",
    title: "Connector setup: Test Connection for every connector and the HTTP Sender destination switch.",
    highlights: [
      "Test Connection works for all nine connectors and says what it checked and what it did not.",
      "The Edit dialog shows every field, and saving restarts the connector so new settings take effect.",
      "HTTP Sender asks for a destination first: XSIAM HTTP collector, Cribl integration or both.",
      "Connector forms list the settings each connector reads; lists and numbers save as real values.",
      "A disabled instance now pauses its tools; enable any instance you still rely on.",
    ],
  },
  {
    version: "1.0.5",
    date: "2026-10-15", // shipped in v1.0.6
    title: "Model providers: Claude and OpenAI beside Vertex, with a live model registry and one default model.",
    breaking: true,
    highlights: [
      "Run Phantom on Claude or OpenAI with an API key; Vertex is now optional.",
      "A live model registry merges each provider's own model list with prices and availability badges.",
      "One default model, set with Set as default on Models; GEMINI_MODEL and the ANTHROPIC_API_KEY variable are gone.",
      "A model that cannot run fails the turn with MODEL_UNAVAILABLE instead of being swapped silently.",
      "Cost is tracked per provider and model; calls with no known price show as unpriced, never $0.",
      "An old geminiModel setting moves to the default model only if the catalog serves it; otherwise it is dropped and audited.",
    ],
  },
  {
    version: "1.0.4",
    date: "2026-10-15", // shipped in v1.0.6
    title: "Hook, benchmark and status fixes, and documentation coverage.",
    highlights: [
      "Claude Code CLI integration removed; the Anthropic card keeps only the API key field.",
      "Backups now include your hooks; secret values are left out and the hook restores disabled.",
      "Personality page drops eleven settings nothing used; it keeps the persona editor and action policy.",
      "Caldera now shows its real status on Services instead of always reading unknown.",
      "Benchmark runs now work: every case used to fail with a 401 from the chat endpoint.",
      "Built-in hooks can only be saved on events they support.",
      "Cost and context warnings from the built-in hooks now appear on Notifications.",
      "New user-guide sections for Benchmark Runs, Runtime Events and What's New; the Knowledge Bases guide covers browsing.",
      "The architecture page gains Benchmark Harness and About & Release Notes sections; a new observability overview journey.",
    ],
  },
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
