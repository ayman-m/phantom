"""A small SCIM 2.0 client (RFC 7643 / 7644) for a Cloud Identity Engine SCIM directory.

It makes the calls the Entra ID and Okta provisioning services make, because those are the clients the Cloud Identity
Engine's SCIM endpoint is built against: `GET /Users?filter=userName eq "..."`, `POST /Users`, `PATCH /Users/{id}` with
an `Operations` list of path-based `replace` operations, `DELETE /Users/{id}`, and the same for `/Groups`, with members
added and removed by `PATCH`. It does not rely on `/ServiceProviderConfig`, `/Schemas` or `/Bulk` existing.

The bearer token is held by the client and sent only as the Authorization header; no method returns it, and error
messages carry the HTTP status and the server's SCIM `detail`, never a header.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
ENTERPRISE_SCHEMA = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
GROUP_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Group"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
CONTENT_TYPE = "application/scim+json"
RETRY_STATUSES = (429, 502, 503, 504)


class ScimError(Exception):
    """A SCIM call that did not succeed: the HTTP status (0 when no response came back) and the server's detail."""

    def __init__(self, status: int, detail: str, *, method: str = "", path: str = "") -> None:
        self.status, self.detail, self.method, self.path = status, detail, method, path
        where = f"{method} {path} " if method else ""
        super().__init__(f"{where}-> {status or 'no response'}: {detail}")


def quote_filter_value(value: str) -> str:
    """A string literal for a SCIM filter (RFC 7644 3.4.2.2): double-quoted, with backslash and quote escaped."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return (response.text or response.reason_phrase or "").strip()[:300]
    if isinstance(body, dict):
        for key in ("detail", "message", "error_description", "error"):
            if body.get(key):
                return str(body[key])[:300]
    return str(body)[:300]


class ScimClient:
    def __init__(self, base_url: str, token: str, *, verify_tls: bool = True, timeout: float = 20.0,
                 transport: httpx.BaseTransport | None = None, max_attempts: int = 4,
                 sleep: Any = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._sleep = sleep or (lambda seconds: time.sleep(seconds))
        self._max_attempts = max(1, max_attempts)
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}", "Accept": CONTENT_TYPE, "Content-Type": CONTENT_TYPE},
            verify=verify_tls, timeout=timeout, transport=transport, follow_redirects=False,
        )
        self.calls = 0

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ScimClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # -- transport --------------------------------------------------------------------------------------------------

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                body: dict[str, Any] | None = None, ok: tuple[int, ...] = (200, 201, 204)) -> dict[str, Any] | None:
        """One SCIM call. Retries 429 and 502-504 (honouring Retry-After, capped at 30 s) and transport errors; any
        other status outside `ok` raises ScimError. Returns the JSON body, or None for an empty one (204)."""
        delay = 1.0
        for attempt in range(1, self._max_attempts + 1):
            self.calls += 1
            try:
                response = self._http.request(method, path, params=params, json=body)
            except httpx.HTTPError as exc:
                if attempt == self._max_attempts:
                    raise ScimError(0, f"{type(exc).__name__}: {exc}", method=method, path=path) from None
                self._sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            if response.status_code in RETRY_STATUSES and attempt < self._max_attempts:
                wait = delay
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    wait = float(retry_after)
                self._sleep(min(wait, 30.0))
                delay = min(delay * 2, 30.0)
                continue
            if response.status_code not in ok:
                raise ScimError(response.status_code, _detail(response), method=method, path=path)
            if not response.content:
                return None
            try:
                data = response.json()
            except ValueError:
                raise ScimError(response.status_code, "the response is not JSON", method=method, path=path) from None
            return data if isinstance(data, dict) else {"value": data}
        raise ScimError(0, "retries exhausted", method=method, path=path)  # pragma: no cover

    # -- queries ----------------------------------------------------------------------------------------------------

    def list(self, resource: str, *, filter: str | None = None, start_index: int = 1,
             count: int = 100) -> dict[str, Any]:
        """One page of a ListResponse: {total, start_index, resources}."""
        params: dict[str, Any] = {"startIndex": max(1, start_index), "count": max(1, min(count, 1000))}
        if filter:
            params["filter"] = filter
        data = self.request("GET", f"/{resource}", params=params) or {}
        resources = data.get("Resources") or data.get("resources") or []
        return {"total": int(data.get("totalResults", len(resources)) or 0),
                "start_index": int(data.get("startIndex", start_index) or start_index),
                "resources": [r for r in resources if isinstance(r, dict)]}

    def list_all(self, resource: str, *, filter: str | None = None, page_size: int = 100,
                 limit: int = 5000) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        start = 1
        while len(out) < limit:
            page = self.list(resource, filter=filter, start_index=start, count=page_size)
            batch = page["resources"]
            out.extend(batch)
            if not batch or len(out) >= page["total"]:
                break
            start += len(batch)
        return out[:limit]

    def find_one(self, resource: str, attribute: str, value: str) -> dict[str, Any] | None:
        # Only an exact (case-insensitive) match counts: a server that ignored the filter would otherwise hand back an
        # unrelated first resource, and the caller would update the wrong object.
        page = self.list(resource, filter=f"{attribute} eq {quote_filter_value(value)}", count=10)
        matches = [r for r in page["resources"] if str(r.get(attribute, "")).lower() == value.lower()]
        return matches[0] if matches else None

    def find_user(self, user_name: str) -> dict[str, Any] | None:
        return self.find_one("Users", "userName", user_name)

    def find_group(self, display_name: str) -> dict[str, Any] | None:
        return self.find_one("Groups", "displayName", display_name)

    # -- mutations --------------------------------------------------------------------------------------------------

    def create(self, resource: str, body: dict[str, Any]) -> dict[str, Any]:
        created = self.request("POST", f"/{resource}", body=body, ok=(200, 201))
        if not created or not created.get("id"):
            raise ScimError(201, "the server created the resource but returned no id", method="POST", path=f"/{resource}")
        return created

    def patch(self, resource: str, resource_id: str, operations: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not operations:
            return None
        return self.request("PATCH", f"/{resource}/{resource_id}",
                            body={"schemas": [PATCH_SCHEMA], "Operations": operations})

    def delete(self, resource: str, resource_id: str) -> None:
        self.request("DELETE", f"/{resource}/{resource_id}", ok=(200, 204, 404))

    def add_members(self, group_id: str, member_ids: list[str]) -> None:
        if member_ids:
            self.patch("Groups", group_id, [{"op": "add", "path": "members",
                                             "value": [{"value": m} for m in member_ids]}])

    def remove_member(self, group_id: str, member_id: str) -> None:
        self.patch("Groups", group_id, [{"op": "remove", "path": f"members[value eq {quote_filter_value(member_id)}]"}])
