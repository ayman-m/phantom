/**
 * Phantom admin auth constants compiled into the image.
 *
 * There is no DEFAULT_ADMIN_PASSWORD in this file. The
 * default password does not live in the image at all. It's sourced
 * at agent boot from the PHANTOM_DEFAULT_ADMIN_PASSWORD env var,
 * which the installer auto-generates per install and writes to
 * /opt/phantom/.env. See app/help/architecture#authentication for
 * the full canonical-state-discipline rationale ("no credentials in
 * any image, full stop"). The seed call still happens in
 * entrypoint.sh, which reads the password from the environment.
 *
 * # First-boot behavior
 *
 * On first container boot, the entrypoint asks the MCP auth_store
 * whether `auth.v1` is initialised. If not, the MCP writes the
 * PBKDF2 hash of $PHANTOM_DEFAULT_ADMIN_PASSWORD (sourced from .env)
 * to the SecretStore under `/ui/auth/admin/password_hash` and sets
 * `credentials_changed=false`.
 *
 * The operator logs in with admin / (the value in their installer
 * output banner, also visible in their .env), sees the "you must
 * change your password" banner, redirects to /profile, changes the
 * password. The change writes the new hash AND sets
 * `credentials_changed=true`. The banner never appears again unless
 * the operator runs phantom-factory-reset.
 *
 * # Discoverability
 *
 * The default credentials are documented in:
 *  - app/help/user/page.tsx#authentication ("First-Time Login" subsection)
 *  - The phantom-installer epilogue (prints the random per-install value)
 *  - docker logs phantom-agent on first boot (entrypoint prints the
 *    credentials banner ONCE when the seed fires; no print on later
 *    boots when SecretStore already holds operator-set credentials)
 *  - /opt/phantom/.env at PHANTOM_DEFAULT_ADMIN_PASSWORD
 *
 * # CLI parity
 *
 * The host-side reset CLI (installer/phantom-reset-admin-password.sh →
 * mcp/agent/cli/reset-admin.mjs) does NOT use these constants. The CLI
 * prompts the operator for a new password interactively. Defaults are
 * a first-boot-only mechanism.
 */

/** The single admin username. Phantom is single-user only. Multi-user
 *  is on the roadmap; until then this constant is the only username
 *  the system recognizes. Login attempts for other usernames return
 *  the same 401 as a wrong password (no info leak about which is
 *  wrong). Usernames are NOT credentials — keeping this baked is
 *  fine under the "no credentials in images" rule because the
 *  username doesn't grant any access on its own. */
export const ADMIN_USERNAME = "admin";

/** Cookie name for the server-side session token. The value is a
 *  32-byte random token whose hash is server-validated (not a flat
 *  boolean flag). */
export const SESSION_COOKIE_NAME = "phantom_session";

/** Absolute session lifetime in seconds. Cookies expire after this
 *  regardless of activity; idle-timeout is not separately enforced
 *  (single-operator dev tool — 2h is short enough that a forgotten
 *  laptop session expires quickly anyway). */
export const SESSION_TTL_SECONDS = 7200; // 2 hours
