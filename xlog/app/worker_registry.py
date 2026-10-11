"""The live worker registry, and the admission gate in front of it.

Every worker-creating GraphQL resolver goes through `registry.admit(...)`.
Admission is the ONLY place a worker enters the registry, which is what makes
the ceilings meaningful: there is no second door.

WHY THIS EXISTS
---------------
A worker created with count=200, interval=1 put 987,441 events into a live
tenant in one hour. Three separate properties combined to allow it:

  * `count` means events per TICK on the OverrideSender path, and those
    workers never self-terminate, so the real figure is a sustained rate
    (200/sec, ~17M/day) rather than the "200 events" it reads like;
  * nothing validated count or interval anywhere — not the GraphQL schema,
    not the resolvers, not the senders;
  * `WORKERS_NUMBER` bounded the NUMBER of workers but never their aggregate
    rate, so 25 workers at 200/sec each passed the only check that existed.

WHAT THIS ENFORCES
------------------
The ceiling is on the INTEGRAL, not only the derivative. A sustained rate
above `XLOG_MAX_WORKER_EVENTS_PER_SEC` is refused; a BURST that declares its
own size is granted up to `XLOG_MAX_BURST_EVENTS_PER_SEC` but capped at
`XLOG_MAX_BURST_EVENTS` total. Generating security telemetry at volume is
Phantom's actual purpose, so "a few hundred events quickly" must keep working;
"a few hundred events per second, forever" must not.

THE PER-SENDER-CLASS TRAP
-------------------------
No single formula over the GraphQL arguments is correct, because the two
senders read the SAME argument names in opposite ways:

    legacy Sender    while status == "Running" and count > 0  -> count is a
                     TOTAL, one event per tick, rate = 1/interval, and it
                     DOES self-terminate.
    OverrideSender   while not stop_event.is_set()            -> count is per
                     TICK, rate = count/interval, and it runs until stopped.

Hence `events_per_second(sender)`, which asks the sender rather than guessing
from the request. Getting this wrong is a ~200x error in either direction.
"""

from __future__ import annotations

import datetime
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from app.config import Config

logger = logging.getLogger("xlog.worker_registry")


class WorkerAdmissionError(ValueError):
    """A worker was refused admission.

    Subclasses ValueError deliberately: xlog's resolvers already surface
    ValueError with a remediation clause, and the caller is very often an LLM
    agent that reads the message to correct itself. Every message here states
    the offending numbers, the ceiling, and what to do instead.
    """


# ─── config helpers ──────────────────────────────────────────────────────

def _int_env(raw: Any, default: int) -> int:
    """Read one ceiling. Unset/garbage falls back rather than crashing boot.

    A malformed ceiling must not take xlog down, but it must not silently
    become "unlimited" either — hence the fallback to the coded default and a
    warning, not to 0 (which means disabled).
    """
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning(
            "worker_registry: malformed ceiling %r; falling back to %s", raw, default
        )
        return default


def ceilings() -> Dict[str, int]:
    """Current ceilings. Read per call so tests can monkeypatch Config."""
    return {
        "worker_eps": _int_env(Config.XLOG_MAX_WORKER_EVENTS_PER_SEC, 10),
        "burst_eps": _int_env(Config.XLOG_MAX_BURST_EVENTS_PER_SEC, 500),
        "burst_events": _int_env(Config.XLOG_MAX_BURST_EVENTS, 50000),
        "concurrent_bursts": _int_env(Config.XLOG_MAX_CONCURRENT_BURSTS, 1),
        "total_eps": _int_env(Config.XLOG_MAX_TOTAL_EVENTS_PER_SEC, 50),
        "population": _int_env(Config.WORKERS_NUMBER, 25),
    }


# ─── rate arithmetic ─────────────────────────────────────────────────────

def rate_from(events_per_tick: int, interval: int) -> float:
    """events/sec, with non-positive intervals treated as UNBOUNDED.

    `interval <= 0` is not a small interval — it is no throttle at all. Both
    `Event.wait(0)` and `Event.wait(-1)` return immediately, so the tick loop
    spins as fast as the CPU allows. Returning `inf` makes every downstream
    comparison refuse it, and closes the hole where a NEGATIVE interval made
    `count / interval` negative and thus quietly passed a `> ceiling` check.
    """
    if interval <= 0:
        return float("inf")
    return events_per_tick / interval


def events_per_second(sender: Any) -> float:
    """Ask the sender for its own rate; never infer it from request args.

    Prefers an `events_per_second` property on the sender (each class knows
    its own loop semantics). Falls back to the conservative UNBOUNDED reading
    for an unknown class — a new sender must opt IN to being cheap, so
    forgetting the property fails closed rather than silently uncapped.
    """
    explicit = getattr(sender, "events_per_second", None)
    if isinstance(explicit, (int, float)):
        return float(explicit)

    count = getattr(sender, "count", None)
    interval = getattr(sender, "interval", None)
    try:
        count = int(count)
        interval = int(interval)
    except (TypeError, ValueError):
        logger.warning(
            "worker_registry: %s exposes no events_per_second and no usable "
            "count/interval; treating as unbounded",
            type(sender).__name__,
        )
        return float("inf")
    return rate_from(count, interval)


def _fmt(rate: float) -> str:
    return "unbounded" if rate == float("inf") else f"{rate:.2f}"


# ─── the registry ────────────────────────────────────────────────────────

class WorkerRegistry:
    """Owns the live-worker dict and the one admission path into it.

    Replaces the bare module-level `workers = {}` plus the three copy-pasted
    prune-then-cap blocks that preceded it. Those blocks had two defects this
    class exists to remove:

      * the population cap was checked ONCE before the scenario loops while
        workers were appended INSIDE them, so a single scenario call starting
        near the ceiling could push the registry to any size;
      * worker names were minted as `worker_<YYYYMMDDHHMMSS>` with no
        uniqueness suffix at three sites, two of them inside those loops. Two
        workers created in the same clock second collided, and the second
        insert silently OVERWROTE the first. The overwritten worker's thread
        was already running, so it became invisible to list_workers,
        unreachable by kill_worker, and uncounted against every cap — an
        orphaned stream recoverable only by restarting the container.
    """

    def __init__(self) -> None:
        # RLock, not Lock: admit() calls _prune() and _mint_name() while held.
        self._lock = threading.RLock()
        self._workers: Dict[str, Any] = {}
        self._bursts: Dict[str, bool] = {}
        self._seq = 0

    # ─── introspection ───────────────────────────────────────────────

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._workers

    def get(self, name: str) -> Optional[Any]:
        with self._lock:
            return self._workers.get(name)

    def names(self) -> List[str]:
        with self._lock:
            return list(self._workers.keys())

    def items(self) -> List[Tuple[str, Any]]:
        with self._lock:
            return list(self._workers.items())

    def snapshot(self) -> Dict[str, Any]:
        """Ceilings + current consumption. The basis of any UI/ops surface."""
        with self._lock:
            self._prune()
            live = [
                {
                    "worker": name,
                    "status": getattr(w, "status", "Unknown"),
                    "events_per_second": events_per_second(w),
                    "burst": self._bursts.get(name, False),
                }
                for name, w in self._workers.items()
            ]
            return {
                "workers": live,
                "sustained_events_per_second": self._sustained_total(),
                "concurrent_bursts": sum(1 for v in self._bursts.values() if v),
                "ceilings": ceilings(),
            }

    def snapshot_json(self) -> Dict[str, Any]:
        """`snapshot()` rendered safe for a JSON response.

        `snapshot()` can carry `float('inf')` — `rate_from` returns it for a
        non-positive interval, and `events_per_second` returns it for a sender
        class that declares no rate. Python's `json.dumps` writes that as the
        bare token `Infinity`, which is NOT in the JSON grammar: a browser's
        `JSON.parse` rejects the whole document. A UI reading this would die
        with a parse error rather than showing the one worker that matters —
        the unbounded one.

        So `inf` becomes `null`, meaning "unbounded / not measurable", and a
        parallel `*_unbounded` boolean makes that state explicit rather than
        leaving a consumer to guess whether null means unbounded or unknown.
        Numeric fields stay numeric-or-null so a typed client can model them.
        """
        def _num(v: float):
            return None if v == float("inf") else round(float(v), 4)

        snap = self.snapshot()
        workers = []
        for w in snap["workers"]:
            rate = w["events_per_second"]
            workers.append({
                **w,
                "events_per_second": _num(rate),
                "events_per_second_unbounded": rate == float("inf"),
            })
        total = snap["sustained_events_per_second"]
        return {
            **snap,
            "workers": workers,
            "sustained_events_per_second": _num(total),
            "sustained_events_per_second_unbounded": total == float("inf"),
        }

    # ─── internals (call with the lock held) ─────────────────────────

    def _prune(self) -> None:
        """Drop terminal workers so their rate is reclaimed."""
        live = {}
        for name, w in self._workers.items():
            if getattr(w, "status", None) == "Running":
                live[name] = w
            else:
                self._bursts.pop(name, None)
        self._workers = live

    def _sustained_total(self) -> float:
        """Aggregate rate of SUSTAINED workers only.

        Bursts are excluded and accounted against their own concurrency
        ceiling. Summing them here would make the two ceilings contradict
        each other — a single permitted 500/sec burst would instantly exceed
        any sane aggregate and lock out every subsequent worker.
        """
        return sum(
            events_per_second(w)
            for name, w in self._workers.items()
            if not self._bursts.get(name, False)
        )

    def _mint_name(self, when: Optional[datetime.datetime] = None) -> str:
        """A name that is unique even within the same clock second."""
        when = when or datetime.datetime.now()
        base = f"worker_{when.strftime('%Y%m%d%H%M%S')}"
        if base not in self._workers:
            return base
        while True:
            self._seq += 1
            candidate = f"{base}_{self._seq}"
            if candidate not in self._workers:
                return candidate

    # ─── admission ───────────────────────────────────────────────────

    def admit(
        self,
        senders: List[Any],
        *,
        bounded: Optional[List[bool]] = None,
    ) -> List[str]:
        """Validate and register senders together, all-or-nothing.

        `senders` is a LIST because scenario resolvers create many workers per
        call. Admitting them as a batch is what makes the population ceiling
        honest: checking once and then inserting in a loop would let a batch
        exceed the ceiling. Either every worker in the batch is admitted, or none
        is and nothing has been started.

        `bounded[i]` marks sender i as a DECLARED burst — it carries its own
        size limit (duration or event budget), so it is priced against the
        burst ceilings instead of the sustained ones.

        Returns the assigned names, positionally matching `senders`. The
        caller starts them; admission never starts a thread, so a rejection
        cannot leave one running.
        """
        bounded = bounded or [False] * len(senders)
        if len(bounded) != len(senders):
            raise ValueError("bounded must match senders in length")

        c = ceilings()
        with self._lock:
            self._prune()

            # 1. price each sender. A BOUNDED worker is judged on its TOTAL;
            #    an UNBOUNDED one on its RATE.
            #
            #    This split is the whole model. An unbounded worker's eventual
            #    volume is its rate times however long nobody notices, so rate
            #    is the only thing worth capping. A bounded worker cannot run
            #    away by definition — the legacy Sender delivers exactly
            #    `count` events and stops — so capping its rate would refuse
            #    harmless work (a 100-event seeding run) while doing nothing
            #    for safety. Judge it on the number that can actually hurt.
            classified: List[bool] = []
            for sender, declared_burst in zip(senders, bounded):
                rate = events_per_second(sender)
                total = getattr(sender, "max_total_events", None)

                # Boundedness must be a property of the SENDER, never a claim
                # by the caller. `declared_burst` says the REQUEST asked for a
                # burst; `total` says the constructed worker will actually
                # stop. Only the second one is load-bearing.
                #
                # Trusting the claim shipped a real bug: the resolver computed
                # "this is a burst" from the request but forgot to pass the
                # budget into the sender's constructor, so admission granted
                # 200 events/sec on a promise the worker had never received —
                # and it ran unbounded until killed by hand. Requiring the
                # sender's own bound makes that class of mistake impossible:
                # if the budget did not reach the worker, it is refused.
                if declared_burst and total is None:
                    raise WorkerAdmissionError(
                        f"worker rejected: a bounded run was requested, but the "
                        f"worker reports no event budget — the limit did not "
                        f"reach it, so it would run at {_fmt(rate)} events/sec "
                        f"indefinitely. This is a bug in the worker-creation "
                        f"path, not in your request; report it."
                    )

                is_bounded = total is not None

                if is_bounded:
                    if total is not None and c["burst_events"] > 0 and total > c["burst_events"]:
                        raise WorkerAdmissionError(
                            f"worker rejected: {total:,} events exceeds the "
                            f"{c['burst_events']:,}-event ceiling for a single "
                            f"bounded run. Split it into smaller runs, or raise "
                            f"XLOG_MAX_BURST_EVENTS."
                        )
                    if c["burst_eps"] > 0 and rate > c["burst_eps"]:
                        raise WorkerAdmissionError(
                            f"worker rejected: {_fmt(rate)} events/sec exceeds "
                            f"the burst ceiling of {c['burst_eps']}/sec. Raise "
                            f"interval to slow it down; the total is already "
                            f"bounded."
                        )
                    # Only a bounded run FASTER than the sustained ceiling
                    # consumes a burst grant. A slow finite worker is ordinary
                    # work and must not be serialized behind the burst limit.
                    classified.append(
                        c["worker_eps"] > 0 and rate > c["worker_eps"]
                    )
                    continue

                if c["worker_eps"] > 0 and rate > c["worker_eps"]:
                    raise WorkerAdmissionError(
                        f"worker rejected: {_fmt(rate)} events/sec exceeds the "
                        f"sustained ceiling of {c['worker_eps']}/sec, and this "
                        f"worker never stops on its own. Reduce count, raise "
                        f"interval, or declare a bounded burst by passing "
                        f"duration_seconds or max_events (bursts may run up to "
                        f"{c['burst_eps']}/sec, capped at "
                        f"{c['burst_events']:,} events)."
                    )
                classified.append(False)

            bounded = classified

            # 2. concurrent burst grants
            new_bursts = sum(1 for b in bounded if b)
            if new_bursts and c["concurrent_bursts"] > 0:
                live_bursts = sum(1 for v in self._bursts.values() if v)
                if live_bursts + new_bursts > c["concurrent_bursts"]:
                    raise WorkerAdmissionError(
                        f"burst rejected: {live_bursts} burst(s) already running, "
                        f"ceiling is {c['concurrent_bursts']}. Wait for the "
                        f"running burst to finish, or stop it with kill_worker."
                    )

            # 3. aggregate sustained rate
            if c["total_eps"] > 0:
                current = self._sustained_total()
                incoming = sum(
                    events_per_second(s)
                    for s, b in zip(senders, bounded)
                    if not b
                )
                if current + incoming > c["total_eps"]:
                    top = sorted(
                        (
                            (events_per_second(w), n)
                            for n, w in self._workers.items()
                            if not self._bursts.get(n, False)
                        ),
                        reverse=True,
                    )[:5]
                    listing = ", ".join(f"{n} at {_fmt(r)}/sec" for r, n in top)
                    raise WorkerAdmissionError(
                        f"worker rejected: would take total generation to "
                        f"{_fmt(current + incoming)} events/sec, over the "
                        f"aggregate ceiling of {c['total_eps']}/sec "
                        f"(currently {_fmt(current)}/sec). "
                        f"Stop a running worker first"
                        + (f" — largest: {listing}." if listing else ".")
                    )

            # 4. population — counted against the WHOLE batch, not per insert
            if c["population"] > 0:
                if len(self._workers) + len(senders) > c["population"]:
                    free = max(c["population"] - len(self._workers), 0)
                    raise WorkerAdmissionError(
                        f"rejected: {len(senders)} worker(s) requested but only "
                        f"{free} slot(s) free ({len(self._workers)} live, ceiling "
                        f"{c['population']} via WORKERS_NUMBER). Stop one with "
                        f"kill_worker, or raise WORKERS_NUMBER."
                    )

            # 5. insert — only now that nothing can fail
            names: List[str] = []
            for sender, is_burst in zip(senders, bounded):
                name = self._mint_name()
                if getattr(sender, "worker_name", None) is not None:
                    sender.worker_name = name
                self._workers[name] = sender
                self._bursts[name] = is_burst
                names.append(name)
            # Persist inside the lock, where `names` is in scope.
            #
            # A previous attempt put this block one indent level out, so it sat
            # OUTSIDE the `with self._lock:` that builds `names` — it never ran,
            # and produced no output to say so. That is the fourth silent no-op
            # in this fix; each looked like a correct deploy.
            #
            # admit() is the one place proven to run on every creation path: it
            # mints the worker names that appear in list_workers, so it is
            # reached regardless of which module object built the sender.
            for nm, snd in zip(names, senders):
                _persist_admitted(nm, snd)
            return names

    # ─── mutation ────────────────────────────────────────────────────

    def stop(self, name: str) -> Optional[str]:
        with self._lock:
            worker = self._workers.get(name)
        if worker is None:
            return None
        status = worker.stop()
        with self._lock:
            self._bursts.pop(name, None)
        return status if isinstance(status, str) else getattr(worker, "status", "Stopped")

    def pop(self, name: str, default: Any = None) -> Any:
        with self._lock:
            self._bursts.pop(name, None)
            return self._workers.pop(name, default)


registry = WorkerRegistry()


def _persist_admitted(name: str, sender: Any) -> None:
    """Record an admitted worker so a restart can rebuild it.

    Best-effort and loud: a store failure must not stop a healthy worker, but
    it is logged. A silent no-op here is precisely how losing every worker on
    restart stayed invisible.
    """
    try:
        fields = getattr(sender, "vendor_fields", None)
        dest = getattr(sender, "destination", "") or ""
        # Only the schema-override streaming path is restorable; see
        # schema.py:_rebuild_sender for why the others are not.
        if not fields or not dest.startswith(("udp:", "tcp:")):
            # Log the skip. An early return with no output is the same silent
            # no-op that made the previous three attempts undiagnosable —
            # "not restorable" and "never ran" looked identical.
            logger.info(
                "not persisting %s: restorable=False (sender=%s, dest=%r, "
                "has_fields=%s)",
                name, type(sender).__name__, dest[:40], bool(fields),
            )
            return
        from app import store

        # vendor_fields carries Strawberry SchemaOverrideField objects, not
        # plain dicts, and json.dumps refuses them:
        #   TypeError: Object of type SchemaOverrideField is not JSON serializable
        #
        # THIS was the real failure behind five attempts at this fix. Every
        # location tried — resolver, sender.start(), sender.__init__,
        # registry.admit — would have failed identically; the placement was
        # never the problem. The broad try/except swallowed it each time, and
        # local tests passed because they construct senders with plain dicts.
        # Reduced to the two keys _rebuild_sender actually needs.
        fields_json = [
            {"name": getattr(f, "name", None) or (f.get("name") if isinstance(f, dict) else None),
             "type": getattr(f, "type", None) or (f.get("type") if isinstance(f, dict) else None)}
            for f in fields
        ]
        fields_json = [f for f in fields_json if f.get("name")]
        if not fields_json:
            logger.info("not persisting %s: no usable schema_override fields", name)
            return

        store.save_worker_spec(name, {
            "worker_name": name,
            "type": getattr(sender, "data_type", "CEF"),
            "destination": dest,
            "count": getattr(sender, "count", 1),
            "interval": getattr(sender, "interval", 5),
            "vendor": getattr(sender, "vendor", None),
            "product": getattr(sender, "product", None),
            "verify_ssl": getattr(sender, "verify_ssl", False),
            "max_events": getattr(sender, "_max_events", None),
            "duration_seconds": getattr(sender, "_max_seconds", None),
            "schema_override": fields_json,
        })
        logger.info("persisted worker spec for %s", name)
    except Exception as exc:
        logger.warning(
            "could not persist worker spec for %s: %s: %s",
            name, type(exc).__name__, exc,
        )


# ─── the reaper ──────────────────────────────────────────────────────────
#
# A worker can stop making progress without ever exiting. The tick loop can
# block indefinitely inside a socket send against a dead TCP destination, or
# its thread can die on an exception the loop does not catch. Either way the
# registry keeps counting it: it holds a slot against the population ceiling
# and its declared rate against the aggregate, so admission refuses NEW
# workers on behalf of one that is doing nothing.
#
# In-loop budget checks cannot help — the loop is not running. Only something
# outside the worker can notice.
#
# TWO DETECTORS, deliberately asymmetric in confidence:
#
#   A. thread is dead, status still says Running.
#      Unambiguous. A thread that has exited cannot resume, so reaping is
#      pure reclamation with no judgement call. ON by default.
#
#   B. no progress for a long time.
#      Heuristic, and dangerous by default: a 0.2 ev/s baseline worker emits
#      once every five seconds BY DESIGN, and a bounded worker that finished
#      its budget legitimately stops counting. A naive "no recent events"
#      rule would reap healthy workers, which is worse than the leak it fixes.
#      OFF by default; when enabled the window is scaled to the worker's OWN
#      interval rather than a fixed number.


def _thread_is_dead(sender: Any) -> bool:
    """True when the worker's thread has exited but it still claims Running.

    The `ident is not None` guard matters: every sender sets status='Running'
    BEFORE calling thread.start(), so a worker inspected in that window has a
    thread object that was never started. `is_alive()` is False for it, and
    without this guard the reaper would kill workers a few microseconds old.
    """
    t = getattr(sender, "_thread", None)
    if t is None:
        return False
    if getattr(t, "ident", None) is None:
        return False  # never started yet — not dead, just not begun
    return not t.is_alive()


def _stalled_seconds(sender: Any) -> Optional[float]:
    """Seconds since this worker last recorded progress, or None if unknown."""
    last = getattr(sender, "_last_report_at", None)
    if not last:
        return None
    import time as _t

    return max(0.0, _t.monotonic() - float(last))


def reap_once(registry_obj: "WorkerRegistry") -> Dict[str, Any]:
    """One reaper pass. Returns what it did, so it can be surfaced and tested.

    Split from the loop deliberately: the decision logic is then testable
    without threads or sleeping, which is the part worth having tests for.
    """
    detector_b = _int_env(getattr(Config, "XLOG_REAPER_STALL_SECONDS", 0), 0)
    reaped: List[Dict[str, Any]] = []

    for name, sender in registry_obj.items():
        status = getattr(sender, "status", "")
        if status != "Running":
            continue  # already terminal; _prune reclaims it

        # Detector A — unambiguous.
        if _thread_is_dead(sender):
            reaped.append({"worker": name, "reason": "thread_dead"})
            continue

        # Detector B — opt-in, and scaled to the worker's own cadence.
        if detector_b > 0:
            stalled = _stalled_seconds(sender)
            if stalled is None:
                continue
            # A slow worker is not a stalled one. Require the stall to exceed
            # BOTH the configured floor and a generous multiple of this
            # worker's own interval, so a 0.2 ev/s baseline is never reaped
            # for behaving exactly as configured.
            interval = getattr(sender, "interval", 1) or 1
            threshold = max(detector_b, interval * 20)
            if stalled > threshold:
                reaped.append({
                    "worker": name,
                    "reason": "stalled",
                    "stalled_seconds": round(stalled, 1),
                    "threshold": threshold,
                })

    for row in reaped:
        nm = row["worker"]
        try:
            registry_obj.stop(nm)
            registry_obj.pop(nm)
            try:
                from app import store

                store.delete_worker_spec(nm)
            except Exception:
                pass
            logger.warning(
                "reaped worker %s (%s) — it held a slot and its rate against "
                "the ceilings while making no progress",
                nm, row["reason"],
            )
        except Exception as exc:
            logger.warning("could not reap %s: %s", nm, exc)

    return {"reaped": reaped, "count": len(reaped)}


def start_reaper(registry_obj: "WorkerRegistry") -> Optional[threading.Thread]:
    """Start the background reaper. Returns the thread, or None if disabled."""
    every = _int_env(getattr(Config, "XLOG_REAPER_INTERVAL_SECONDS", 60), 60)
    if every <= 0:
        logger.info("worker reaper disabled (XLOG_REAPER_INTERVAL_SECONDS=0)")
        return None

    def _loop() -> None:
        import time as _t

        while True:
            _t.sleep(every)
            try:
                reap_once(registry_obj)
            except Exception as exc:  # never let the reaper die silently
                logger.warning("reaper pass failed: %s", exc)

    t = threading.Thread(target=_loop, name="worker-reaper", daemon=True)
    t.start()
    logger.info("worker reaper started (every %ss)", every)
    return t
