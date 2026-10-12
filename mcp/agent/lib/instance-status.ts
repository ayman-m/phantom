/**
 * How the /connectors page turns an instance's connection state into the
 * Connected / Error / Not Tested badge.
 *
 * `GET /api/v1/instances` returns the connection health of the instance's
 * connector under the key `state` (bundles/spark/mcp/src/api/instances.py,
 * `_instance_to_dict`, sourced from connector_state.db): one of
 * `connected | failed | needs-auth | pending | disabled`. There is no
 * `status` key on the row. The page used to read `status`, so every row came
 * back "Not Tested" after a reload even though the server still held the
 * result of the last probe.
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
