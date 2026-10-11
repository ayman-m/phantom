import type { ReadonlyRequestCookies } from "next/dist/server/web/spec-extension/adapters/request-cookies";

import { SESSION_COOKIE_NAME } from "@/lib/auth-defaults";

export function getToken(
  cookies: ReadonlyRequestCookies | { get(name: string): { value: string } | undefined },
): string | undefined {
  return cookies.get(SESSION_COOKIE_NAME)?.value;
}

export function getAuthHeaders(
  cookies: ReadonlyRequestCookies | { get(name: string): { value: string } | undefined },
): { Authorization: string } | Record<string, never> {
  const token = getToken(cookies);
  if (!token) {
    return {};
  }
  return { Authorization: `Bearer ${token}` };
}
