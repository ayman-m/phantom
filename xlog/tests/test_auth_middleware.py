"""xlog's GraphQL surface must require authentication.

Two defects concealed each other here, and either fix alone would have broken
log generation:

  * auth.py whitelisted "/" — the path the GraphQL schema is mounted at — so
    every worker-creating mutation was reachable with no credential by anything
    that could reach the container. The stated justification was preserving
    schema introspection for tooling.
  * The xlog connector, the only real caller, read its token from a config key
    that is never populated in a container deployment, so it sent no
    Authorization header at all.

The whitelist was therefore the only reason generation worked. Removing it
without fixing the connector 401s all 13 GraphQL call sites.

These tests pin both halves: "/" is gated, /health is not, and an unset key
refuses service rather than serving it unauthenticated.
"""

import unittest

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.auth import SKIP_AUTH_PATHS, XLogBearerAuthMiddleware

TOKEN = "s3cret-token-value"


def _app(token):
    """A stand-in mounting a route at "/" exactly as xlog/main.py does."""
    async def ok(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[
        Route("/", ok, methods=["GET", "POST"]),
        Route("/health", ok, methods=["GET"]),
        Route("/api/v1/thing", ok, methods=["GET"]),
    ])
    app.add_middleware(XLogBearerAuthMiddleware, expected_token=token)
    return TestClient(app)


class TestGraphQLSurfaceIsGated(unittest.TestCase):
    def test_root_is_not_whitelisted(self):
        """"/" IS the GraphQL surface. It must never bypass auth."""
        self.assertNotIn("/", SKIP_AUTH_PATHS)

    def test_health_is_still_whitelisted(self):
        """The docker healthcheck probes this without a token."""
        self.assertIn("/health", SKIP_AUTH_PATHS)
        self.assertEqual(_app(TOKEN).get("/health").status_code, 200)

    def test_graphql_without_a_token_is_refused(self):
        r = _app(TOKEN).post("/", json={"query": "{ listWorkers { worker } }"})
        self.assertEqual(r.status_code, 401)

    def test_graphql_with_a_bad_token_is_refused(self):
        r = _app(TOKEN).post("/", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(r.status_code, 401)

    def test_graphql_with_the_bearer_form_is_allowed(self):
        r = _app(TOKEN).post("/", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(r.status_code, 200)

    def test_graphql_with_the_bare_form_is_allowed(self):
        """The connector sends the bare value, not "Bearer <tok>"."""
        r = _app(TOKEN).post("/", headers={"Authorization": TOKEN})
        self.assertEqual(r.status_code, 200)

    def test_rest_paths_were_already_gated_and_still_are(self):
        c = _app(TOKEN)
        self.assertEqual(c.get("/api/v1/thing").status_code, 401)
        self.assertEqual(
            c.get("/api/v1/thing", headers={"Authorization": TOKEN}).status_code, 200
        )


class TestUnsetKeyFailsClosed(unittest.TestCase):
    """An unset key must refuse service, not serve everything.

    The previous behaviour fell through permissively "for upgrade
    compatibility", which meant a misconfigured deploy served every
    worker-creating mutation to anyone on the network, silently.
    """

    def test_unset_key_refuses_graphql(self):
        r = _app("").post("/", json={"query": "{ listWorkers { worker } }"})
        self.assertEqual(r.status_code, 503)

    def test_unset_key_refuses_even_with_a_token_presented(self):
        """No credential can satisfy a server that has none configured."""
        r = _app("").post("/", headers={"Authorization": "anything"})
        self.assertEqual(r.status_code, 503)

    def test_503_not_401_because_the_server_is_at_fault(self):
        """401 would send an operator hunting for a bad token."""
        r = _app("").get("/api/v1/thing")
        self.assertEqual(r.status_code, 503)
        self.assertIn("XLOG_API_KEY", r.json()["detail"])

    def test_error_names_the_file_to_fix(self):
        r = _app("").get("/api/v1/thing")
        self.assertIn(".env", r.json()["detail"])

    def test_health_still_answers_with_no_key(self):
        """The container must stay healthy and diagnosable, not crash-loop.

        An operator should see a running service refusing work, rather than a
        restart loop with the cause buried in logs.
        """
        self.assertEqual(_app("").get("/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
