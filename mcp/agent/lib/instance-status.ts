/**
 * How the /connectors page turns an instance's connection state into the
 * Connected / Error / Not Tested badge, the "tools available" note beside it,
 * and the outcome of a Test Connection press.
 *
 * `GET /api/v1/instances` returns the connection health of the instance's
 * connector under the key `state` (bundles/spark/mcp/src/api/instances.py,
 * `_instance_to_dict`, sourced from connector_state.db): one of
 * `connected | failed | needs-auth | pending | disabled`. There is no
 * `status` key on the row. The page used to read `status`, so every row came
 * back "Not Tested" after a reload even though the server still held the
 * result of the last probe.
 *
 * Tool advertisement does NOT depend on that state. The connector loader
 * registers a connector's tools whenever it is installed and has an enabled
 * instance (bundles/spark/mcp/src/usecase/connector_loader.py), so the state
 * only says how the last test or tool call went. The note therefore keys on
 * `enabled` alone for "available" and uses the state to say whether the
 * connection is known to be good, unknown or failing.
 *
 * Erasable-syntax TypeScript only, so scripts/test-instance-status.mjs can
 * import this file directly with Node's type stripping.
 */

export type InstanceStatus = "connected" | "error" | "not_tested";

/** Map a connector_state `state` string onto the badge the page shows. */
export function instanceStatusFromState(state: unknown): InstanceStatus {
  switch (state) {
    case "connected":
      return "connected";
    case "failed":
    case "needs-auth":
      return "error";
    default:
      // pending (never probed), disabled (a switch, not a health result),
      // or a value this build does not know.
      return "not_tested";
  }
}

export type ToolNoteTone = "ok" | "neutral" | "warn" | "paused";

export interface ToolNote {
  /** Whether the agent can call this instance's tools. True whenever the instance is enabled. */
  available: boolean;
  label: string;
  title: string;
  tone: ToolNoteTone;
}

/**
 * The note beside an instance row that says whether the agent can use its tools.
 *
 * - disabled instance: "Tools paused (disabled)"
 * - enabled, connected: available
 * - enabled, never tested (`pending`, or a state this build does not know):
 *   available, "not tested yet", neutral
 * - enabled, `failed`: available, "connection failing"
 * - enabled, `needs-auth`: available, "credentials rejected"
 */
export function toolNote(input: {
  enabled: boolean;
  state: unknown;
  lastError?: string | null;
}): ToolNote {
  if (!input.enabled) {
    return {
      available: false,
      label: "Tools paused (disabled)",
      title: "This instance is disabled. Re-enable it to let the agent use its tools.",
      tone: "paused",
    };
  }
  const reason = typeof input.lastError === "string" && input.lastError.trim() ? ` Last error: ${input.lastError.trim()}` : "";
  switch (input.state) {
    case "connected":
      return {
        available: true,
        label: "Tools available to agent",
        title: "The agent can call this connector's tools from chat.",
        tone: "ok",
      };
    case "failed":
      return {
        available: true,
        label: "Tools available · connection failing",
        title: `The agent can call this connector's tools, but the last test or tool call failed.${reason}`,
        tone: "warn",
      };
    case "needs-auth":
      return {
        available: true,
        label: "Tools available · credentials rejected",
        title: `The agent can call this connector's tools, but the last test or tool call was refused for its credentials.${reason}`,
        tone: "warn",
      };
    default:
      return {
        available: true,
        label: "Tools available · not tested yet",
        title: "The agent can call this connector's tools. Press Test Connection to check the connection.",
        tone: "neutral",
      };
  }
}

export interface TestResponse {
  probe_implemented?: boolean;
  ok?: boolean;
  error?: string | null;
  message?: string | null;
  dry_run?: boolean;
  connector_state?: { state?: string } | null;
}

export type TestOutcomeKind = "passed" | "failed" | "no_test";

export interface TestOutcome {
  kind: TestOutcomeKind;
  /** The badge the row should show afterwards. */
  status: InstanceStatus;
  /** One line for the operator. */
  message: string;
}

export const NO_BUILT_IN_TEST = "This connector has no built-in test.";

/** What a Test Connection press means, from the body of POST /api/v1/instances/{id}/test. */
export function testOutcome(data: TestResponse): TestOutcome {
  if (data.probe_implemented === false) {
    return {
      kind: "no_test",
      status: instanceStatusFromState(data.connector_state?.state),
      message: data.message?.trim() || NO_BUILT_IN_TEST,
    };
  }
  if (data.ok) {
    return { kind: "passed", status: "connected", message: data.message?.trim() || "Connection OK." };
  }
  return {
    kind: "failed",
    status: "error",
    message: `Test failed: ${data.error?.trim() || "unknown error"}`,
  };
}
