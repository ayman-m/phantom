/**
 * POST /api/agent/providers/vertex/test
 *
 * Real Vertex AI connection test for the /providers page Test button.
 *
 * Design principle: the test should ANSWER OPERATORS' QUESTION
 * "does this credential work with GCP?" by ASKING GCP. We do not
 * pre-validate with heuristics like "private_key body is shorter
 * than 1600 chars" — that's our guess at what GCP would reject,
 * not what GCP actually says. Instead we:
 *
 *   1. Parse the JSON (structural error → operator gets the JSON
 *      syntax error from JSON.parse).
 *   2. Resolve the redaction sentinel "***" from the ProviderStore
 *      (so clicking Test without re-pasting validates the stored
 *      credentials).
 *   3. Hand whatever we have to google-auth-library and let it do
 *      the JWT → OAuth2 token exchange against Google's token
 *      endpoint.
 *   4. Surface the underlying Google error verbatim if the exchange
 *      fails. The operator gets the authoritative answer from GCP,
 *      not our static guess.
 *
 * Body (JSON):
 *   { service_account_json: string, project_id?: string, location?: string }
 *
 *   service_account_json may be the literal "***" redaction sentinel
 *   — meaning "the operator clicked Test without typing fresh JSON,
 *   so test the currently stored credentials." We resolve from the
 *   ProviderStore in that case, exactly like the chat handler does.
 *
 * Response:
 *   200 { status: "success", message: "..." }   — real auth worked
 *   200 { status: "error",   message: "..." }   — JSON parse failure
 *   200 { status: "error",   message: "..." }   — Google's verbatim error
 *
 * Always 200 at the HTTP layer so the page's status interpreter
 * doesn't fall through to its 404 → soft-success branch.
 */

import { NextResponse } from "next/server";
import { GoogleAuth } from "google-auth-library";

import { resolveVertexCredentialsFromStore } from "@/lib/vertex-credentials";
import { parseCredentialsInput } from "@/lib/vertex-validate";

export const dynamic = "force-dynamic";

const REDACTION_SENTINEL = "***";

interface TestBody {
  service_account_json?: string;
  project_id?: string;
  location?: string;
}

export async function POST(request: Request) {
  let body: TestBody;
  try {
    body = (await request.json()) as TestBody;
  } catch {
    return NextResponse.json(
      { status: "error", message: "Request body must be valid JSON." },
      { status: 200 },
    );
  }

  let saJson = (body.service_account_json || "").trim();

  // If the operator clicked Test without typing fresh JSON, the form
  // sent the redaction sentinel. Resolve from the ProviderStore so we
  // can test the currently stored credentials.
  if (saJson === REDACTION_SENTINEL || saJson === "") {
    const stored = await resolveVertexCredentialsFromStore();
    if (!stored) {
      return NextResponse.json(
        {
          status: "error",
          message:
            "No Vertex service-account JSON is configured yet. Paste a real " +
            "service-account JSON above and click Test.",
        },
        { status: 200 },
      );
    }
    saJson = stored;
  }

  // Parse only — structural JSON syntax errors get a clear message.
  // We do NOT run heuristic checks here (private_key length, sample
  // domain detection, etc.); the operator wants the live answer from
  // Google, so we hand whatever we parsed to google-auth-library and
  // let it tell us what's actually wrong.
  let credentials: Record<string, unknown> | null;
  try {
    const parsed = parseCredentialsInput(saJson);
    credentials = parsed.credentials;
  } catch (err) {
    return NextResponse.json(
      {
        status: "error",
        message: err instanceof Error ? err.message : String(err),
      },
      { status: 200 },
    );
  }
  if (!credentials) {
    return NextResponse.json(
      {
        status: "error",
        message:
          "Service-account JSON is empty after parse. Paste the full JSON " +
          "key from the GCP Console.",
      },
      { status: 200 },
    );
  }

  // The real test: JWT → OAuth2 token exchange via google-auth-library
  // against https://oauth2.googleapis.com/token. We surface the
  // underlying Google error verbatim (truncated) when it fails so the
  // operator sees the authoritative diagnostic — wrong project, disabled
  // SA, malformed PEM, missing field, all surface as Google's own message.
  try {
    // GoogleAuth's constructor type for `credentials` is a union over
    // multiple credential shapes. The cast here is structural — if the
    // shape is wrong, the JWT signing or token exchange below throws
    // with Google's own diagnostic, which is exactly what we want to
    // surface to the operator (the whole point of this endpoint is
    // letting Google answer, not us).
    const jwtInput = credentials as unknown as {
      type: string;
      project_id: string;
      private_key: string;
      client_email: string;
    };
    const auth = new GoogleAuth({
      credentials: jwtInput,
      scopes: ["https://www.googleapis.com/auth/cloud-platform"],
    });
    const client = await auth.getClient();
    const tokenResp = await client.getAccessToken();
    if (!tokenResp || !tokenResp.token) {
      return NextResponse.json(
        {
          status: "error",
          message:
            "OAuth2 exchange returned no access token. The service-account " +
            "JSON may be valid syntactically but is not authorised for " +
            "Vertex AI in this project.",
        },
        { status: 200 },
      );
    }
    const jsonProject =
      typeof credentials.project_id === "string"
        ? credentials.project_id
        : "(unknown)";
    return NextResponse.json(
      {
        status: "success",
        message:
          `Connected. JWT exchange succeeded for ${credentials.client_email} ` +
          `against project ${jsonProject}.`,
      },
      { status: 200 },
    );
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);

    // Special-case ONLY local PEM/DECODER failures. These mean Node's
    // OpenSSL couldn't even sign the JWT because the private_key in the
    // JSON isn't a parseable RSA key — the request never reached Google,
    // so there's no "Google verdict" to surface. We translate to a
    // human-readable diagnostic the operator can act on. Everything
    // else (Google's invalid_grant / unauthorized_client / network /
    // DNS errors) passes through verbatim because that's what the
    // operator wants to see — the authoritative answer from upstream.
    if (isLocalPemDecodeError(detail)) {
      return NextResponse.json(
        {
          status: "error",
          message:
            "Service-account JSON has an invalid private_key — the PEM " +
            "content can't be decoded as an RSA key. Re-paste the full " +
            "JSON from GCP Console → IAM & Admin → Service Accounts → " +
            "your SA → Keys → Add Key → Create new key (JSON).",
        },
        { status: 200 },
      );
    }

    // Trim absurdly long stack traces — operators only need the cause.
    const trimmed = detail.length > 400 ? `${detail.slice(0, 400)}…` : detail;
    return NextResponse.json(
      {
        status: "error",
        message: `OAuth2 exchange failed: ${trimmed}`,
      },
      { status: 200 },
    );
  }
}

/**
 * Detect Node-OpenSSL decoder errors that fire when the private_key
 * in the service-account JSON isn't a valid PEM. These are the LOCAL
 * failures that happen before the JWT signing step ever reaches
 * Google's token endpoint. Distinguishing them from Google's own
 * errors lets the route translate the cryptic OpenSSL hex code into
 * a re-paste-the-JSON action item, while letting Google's verbatim
 * messages pass through for everything else.
 *
 * The patterns match OpenSSL 3.x error format (`error:XXXXXXXX:...`)
 * for the namespaces that fire on PEM/RSA-key parse failure. Sample
 * matches:
 *
 *   error:1E08010C:DECODER routines::unsupported
 *   error:0480006C:PEM routines::no start line
 *   error:0608E09F:asn1 encoding routines:asn1_check_tlen:wrong tag
 */
function isLocalPemDecodeError(message: string): boolean {
  return (
    /error:[0-9A-Fa-f]{8}:DECODER routines/i.test(message) ||
    /error:[0-9A-Fa-f]{8}:PEM routines/i.test(message) ||
    /error:[0-9A-Fa-f]{8}:asn1 encoding routines/i.test(message)
  );
}
