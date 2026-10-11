from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel
from strawberry.asgi import GraphQL
import os

from app.schema import schema
from app.config import Config
from app.auth import XLogBearerAuthMiddleware
from app import store


if not os.path.exists(Config.LOGGING_DIR):
    os.makedirs(Config.LOGGING_DIR)


app = FastAPI()
app.add_route("/", GraphQL(schema=schema))
# Bearer-token auth on EVERY path except /health — including "/", which is
# the GraphQL surface mounted directly above. Whitelisting "/" would leave
# every worker-creating mutation reachable with no credential.
# When XLOG_API_KEY is unset the middleware refuses requests with 503 rather
# than running permissively. See app/auth.py.
app.add_middleware(XLogBearerAuthMiddleware, expected_token=Config.XLOG_API_KEY)


class SimulationRunCreate(BaseModel):
    name: str
    kind: str = "manual"
    status: str = "created"
    destination: Optional[str] = None
    tags: Optional[List[str]] = None
    attack: Optional[Dict[str, Any]] = None
    worker_ids: Optional[List[str]] = None
    caldera_operation_id: Optional[str] = None
    summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SimulationStatusUpdate(BaseModel):
    status: str
    metadata: Optional[Dict[str, Any]] = None


class ValidationResultCreate(BaseModel):
    status: str
    query: Optional[str] = None
    expected: Optional[Dict[str, Any]] = None
    observed: Optional[Dict[str, Any]] = None
    missed: Optional[List[str]] = None
    noisy_fields: Optional[List[str]] = None
    recommended_rules: Optional[List[str]] = None
    notes: Optional[str] = None


class ScenarioPackageCreate(BaseModel):
    name: str
    version: str = "1.0"
    status: str = "draft"
    tags: Optional[List[str]] = None
    attack: Optional[Dict[str, Any]] = None
    telemetry: Optional[Dict[str, Any]] = None
    validation: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


@app.on_event("startup")
def startup() -> None:
    store.init_db()
    # Rebuild any workers that were running when this process last stopped.
    # Without this an xlog restart ends all log generation SILENTLY — the
    # registry is in-memory, so list_workers returns empty and the platform
    # looks idle rather than broken. See app/schema.py:restore_workers_on_boot.
    try:
        from app.schema import restore_workers_on_boot

        app.state.worker_restore = restore_workers_on_boot()

        # Start the reaper. A worker can stop making progress without exiting
        # — blocked in a socket send to a dead destination, or its thread dead
        # on an uncaught exception — and the registry keeps counting it
        # against both the population and aggregate ceilings. In-loop checks
        # cannot help, because the loop is not running.
        from app.worker_registry import registry, start_reaper

        app.state.reaper = start_reaper(registry)
    except Exception as exc:  # never let recovery stop the service booting
        import logging

        logging.getLogger("xlog").warning("worker restore failed: %s", exc)
        app.state.worker_restore = {"error": str(exc)}


@app.get("/health")
def health() -> Dict[str, str]:
    store.init_db()
    return {"status": "ok", "database": str(store.DB_PATH)}


@app.get("/api/v1/worker-rates")
def worker_rates() -> Dict[str, Any]:
    """Live generation rates and the ceilings they are judged against.

    The registry already computes all of this for admission decisions; this
    exposes it so an operator can see current consumption instead of reading
    container logs. `snapshot_json` (not `snapshot`) because the raw form can
    carry float('inf'), which serializes as a bare `Infinity` token that
    JSON.parse rejects.

    `pid` is included deliberately. xlog runs multiple uvicorn workers when
    TLS is off (see the `workers=` argument below), and the registry is
    module-level state — so this snapshot describes THIS process only. Without
    the pid a reader would silently see a fraction of the picture and have no
    way to tell.
    """
    from app.worker_registry import registry

    return {**registry.snapshot_json(), "pid": os.getpid()}


@app.post("/api/v1/worker-rates/{worker}/stop")
def stop_worker_rate(worker: str) -> Dict[str, Any]:
    """Stop one worker and release its share of the ceilings.

    Mirrors the GraphQL action_worker path, and must do all THREE steps:

      stop()               signal the thread
      pop()                drop the registration, releasing its slot and rate
      delete_worker_spec() forget the persisted definition

    The third is what makes the stop stick. Without it the route would stop the
    worker and leave its row in worker_specs, so restore-on-boot would resurrect
    it at the next restart — the operator kills a runaway worker from the rate
    panel, watches the meters drop, and finds it consuming budget again after
    the next upgrade with no indication why. The user guide states plainly
    that an explicit stop is permanent.
    """
    from app.worker_registry import registry
    from app import store

    if registry.get(worker) is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    registry.stop(worker)
    registry.pop(worker)
    try:
        store.delete_worker_spec(worker)
    except Exception:
        # Advisory: the worker IS stopped either way. Worst case it returns
        # after a restart (a stale persisted spec), so log rather than swallow.
        import logging

        logging.getLogger("xlog").warning(
            "stopped %s but could not delete its persisted spec; it may "
            "return on restart", worker,
        )
    return {"worker": worker, "status": "Stopped"}


@app.get("/api/v1/simulations")
def list_simulations(limit: int = Query(default=50, ge=1, le=250)) -> Dict[str, Any]:
    return {"simulations": store.list_simulation_runs(limit=limit)}


@app.post("/api/v1/simulations")
def create_simulation(request: SimulationRunCreate) -> Dict[str, Any]:
    return store.create_simulation_run(**request.dict())


@app.get("/api/v1/simulations/{simulation_id}")
def get_simulation(simulation_id: str) -> Dict[str, Any]:
    simulation = store.get_simulation_run(simulation_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return simulation


@app.patch("/api/v1/simulations/{simulation_id}/status")
def update_simulation_status(simulation_id: str, request: SimulationStatusUpdate) -> Dict[str, Any]:
    simulation = store.update_simulation_status(
        simulation_id,
        request.status,
        metadata=request.metadata,
    )
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return simulation


@app.post("/api/v1/simulations/{simulation_id}/validations")
def create_validation(simulation_id: str, request: ValidationResultCreate) -> Dict[str, Any]:
    try:
        return store.create_validation_result(simulation_id=simulation_id, **request.dict())
    except KeyError:
        raise HTTPException(status_code=404, detail="Simulation not found")


@app.get("/api/v1/scenario-packages")
def list_scenario_packages(limit: int = Query(default=100, ge=1, le=250)) -> Dict[str, Any]:
    return {"scenario_packages": store.list_scenario_packages(limit=limit)}


@app.post("/api/v1/scenario-packages")
def create_scenario_package(request: ScenarioPackageCreate) -> Dict[str, Any]:
    return store.create_scenario_package(**request.dict())


@app.get("/api/v1/coverage-report")
def coverage_report() -> Dict[str, Any]:
    return store.coverage_report()


@app.get("/api/v1/simulations/{simulation_id}/export")
def export_simulation(simulation_id: str, format: str = Query(default="json")) -> Response:
    try:
        content = store.export_simulation(simulation_id, format)
    except KeyError:
        raise HTTPException(status_code=404, detail="Simulation not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    media_types = {
        "json": "application/json",
        "csv": "text/csv",
        "md": "text/markdown",
    }
    return Response(content=content, media_type=media_types.get(format, "text/plain"))


def _resolve_ssl_args() -> dict:
    """
    Returns kwargs for uvicorn.run that enable TLS.

    Resolution priority:
      1. /tls/cert.pem + /tls/key.pem (the shared phantom_tls volume,
         written by the agent — primary mechanism going forward)
      2. SSL_CERT_FILE/SSL_KEY_FILE env (explicit file paths)
      3. SSL_CERT_PEM/SSL_KEY_PEM env (inline PEM with \\n escapes;
         legacy path, kept for transitional dev compose runs)

    Returns an empty dict (plain HTTP) when no SSL config of any kind
    is reachable. Inline PEM is written to tempfiles + cleaned up
    via atexit; file-path forms are passed through as-is.
    """
    import atexit
    import tempfile
    import time

    # Priority 1: shared phantom_tls volume mounted at /tls.
    #
    # Boot-order race: xlog has no depends_on relationship with
    # phantom-agent, so nothing in compose requires phantom-agent's
    # entrypoint (the process that generates cert.pem/key.pem onto this
    # shared volume on first boot) to have run before xlog starts. xlog's
    # own healthcheck has a plain-HTTP fallback, so it reports healthy
    # either way. xlog can therefore win the race, find the volume empty,
    # fall through to plain HTTP, and stay that way for its entire process
    # lifetime, because this decision only runs once at startup. Every
    # https://xlog:8000 client (phantom-agent itself, every xlog connector
    # instance) would then fail with a confusing "[SSL] record layer
    # failure", which looks like a cert/config problem but is a pure
    # timing race that a plain `docker restart xlog` heals.
    #
    # So: poll briefly for the cert to land instead of deciding on a
    # single point-in-time check. Cert generation is a fast, one-shot
    # `openssl req` in phantom-agent's entrypoint, a few hundred ms in
    # practice, so a short bounded wait closes the race without
    # meaningfully slowing xlog's boot, and still falls through to the
    # existing plaintext-with-warning behavior for a genuine standalone
    # deployment that never gets a phantom-agent sibling at all.
    shared_cert = "/tls/cert.pem"
    shared_key = "/tls/key.pem"
    wait_timeout_s = 10.0
    wait_deadline = time.monotonic() + wait_timeout_s
    waited = False
    while not (os.path.isfile(shared_cert) and os.path.isfile(shared_key)):
        if time.monotonic() >= wait_deadline:
            break
        waited = True
        time.sleep(0.25)
    if os.path.isfile(shared_cert) and os.path.isfile(shared_key):
        if waited:
            print(f"[xlog] shared TLS volume populated after a short wait "
                  f"(cert={shared_cert}, key={shared_key})", flush=True)
        print(f"[xlog] TLS enabled from shared volume "
              f"(cert={shared_cert}, key={shared_key})", flush=True)
        return {"ssl_certfile": shared_cert, "ssl_keyfile": shared_key}
    if waited:
        print(f"[xlog] WARN: shared TLS volume still empty after "
              f"{wait_timeout_s:.0f}s wait (cert={shared_cert}, "
              f"key={shared_key}); falling through to env-var SSL config, "
              f"then plain HTTP", flush=True)

    # Priority 2/3: env-var fallbacks (legacy path, transitional).
    ssl_certfile = os.environ.get("SSL_CERT_FILE") or None
    ssl_keyfile  = os.environ.get("SSL_KEY_FILE")  or None
    cert_pem     = os.environ.get("SSL_CERT_PEM")  or None
    key_pem      = os.environ.get("SSL_KEY_PEM")   or None

    if not (ssl_certfile or cert_pem) or not (ssl_keyfile or key_pem):
        # Either both file/PEM forms must be configured, or neither.
        # If only one half is present we run plain HTTP and log it —
        # silently dropping a half-config would surprise operators.
        if any([ssl_certfile, ssl_keyfile, cert_pem, key_pem]):
            print("[xlog] WARN: partial SSL config (need both cert AND key); "
                  "running plain HTTP", flush=True)
        return {}

    def _normalize_pem(pem: str) -> str:
        # Same shape as bundles/spark/mcp/src/main.py:normalize_pem —
        # handle \\n-escape compose-env passthrough, normalize header
        # placement, collapse multiple blank lines.
        s = pem.replace("\\n", "\n").replace("\\r", "")
        for hdr in (
            "-----BEGIN CERTIFICATE-----",
            "-----END CERTIFICATE-----",
            "-----BEGIN PRIVATE KEY-----",
            "-----END PRIVATE KEY-----",
            "-----BEGIN RSA PRIVATE KEY-----",
            "-----END RSA PRIVATE KEY-----",
        ):
            if hdr.startswith("-----BEGIN"):
                s = s.replace(hdr, hdr + "\n")
            else:
                s = s.replace(hdr, "\n" + hdr)
        while "\n\n" in s:
            s = s.replace("\n\n", "\n")
        return s.strip() + "\n"

    temp_files = []

    if not ssl_certfile and cert_pem:
        cert_tmp = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".crt")
        cert_tmp.write(_normalize_pem(cert_pem))
        cert_tmp.close()
        ssl_certfile = cert_tmp.name
        temp_files.append(cert_tmp.name)

    if not ssl_keyfile and key_pem:
        key_tmp = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".key")
        key_tmp.write(_normalize_pem(key_pem))
        key_tmp.close()
        ssl_keyfile = key_tmp.name
        temp_files.append(key_tmp.name)

    def _cleanup():
        for f in temp_files:
            try:
                os.unlink(f)
            except FileNotFoundError:
                pass

    atexit.register(_cleanup)

    print(f"[xlog] TLS enabled (cert={ssl_certfile}, key={ssl_keyfile})",
          flush=True)
    return {"ssl_certfile": ssl_certfile, "ssl_keyfile": ssl_keyfile}


if __name__ == "__main__":
    import uvicorn

    # When TLS is on, drop workers=4 → workers=1. uvicorn's multi-worker
    # mode forks AFTER tempfiles are written, so each worker has access
    # to the same files; the issue is reload-style cleanup gets racy
    # across forked processes when atexit fires. workers=1 is the safe
    # path for TLS; we can revisit when xlog needs the throughput.
    ssl_kwargs = _resolve_ssl_args()
    workers = 1 if ssl_kwargs else 4
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        workers=workers,
        **ssl_kwargs,
    )
