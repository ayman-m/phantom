/**
 * Outbound-URL guard for provider traffic.
 *
 * A provider card can carry an operator-set base URL, and the API key travels
 * to whatever host it names. So every call that leaves for a provider goes
 * through this module:
 *
 *   - `assertSafeBaseUrl` accepts `https:` URLs only, refuses embedded
 *     credentials, query strings and fragments, refuses loopback and
 *     link-local addresses (including the IPv6 and IPv4-mapped forms and the
 *     numeric host spellings the URL parser normalizes), refuses the compose
 *     service names and any single-label host, and re-checks the resolved
 *     addresses at call time so a name that later points inward is caught.
 *   - `guardedFetch` sends with `redirect: 'manual'` and a deadline, and treats
 *     any 3xx as a failure, so a redirect can never carry the key elsewhere.
 *
 * Private ranges (10/8, 172.16/12, 192.168/16) stay allowed: corporate LLM
 * gateways live there. Limit: the address check and the connection are two
 * lookups, so a resolver that answers differently the second time is not
 * defeated; the https and no-redirect rules still hold.
 *
 * Erasable TypeScript only; no `@/` imports, no environment reads.
 */

import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';
import { ProviderError } from './errors.ts';

/** Hosts that name this install's own services. */
export const COMPOSE_SERVICE_HOSTS: readonly string[] = [
  'localhost',
  'phantom-agent',
  'phantom-tls-init',
  'phantom-updater',
  'phantom-browser',
  'xlog',
  'caldera',
];

const BLOCKED_SUFFIXES: readonly string[] = ['.localhost', '.local', '.internal'];

export type HostResolver = (host: string) => Promise<string[]>;

export interface UrlGuardDeps {
  /** Extra hosts to refuse, e.g. the MCP host taken from MCP_URL. */
  blockedHosts?: readonly string[];
  /** Defaults to the system resolver (all addresses). */
  resolveHost?: HostResolver;
}

function reject(message: string): never {
  throw new ProviderError({ kind: 'invalid_request', code: 'BASE_URL_REJECTED', message });
}

/** Expand an IPv6 literal into eight 16-bit groups, or null when malformed. */
function expandIpv6(input: string): number[] | null {
  let text = input;
  const zone = text.indexOf('%');
  if (zone >= 0) text = text.slice(0, zone);
  let tail: number[] = [];
  const dotted = text.lastIndexOf('.');
  if (dotted >= 0) {
    const colon = text.lastIndexOf(':');
    const parts = text.slice(colon + 1).split('.').map(Number);
    if (parts.length !== 4 || parts.some((p) => !Number.isInteger(p) || p < 0 || p > 255)) return null;
    tail = [(parts[0] << 8) | parts[1], (parts[2] << 8) | parts[3]];
    text = text.slice(0, colon + 1) + '0:0';
  }
  const halves = text.split('::');
  if (halves.length > 2) return null;
  const toGroups = (s: string) => (s === '' ? [] : s.split(':'));
  const head = toGroups(halves[0]);
  const rest = halves.length === 2 ? toGroups(halves[1]) : [];
  const missing = 8 - head.length - rest.length;
  if (halves.length === 1 ? head.length !== 8 : missing < 1) return null;
  const all = [...head, ...(halves.length === 2 ? Array(missing).fill('0') : []), ...rest];
  const groups = all.map((g) => (/^[0-9a-f]{1,4}$/i.test(g) ? parseInt(g, 16) : NaN));
  if (groups.some((g) => Number.isNaN(g))) return null;
  if (tail.length) {
    groups[6] = tail[0];
    groups[7] = tail[1];
  }
  return groups;
}

/** Why an address must not be called, or null when it may be. */
export function blockedAddressReason(address: string): string | null {
  const kind = isIP(address);
  if (kind === 4) {
    const [a, b] = address.split('.').map(Number);
    if (a === 127) return 'a loopback address';
    if (a === 0) return 'an unspecified address';
    if (a === 169 && b === 254) return 'a link-local address';
    return null;
  }
  if (kind === 6) {
    const g = expandIpv6(address);
    if (!g) return 'a malformed address';
    if (g.slice(0, 7).every((x) => x === 0) && g[7] === 1) return 'a loopback address';
    if (g.every((x) => x === 0)) return 'an unspecified address';
    if ((g[0] & 0xffc0) === 0xfe80) return 'a link-local address';
    // The EC2 metadata endpoint's IPv6 form.
    if (g[0] === 0xfd00 && g[1] === 0x0ec2 && g.slice(2, 7).every((x) => x === 0) && g[7] === 0x254) {
      return 'a link-local address';
    }
    // IPv4-mapped (::ffff:a.b.c.d) and IPv4-compatible (::a.b.c.d): judge the embedded IPv4.
    if (g.slice(0, 5).every((x) => x === 0) && (g[5] === 0xffff || g[5] === 0)) {
      const v4 = `${g[6] >> 8}.${g[6] & 255}.${g[7] >> 8}.${g[7] & 255}`;
      return blockedAddressReason(v4);
    }
    return null;
  }
  return 'not an IP address';
}

async function defaultResolve(host: string): Promise<string[]> {
  const found = await lookup(host, { all: true });
  return found.map((f) => f.address);
}

function normalizeHost(hostname: string): string {
  let h = hostname.toLowerCase();
  if (h.startsWith('[') && h.endsWith(']')) h = h.slice(1, -1);
  while (h.endsWith('.')) h = h.slice(0, -1);
  return h;
}

/**
 * Syntax and name checks only (no DNS). Returns the parsed URL; throws a
 * `BASE_URL_REJECTED` ProviderError with an operator-readable reason.
 */
export function checkBaseUrl(raw: string, deps: UrlGuardDeps = {}): URL {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return reject('The base URL is not a valid URL.');
  }
  if (url.protocol !== 'https:') return reject('The base URL must use https.');
  if (url.username || url.password) return reject('The base URL must not contain credentials.');
  if (url.search || url.hash) return reject('The base URL must not contain a query string or fragment.');
  const host = normalizeHost(url.hostname);
  if (!host) return reject('The base URL has no host.');

  if (isIP(host)) {
    const why = blockedAddressReason(host);
    if (why) return reject(`The base URL points at ${why}.`);
    return url;
  }
  if (!host.includes('.')) return reject('The base URL must name a fully qualified host.');
  const blocked = [...COMPOSE_SERVICE_HOSTS, ...(deps.blockedHosts ?? [])].map(normalizeHost);
  if (blocked.includes(host)) return reject('The base URL points at a service inside this install.');
  if (BLOCKED_SUFFIXES.some((s) => host.endsWith(s))) {
    return reject('The base URL points at an internal host name.');
  }
  return url;
}

/**
 * Full check: syntax, names, then every address the host resolves to.
 * Returns the base URL without a trailing slash.
 */
export async function assertSafeBaseUrl(raw: string, deps: UrlGuardDeps = {}): Promise<string> {
  const url = checkBaseUrl(raw, deps);
  const host = normalizeHost(url.hostname);
  if (!isIP(host)) {
    let addresses: string[];
    try {
      addresses = await (deps.resolveHost ?? defaultResolve)(host);
    } catch {
      throw new ProviderError({
        kind: 'network',
        message: 'The provider host name could not be resolved.',
        retryable: true,
      });
    }
    if (addresses.length === 0) {
      throw new ProviderError({ kind: 'network', message: 'The provider host name did not resolve.', retryable: true });
    }
    for (const address of addresses) {
      const why = blockedAddressReason(address);
      if (why) return reject(`The base URL resolves to ${why}.`);
    }
  }
  return url.origin + url.pathname.replace(/\/+$/, '');
}

export interface GuardedFetchDeps {
  fetch?: typeof fetch;
  /** Per-request deadline; default 8 s. */
  timeoutMs?: number;
  signal?: AbortSignal;
}

/**
 * `fetch` that never follows a redirect and always has a deadline. A 3xx
 * becomes a ProviderError, because following it would hand the credential to
 * a host nobody vetted.
 */
export async function guardedFetch(
  url: string,
  init: RequestInit,
  deps: GuardedFetchDeps = {},
): Promise<Response> {
  const signals = [AbortSignal.timeout(deps.timeoutMs ?? 8000)];
  if (deps.signal) signals.push(deps.signal);
  const impl = deps.fetch ?? ((input: string, i?: RequestInit) => fetch(input, i));
  let response: Response;
  try {
    response = await impl(url, { ...init, redirect: 'manual', signal: AbortSignal.any(signals) });
  } catch (err) {
    const timedOut = err instanceof Error && (err.name === 'TimeoutError' || err.name === 'AbortError');
    throw new ProviderError({
      kind: 'network',
      message: timedOut ? 'The provider did not answer in time.' : 'The provider could not be reached.',
      retryable: true,
      cause: err,
    });
  }
  if (response.status >= 300 && response.status < 400) {
    throw new ProviderError({
      kind: 'invalid_request',
      code: 'BASE_URL_REDIRECT',
      message: `The provider answered with a redirect (${response.status}); redirects are not followed.`,
      status: response.status,
    });
  }
  return response;
}
