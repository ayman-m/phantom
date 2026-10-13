/**
 * Edge check for connector-instance secrets typed into the operator UI or sent
 * by an API client.
 *
 * The MCP store reads a secret value starting with "/" as a SecretStore path
 * and later resolves it to plaintext, so a typed value of
 * "/ui/auth/admin/password_hash" would be handed to the connector as that
 * credential. The MCP store refuses every such value that is not the instance's
 * own path for the slot (400); this check refuses them one hop earlier, with
 * the same wording. The UI only ever sends "***" (redaction sentinel) or a
 * freshly typed value, never a stored path, so refusing every "/"-prefixed
 * value here loses nothing.
 */

export const PATH_SECRET_MESSAGE =
  'A secret value cannot start with "/" (it would be read as a path to another stored secret). Supply the secret value itself.';

/**
 * Returns an error message when a request body carries a secret that starts
 * with "/", otherwise null. A body that is not JSON, or has no `secrets`
 * object, is left for the MCP to judge.
 */
export function instanceSecretsError(rawBody: string): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(rawBody);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const secrets = (parsed as { secrets?: unknown }).secrets;
  if (!secrets || typeof secrets !== "object" || Array.isArray(secrets)) return null;
  for (const [slot, value] of Object.entries(secrets)) {
    if (typeof value === "string" && value.startsWith("/")) {
      return `${PATH_SECRET_MESSAGE} (slot "${slot}")`;
    }
  }
  return null;
}
