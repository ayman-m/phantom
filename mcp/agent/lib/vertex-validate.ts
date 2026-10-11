/**
 * Shared Vertex AI service-account JSON validation helpers.
 *
 * Shared by app/api/chat/route.ts and
 * `/api/agent/providers/vertex/test` (the operator-facing
 * Test Connection button) so both run the same checks.
 *
 * The test endpoint runs the SAME validation that
 * blocks chat dispatches at runtime — operators see the failure at
 * the form stage, not on first chat turn.
 */

/**
 * Parse a credentials input string. Returns the parsed object plus a
 * keyFile path if the input looks like a filesystem path (legacy
 * support for env-var deployments where GOOGLE_APPLICATION_CREDENTIALS
 * pointed at a file). Throws on JSON parse failure.
 *
 * The two recognized shapes:
 *   - Starts with `{` → JSON blob, parse it. Returns { credentials, keyFile: null }.
 *   - Anything else → treated as a filesystem path (legacy).
 *     Returns { credentials: null, keyFile: <path> }.
 *
 * The file-path branch is
 * dead code in practice — every credential resolution goes through
 * the ProviderStore which returns cleartext JSON, never a path.
 * The branch is preserved for the rare case of a hand-set
 * GOOGLE_APPLICATION_CREDENTIALS env var pointing at a file on disk.
 */
export function parseCredentialsInput(input: string): {
  credentials: Record<string, unknown> | null;
  keyFile: string | null;
} {
  const trimmed = input.trim();
  if (!trimmed) {
    return { credentials: null, keyFile: null };
  }

  if (trimmed.startsWith("{")) {
    let parsed: ReturnType<typeof JSON.parse>;
    try {
      parsed = JSON.parse(trimmed);
    } catch (error) {
      throw new Error(
        `GOOGLE_APPLICATION_CREDENTIALS JSON parse failed: ${String(error)}`,
      );
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      throw new Error("GOOGLE_APPLICATION_CREDENTIALS must be a JSON object");
    }
    return {
      credentials: parsed as Record<string, unknown>,
      keyFile: null,
    };
  }

  return { credentials: null, keyFile: trimmed };
}

/**
 * Validate a parsed credentials object against common placeholder
 * patterns. Returns null if the credentials look real, or a
 * human-readable error string if a placeholder is detected.
 *
 * Catches:
 *   - Missing required fields (type, project_id, private_key, client_email)
 *   - private_key without PEM markers
 *   - private_key body shorter than 200 chars (real keys are ~1600+)
 *   - Literal "fake" / "placeholder" tokens in the key body
 *   - Sample-domain client_email values (@y.com, @example.com, @test.com)
 *
 * The operator-facing message includes both the diagnostic and an
 * actionable next step (replace with a real key, or use GEMINI_API_KEY).
 */
export function detectPlaceholderCredential(
  credentials: Record<string, unknown> | null,
): string | null {
  if (!credentials) return null;

  // Required structural fields that any real GCP service-account JSON has.
  const required = ["type", "project_id", "private_key", "client_email"] as const;
  for (const field of required) {
    if (
      typeof credentials[field] !== "string" ||
      !(credentials[field] as string).trim()
    ) {
      return `GOOGLE_APPLICATION_CREDENTIALS missing required field: ${field}`;
    }
  }

  const privateKey = String(credentials.private_key);
  if (
    !privateKey.includes("BEGIN PRIVATE KEY") &&
    !privateKey.includes("BEGIN RSA PRIVATE KEY")
  ) {
    return "GOOGLE_APPLICATION_CREDENTIALS private_key is not in PEM format";
  }
  const body = privateKey
    .replace(/-----BEGIN [A-Z ]+ KEY-----/g, "")
    .replace(/-----END [A-Z ]+ KEY-----/g, "")
    .replace(/[\r\n\\]/g, "")
    .trim();
  if (body.length < 200 || /^fake$/i.test(body) || /^placeholder/i.test(body)) {
    return (
      "GOOGLE_APPLICATION_CREDENTIALS private_key looks like a placeholder " +
      `(${body.length} chars between BEGIN/END markers; real keys are ~1600+ chars). ` +
      "Set GEMINI_API_KEY for direct API access, or replace with a real GCP service-account JSON."
    );
  }
  const clientEmail = String(credentials.client_email);
  if (
    /^[^@]+@y\.com$/i.test(clientEmail) ||
    /@example\.com$/i.test(clientEmail) ||
    /@test\.com$/i.test(clientEmail)
  ) {
    return (
      `GOOGLE_APPLICATION_CREDENTIALS client_email looks like a placeholder (${clientEmail}). ` +
      "Replace with a real GCP service-account JSON or use GEMINI_API_KEY instead."
    );
  }
  return null;
}
