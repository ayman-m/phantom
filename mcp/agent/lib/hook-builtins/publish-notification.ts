/**
 * Publish an operator notification from a built-in hook.
 *
 * Non-decisional by design: a failed publish must never break the chat loop,
 * so this never throws. It is not silent either. The failure (the MCP's HTTP
 * status and error body, for example a 400 for an undeclared topic) is
 * logged with console.error under the hook's name, and the caller learns the
 * outcome from the return value so it can skip its "already warned" marker.
 */

import { callMcpServer } from "@/lib/mcp-proxy";

export async function publishHookNotification(
  hookName: string,
  topic: string,
  payload: Record<string, unknown>,
): Promise<boolean> {
  try {
    await callMcpServer("/api/v1/notifications", {
      method: "POST",
      body: { topic, payload },
    });
    return true;
  } catch (err) {
    // callMcpServer's message carries the method, path, status and body:
    // "MCP POST /api/v1/notifications -> 400 {...}".
    console.error(
      `${hookName}: failed to publish a "${topic}" notification:`,
      err instanceof Error ? err.message : err,
    );
    return false;
  }
}
