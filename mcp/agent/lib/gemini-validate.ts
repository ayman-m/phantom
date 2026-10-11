/**
 * Lightweight Gemini API key health check, called by /api/setup at
 * submit time. Failure here is a WARNING, not a BLOCKER — operators
 * legitimately want to set up Phantom without a working Gemini key
 * (offline lab use, Vertex-only deployments, "I'll fix the key later")
 * and we shouldn't gate first-run completion on a third-party API.
 *
 * The validation is intentionally minimal: it hits the public
 * `models.list` endpoint with the supplied key. 200 = key works;
 * anything else = warn-and-proceed.
 *
 * This is the place to add similar checks for other model providers
 * (OpenAI, Anthropic, Vertex, etc.) when their keys appear in the
 * setup payload. The route handler aggregates warnings into the
 * response so the UI can surface them all together.
 */

export interface ValidationResult {
  valid: boolean;
  // When valid=false, why. Operator-displayable; do NOT include the
  // submitted key, only the failure reason and HTTP status.
  error?: string;
}

const GEMINI_LIST_MODELS_URL =
  "https://generativelanguage.googleapis.com/v1beta/models";

const TIMEOUT_MS = 5000;

export async function validateGeminiApiKey(
  apiKey: string,
): Promise<ValidationResult> {
  const key = apiKey?.trim();
  if (!key) {
    // Empty key isn't a "validation failure" worth warning about —
    // the operator just didn't supply one. The Vertex path may be
    // their actual provider. Return valid:true to suppress the
    // warning; route handler will only validate when key is non-empty.
    return { valid: true };
  }

  try {
    const response = await fetch(`${GEMINI_LIST_MODELS_URL}?key=${encodeURIComponent(key)}`, {
      method: "GET",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });

    if (response.ok) {
      return { valid: true };
    }

    // Map common failure cases to operator-friendly messages.
    switch (response.status) {
      case 400:
      case 401:
      case 403:
        return {
          valid: false,
          error: `Gemini API rejected the key (HTTP ${response.status}). ` +
            "Verify the key at https://aistudio.google.com/apikey.",
        };
      case 429:
        return {
          valid: false,
          error: "Gemini API rate-limit hit during validation. " +
            "The key probably works; this is a transient warning.",
        };
      default:
        return {
          valid: false,
          error: `Gemini API returned HTTP ${response.status}.`,
        };
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "TimeoutError") {
      return {
        valid: false,
        error: `Gemini API didn't respond within ${TIMEOUT_MS}ms. ` +
          "Network policy may be blocking the call; the key may still work at runtime.",
      };
    }
    return {
      valid: false,
      error: err instanceof Error ? err.message : "Validation request failed",
    };
  }
}
