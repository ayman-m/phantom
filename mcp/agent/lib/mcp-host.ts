/**
 * The MCP host as a list a provider base URL may not point at, so an
 * operator-typed gateway URL cannot aim the agent at its own backend. Read at
 * call time from `MCP_URL`; one home for what the provider routes, the model
 * registry and the chat route's model calls all pass as `blockedHosts`.
 *
 * Erasable TypeScript only (a node test loads this file directly).
 */
export function mcpBlockedHosts(): string[] {
  try {
    return [new URL(process.env.MCP_URL || 'http://localhost:8080').hostname];
  } catch {
    return [];
  }
}
