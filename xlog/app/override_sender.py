"""Vendor-faithful UDP/TCP worker sender.

The legacy `Sender` generates records on-the-fly
inside its tick loop using Rosetta's generic observables (`local_ip`,
`remote_port`, etc.). It doesn't accept a pre-built record stream for
UDP/TCP destinations, only for the XSIAM_WEBHOOK path.

`OverrideSender` is the schema-override-aware counterpart: it uses
`generate_records_with_override()` from `dynamic_schema.py` to produce
records whose top-level keys match the vendor's actual field names
(extracted from a Cortex ModelingRule via the agent's marketplace), then
streams them to a UDP or TCP destination on a tick.

Interface matches Sender's externally-accessed surface — see
`app/schema.py:list_workers` / `action_worker` for the contract.

This sender is INTENTIONALLY narrow: only UDP + TCP destinations, only
the override case. XSIAM and webhook destinations still flow through
the existing Sender / WebhookSender paths.

Wire format is chosen by `data_type`. JSON-encoding every payload would
break the broker → XSIAM ingestion path: XSIAM brokers route to
`<vendor>_<product>_raw` datasets BY PARSING THE CEF HEADER on incoming
syslog, and JSON over UDP has no header → broker drops it (or routes to
a fallback). So:
  CEF    → `<134>TIMESTAMP HOSTNAME CEF:0|Vendor|Product|Version|SigID|Name|Severity|ext`
  SYSLOG → `<134>TIMESTAMP HOSTNAME vendor product: key=value key=value …`
  LEEF   → `<134>TIMESTAMP HOSTNAME LEEF:2.0|Vendor|Product|Version|EventID|ext`
  *      → JSON (default for any other data_type)
"""

from __future__ import annotations

import datetime
import json
import logging
import socket
import socket as _socket_mod
import threading
import time
from typing import Any, List, Optional

from app.config import Config
from app.dynamic_schema import generate_records_with_override

logger = logging.getLogger("xlog.override_sender")

# Syslog priority for facility=user (1), severity=informational (6) → 1*8+6=14.
# Most CEF-over-syslog deployments use facility=local0 (16) severity=info (6)
# → 16*8+6 = 134. XSIAM brokers don't care about the priority value — they
# parse the CEF/LEEF header out of the message body — but a syntactically
# valid syslog wrapper avoids broker-side warning logs.
_SYSLOG_PRIORITY = 134


def _syslog_timestamp() -> str:
    """RFC 3164 timestamp: 'Mon DD HH:MM:SS' in local server time.

    Using UTC is also accepted by all syslog parsers we test against
    (XSIAM broker, rsyslogd, syslog-ng) — keep it consistent.
    """
    now = datetime.datetime.utcnow()
    # `strftime('%b %e %H:%M:%S')` would give the right form but `%e`
    # isn't portable on all libc. Build by hand for determinism.
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{months[now.month - 1]} {now.day:2d} {now.strftime('%H:%M:%S')}"


def _hostname() -> str:
    """Best-effort short hostname for the syslog wrapper.

    Falls back to 'xlog' if gethostname returns something unusable.
    """
    try:
        h = _socket_mod.gethostname() or "xlog"
        # Strip any FQDN suffix — RFC 3164 hostname field is the short form.
        return h.split(".")[0]
    except Exception:
        return "xlog"


def _escape_cef_header(s: str) -> str:
    """Escape backslash and pipe in CEF header fields (between the | chars)."""
    return str(s).replace("\\", "\\\\").replace("|", "\\|")


def _escape_cef_extension_value(s: Any) -> str:
    r"""Escape backslash, equals, and newline in CEF extension VALUES.

    Per ArcSight CEF spec: \\, \=, \n are the three required escapes for
    the extension portion. Keep tabs/spaces literal — values can contain
    spaces (the parser splits on `<space>key=` boundaries).
    """
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


# XSIAM's column names for the CEF header slots. Bundled data-source schemas
# declare header fields under these names because they are what modeling rules
# read (`xdm.event.type = cefName`). They are never CEF extension keys: the
# broker derives these columns from the header. Sent as extensions they are
# worse than useless -- on vendors whose extension keys the broker whitelists
# (Zscaler, FortiGate) an unrecognized key is not a field boundary, so its text
# is glued onto the previous field. On a Cortex tenant:
# Zscaler `act` lands as "Allowed cefName=Web Transaction".
_CEF_HEADER_COLUMNS = frozenset({
    "cefVersion", "cefDeviceVendor", "cefDeviceProduct", "cefDeviceVersion",
    "cefDeviceEventClassId", "cefName", "cefSeverity",
})

# The CEF spec allows Severity as 0-10 or one of these words.
_CEF_TEXT_SEVERITIES = frozenset({"Unknown", "Low", "Medium", "High", "Very-High"})


def _first_present(rec: dict[str, Any], *keys: str) -> Any:
    """Value of the first key in `keys` that `rec` holds non-empty, else None."""
    for k in keys:
        v = rec.get(k)
        if v is not None and v != "":
            return v
    return None


def _cef_severity(v: Any) -> str:
    """Header Severity: an integer, a CEF-spec word, or the neutral default 5."""
    if v is None:
        return "5"
    if isinstance(v, str) and v in _CEF_TEXT_SEVERITIES:
        return v
    try:
        return str(int(v))
    except (TypeError, ValueError):
        return "5"


def _flatten_extension(rec: dict[str, Any]) -> str:
    """Build `key=value key=value …` from a record dict.

    Skips None/empty values. Lists/dicts are JSON-stringified (CEF doesn't
    have a native array form — embedding JSON is what most Cortex modeling
    rules tolerate).
    """
    parts: List[str] = []
    for k, v in rec.items():
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, (list, dict)):
            # Compact separators (no spaces) so the embedded JSON survives
            # CEF's space-delimited extension parsing — `actor={"id":"x"}`
            # stays ONE extension value, not split at the spaces a default
            # json.dumps would insert. The MR's json_extract_scalar then
            # parses the composite at query time.
            v_s = json.dumps(v, default=str, separators=(",", ":"))
        else:
            v_s = str(v)
        parts.append(f"{k}={_escape_cef_extension_value(v_s)}")
    return " ".join(parts)


def _parse_destination(destination: str) -> tuple[str, str, int]:
    """Parse `udp:host:port` or `tcp:host:port`. Returns (proto, host, port).

    Raises ValueError on malformed input.
    """
    parts = destination.split(":")
    if len(parts) != 3:
        raise ValueError(
            f"OverrideSender requires destination 'udp:host:port' or "
            f"'tcp:host:port', got {destination!r}"
        )
    proto, host, port_s = parts
    proto = proto.lower()
    if proto not in ("udp", "tcp"):
        raise ValueError(
            f"OverrideSender supports only udp/tcp protocols, got {proto!r}"
        )
    try:
        port = int(port_s)
    except ValueError as exc:
        raise ValueError(f"invalid port {port_s!r}") from exc
    return proto, host, port



# A Cortex Broker syslog collector accepts a datagram up to ~4 KB and
# SILENTLY truncates beyond it: a probe carrying markers at known byte
# offsets lands mark500..mark4000 and loses mark5000, mark6000 and
# mark8000 -- no error anywhere, the event simply arrives short.
#
# This matters because a full vendor schema overflows it easily: FortiGate's
# 222 declared fields encode to 5,259 bytes, so `spt=` (offset 4328) is always
# cut and `out=` (4028) is cut whenever the random values run long. The
# affected fields then read as null in XDM and look like a mapping bug rather
# than a transport one.
#
# The broker's truncation is invisible; ours is not. Trim to the limit and warn
# with the count, so an oversized event is a log line instead of a mystery.
def _field_to_dict(f):
    """Normalise one schema-override field to a JSON-serialisable dict.

    Accepts either a Strawberry input object (the create path) or a dict (the
    restore path), so a restored worker can be re-persisted without degrading.
    """
    if isinstance(f, dict):
        return {k: v for k, v in f.items() if v is not None}
    out = {}
    for attr in ("name", "type", "is_array", "is_meta", "is_gate", "example", "enum_values"):
        val = getattr(f, attr, None)
        if val is not None:
            out[attr] = val
    return out


_CEF_MAX_BYTES = 3900


def _guard_cef_length(line: str, ext: str, header: str) -> str:
    """Trim an oversized CEF line at an extension boundary, and say so.

    Cuts between `key=value` pairs rather than mid-token: a half-written pair
    is worse than a missing one, because the broker parses the fragment into a
    garbage column instead of dropping it.
    """
    encoded = line.encode("utf-8", "replace")
    if len(encoded) <= _CEF_MAX_BYTES:
        return line

    prefix_len = len(line) - len(ext)
    budget = _CEF_MAX_BYTES - prefix_len
    if budget <= 0:
        return line  # header alone exceeds the limit; nothing useful to trim

    kept, used, dropped = [], 0, 0
    for pair in ext.split(" "):
        take = len(pair) + (1 if kept else 0)
        if used + take > budget:
            dropped += 1
            continue
        kept.append(pair)
        used += take
    if dropped:
        logger.warning(
            "CEF event exceeded the %d-byte syslog limit (%d bytes); dropped "
            "%d of %d extension fields. The broker would have truncated these "
            "silently. Send fewer fields -- a real vendor event carries tens, "
            "not hundreds.",
            _CEF_MAX_BYTES, len(encoded), dropped, len(ext.split(" ")),
        )
    return line[:prefix_len] + " ".join(kept)


class OverrideSender:
    """Schema-override-aware tick sender for UDP/TCP destinations.

    Lifecycle: __init__ → start() → tick loop in worker thread →
    stop() signals exit. Workers are in-memory (per xlog convention);
    container restart drops them.
    """

    def __init__(
        self,
        worker_name: str,
        data_type: str,
        destination: str,
        vendor_fields: List[Any],
        count: int = 1,
        interval: int = 2,
        verify_ssl: bool = False,
        vendor: Optional[str] = None,
        product: Optional[str] = None,
        observable_overrides: Optional[dict[str, Any]] = None,
        max_events: Optional[int] = None,
        duration_seconds: Optional[int] = None,
    ) -> None:
        self.worker_name = worker_name
        self.data_type = data_type  # informational — kept for list_workers surface
        self.destination = destination
        self.count = count
        self.interval = interval
        self.verify_ssl = verify_ssl  # informational — UDP/TCP don't use TLS in xlog today
        self.vendor = vendor
        self.product = product
        self.vendor_fields = vendor_fields
        self.observable_overrides = observable_overrides or {}
        self.status = "Pending"
        self.created_at = datetime.datetime.utcnow()

        # Validate upfront so malformed input fails at create time (HTTP 400)
        # rather than silently in the worker thread.
        #
        # `interval <= 0` is the dangerous case, and it is not merely invalid —
        # it is the single highest-output configuration this class can take.
        # The tick loop throttles with `self._stop_event.wait(self.interval)`,
        # and Event.wait() returns IMMEDIATELY for both 0 and negative values.
        # So the loop spins as fast as the CPU allows: unbounded, forever.
        #
        # A negative interval was worse still. It also made `count / interval`
        # negative, so the `** HIGH RATE **` guard in _log_startup_rate — which
        # tests `per_sec > 10` — silently passed it. The most dangerous input
        # was the one that warned least. Refusing it here closes both holes at
        # once and lets _log_startup_rate assume a positive interval.
        if count < 1:
            raise ValueError(
                f"count must be >= 1, got {count!r}. Note `count` is events per "
                f"TICK on this path, not a total."
            )
        if interval < 1:
            raise ValueError(
                f"interval must be >= 1 second, got {interval!r}. An interval of "
                f"0 or less does not throttle at all — the worker would emit as "
                f"fast as the CPU allows, without bound and until stopped."
            )

        self._proto, self._host, self._port = _parse_destination(destination)

        # Threading state
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Emission accounting. The legacy Sender logs a line per event
        # ("sending log message"); this path logs the same wording
        # periodically so `docker logs xlog | grep -c "sending log message"`
        # reflects the output of both. Without it a worker doing 200
        # events/sec would look identical to an idle one. See
        # _log_startup_rate.
        self._sent_total = 0
        self._last_report_at = 0.0



        # Optional self-imposed budget. Declaring either one makes this worker
        # finite, which is what admission requires before granting a rate above
        # the sustained ceiling. Both are enforced in the tick loop below.
        self._max_events = int(max_events) if max_events else None
        self._max_seconds = int(duration_seconds) if duration_seconds else None

        # Record the spec LAST — after every attribute it reads exists.
        #
        # Placed earlier it silently did nothing: it reads self._max_events,
        # assigned just above, so it raised AttributeError straight into its
        # own except and logged nothing — the handler swallowed the very
        # failure it existed to report. Two deploys looked correct while
        # writing zero rows. Constructing a sender in a local test reproduced
        # it in seconds, which is where this should have been caught.
        self._persist_spec()

    @property
    def max_total_events(self) -> Optional[int]:
        """UNBOUNDED unless the caller declared a budget.

        The tick loop regenerates `count` records forever and never checks a
        total, so — unlike the legacy Sender and WebhookSender, both bounded
        by construction — this class has no natural end. `None` means exactly
        that, and admission then prices it on RATE, because an unbounded
        worker's eventual total is its rate times however long nobody notices.

        Declaring max_events (or duration_seconds, converted here at the
        worker's own rate) is the promise that makes it finite, and that
        promise is what buys the much higher burst ceiling.
        """
        if self._max_events:
            return int(self._max_events)
        if self._max_seconds:
            return int(self.events_per_second * self._max_seconds)
        return None

    @property
    def events_per_second(self) -> float:
        """This sender's SUSTAINED rate.

        On THIS class `count` is per TICK: the loop regenerates `count`
        records every iteration and never checks a running total, so the rate
        is `count / interval` and it runs until stopped. That is the opposite
        of the legacy Sender, where `count` is a TOTAL and the rate is
        `1 / interval`.

        __init__ rejects interval < 1, so this cannot divide by zero.
        """
        return self.count / self.interval

    # ─── lifecycle ───────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            logger.warning("OverrideSender %s already running", self.worker_name)
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"override-sender-{self.worker_name}", daemon=True
        )
        self.status = "Running"
        self._thread.start()


    def _persist_spec(self) -> None:
        """Record enough to rebuild this worker after a restart.

        Best-effort: a store failure must never stop a worker that is
        otherwise healthy, but it IS logged — a silent no-op here is how the
        restart problem stayed invisible in the first place.
        """
        try:
            from app import store

            store.save_worker_spec(
                self.worker_name,
                {
                    # Without this every restored worker was named
                    # "restored" — _rebuild_sender reads worker_name from the
                    # spec and the spec never stored it.
                    "worker_name": self.worker_name,
                    "type": self.data_type,
                    "destination": self.destination,
                    "count": self.count,
                    "interval": self.interval,
                    "vendor": self.vendor,
                    "product": self.product,
                    "verify_ssl": self.verify_ssl,
                    "max_events": self._max_events,
                    # The attribute is _max_seconds; persisting a name that does not
                    # exist would silently drop the deadline on restore.
                    "duration_seconds": self._max_seconds,
                    # Plain dicts, not the Strawberry SchemaOverrideField objects:
                    # those are not JSON-serialisable, so persisting them raised
                    # TypeError for EVERY schema-driven worker and the spec was
                    # never stored. dynamic_schema's accessors read dicts and
                    # objects alike, and _rebuild_sender passes this straight back
                    # as vendor_fields, so a dict round-trips cleanly.
                    "schema_override": [_field_to_dict(f) for f in (self.vendor_fields or [])],
                    "observable_overrides": self.observable_overrides or None,
                },
            )
            logger.info("persisted worker spec for %s", self.worker_name)
        except Exception as exc:
            logger.warning(
                "could not persist worker spec for %s: %s: %s",
                self.worker_name, type(exc).__name__, exc,
            )

    def _forget_spec(self) -> None:
        """Drop the persisted row so a restart never resurrects this worker."""
        try:
            from app import store

            store.delete_worker_spec(self.worker_name)
        except Exception:
            pass

    def stop(self) -> None:
        self._stop_event.set()
        self.status = "Stopped"
        self._forget_spec()
        # Don't join — workers stop is async per the existing Sender contract.

    # ─── tick loop ───────────────────────────────────────────────────

    # How often the tick loop emits a throughput summary. Low enough to
    # notice a runaway quickly, high enough not to spam a busy log.
    _REPORT_EVERY_SECONDS = 30


    _CHECKPOINT_EVERY_SECONDS = 30

    def _checkpoint_progress(self) -> None:
        """Persist events_sent so a restart resumes with the right budget."""
        now = time.monotonic()
        last = getattr(self, "_last_checkpoint_at", 0.0)
        if now - last < self._CHECKPOINT_EVERY_SECONDS:
            return
        self._last_checkpoint_at = now
        try:
            from app import store

            store.update_worker_progress(self.worker_name, self._sent_total)
        except Exception:
            # Advisory only — never let a store hiccup stop generation.
            pass

    def _log_startup_rate(self) -> None:
        """Announce the worker's SUSTAINED rate before the first tick.

        `count` is events per TICK, not a total, and these workers never
        self-terminate — so the real output is `count / interval` events per
        second, forever. That is easy to misread: a worker created with
        count=200, interval=1 reads like "200 events" but is actually 200
        events *per second* indefinitely, i.e. ~17M/day. Stating the computed
        rate and a projected daily volume at creation makes that obvious in
        the log instead of hours later in a tenant-side count.
        """
        # __init__ guarantees interval >= 1, so this cannot divide by zero and
        # cannot go negative (a negative rate would slip past the high-rate check
        # below).
        per_sec = self.count / self.interval
        # Pre-format the thousands separator: "%,.0f" is f-string syntax and
        # raises ValueError inside %-style logging, which logging swallows —
        # losing exactly the line this method exists to emit.
        per_day = f"{per_sec * 86400:,.0f}"
        # Threshold comes from Config rather than a literal, so it tracks the
        # admission ceiling instead of drifting away from it.
        from app.worker_registry import _int_env
        threshold = _int_env(Config.XLOG_HIGH_RATE_WARN_EVENTS_PER_SEC, 10)
        warn = " ** HIGH RATE **" if threshold > 0 and per_sec > threshold else ""
        logger.info(
            "OverrideSender %s starting: count=%s interval=%ss -> %.2f events/sec "
            "(~%s/day, sustained until stopped) dest=%s vendor=%s product=%s%s",
            self.worker_name, self.count, self.interval, per_sec, per_day,
            self.destination, self.vendor, self.product, warn,
        )

    def _run(self) -> None:
        """Per-tick: generate `count` records, encode, send to destination.

        Loops until stop_event is set. Sleeps interval between ticks.
        """
        try:
            sock = self._open_socket()
        except Exception as exc:
            logger.exception("OverrideSender %s: socket open failed: %s",
                             self.worker_name, exc)
            self.status = "Error"
            return

        self._log_startup_rate()
        started = time.monotonic()
        self._last_report_at = started

        try:
            while not self._stop_event.is_set():
                # Honour a declared budget. This is what makes the promise
                # real: admission granted a rate above the sustained ceiling
                # only because the worker said it was finite, so the worker
                # must actually stop. Checked at the TOP of the tick so the
                # budget bounds what is sent, not what was already sent.
                if self._max_events and self._sent_total >= self._max_events:
                    logger.info(
                        "OverrideSender %s stopping: event budget reached "
                        "(%s events)", self.worker_name, self._sent_total,
                    )
                    break
                if self._max_seconds and (time.monotonic() - started) >= self._max_seconds:
                    logger.info(
                        "OverrideSender %s stopping: duration budget reached "
                        "(%ss, %s events sent)",
                        self.worker_name, self._max_seconds, self._sent_total,
                    )
                    break
                try:
                    records = generate_records_with_override(
                        count=self.count,
                        vendor_fields=self.vendor_fields,
                        observable_overrides=self.observable_overrides,
                    )
                    sent = 0
                    for rec in records:
                        payload = self.format_record(rec).encode("utf-8")
                        if self._proto == "udp":
                            sock.sendto(payload, (self._host, self._port))
                        else:  # tcp
                            sock.sendall(payload + b"\n")
                        sent += 1
                    self._sent_total += sent
                    # Checkpoint progress so a restart cannot replay a bounded
                    # worker's FULL budget. Throttled to the reporting cadence
                    # rather than per tick — this is a SQLite write, and the
                    # worst case of being slightly stale is re-sending a few
                    # events, not the whole budget.
                    if self._max_events:
                        self._checkpoint_progress()

                    # Deliberately reuse the legacy Sender's "sending log
                    # message" wording so a single grep covers BOTH sender
                    # paths.
                    now = time.monotonic()
                    if now - self._last_report_at >= self._REPORT_EVERY_SECONDS:
                        elapsed = max(now - started, 1e-9)
                        logger.info(
                            "Worker: %s sending log message to %s "
                            "(+%d this tick, %d total, %.2f events/sec avg)",
                            self.worker_name, self._host, sent,
                            self._sent_total, self._sent_total / elapsed,
                        )
                        self._last_report_at = now
                except Exception as exc:
                    logger.exception(
                        "OverrideSender %s: tick failed: %s",
                        self.worker_name, exc,
                    )
                # Sleep interval, but wake up if stop fires mid-sleep.
                self._stop_event.wait(self.interval)
        finally:
            try:
                sock.close()
            except Exception:
                pass
            # Mark terminal HERE, not only in stop(). A worker that ends on
            # its own — budget reached, or the loop exiting for any other
            # reason — would keep reporting "Running" forever if only stop()
            # wrote this field.
            #
            # That is not just a cosmetic lie in list_workers. The registry
            # reclaims rate by pruning non-Running workers, so a finished
            # burst would keep consuming its share of the aggregate ceiling AND
            # hold its burst-concurrency slot until the container restarted —
            # meaning one completed burst would block every later one.
            if self.status == "Running":
                self.status = "Stopped"
            # A worker that ends by exhausting its own budget never passes
            # through stop(), so without this _forget_spec() would never be
            # called and the row would outlive the run. Every completed burst
            # would stay in the store and be resurrected on the next boot, and
            # stale specs would accumulate across restarts. Forget the spec
            # here too — it is idempotent.
            self._forget_spec()
            elapsed = max(time.monotonic() - started, 1e-9)
            logger.info(
                "OverrideSender %s stopped: %d events sent over %.0fs (%.2f events/sec avg)",
                self.worker_name, self._sent_total, elapsed,
                self._sent_total / elapsed,
            )

    # ─── wire-format encoders ─────────────────────────────────────────
    #
    # Branch on data_type so XSIAM brokers can route by header.
    # Public-method-shaped (not `_format_*`) so tests can call directly
    # without instantiating the socket / thread.

    def format_record(self, rec: dict[str, Any]) -> str:
        """Encode `rec` for the wire per `self.data_type`.

        Dispatches to one of the format-specific encoders below. Anything
        not recognized falls back to JSON.
        """
        dt = (self.data_type or "").upper()
        if dt == "CEF":
            return self._format_cef(rec)
        if dt == "SYSLOG":
            return self._format_syslog(rec)
        if dt == "LEEF":
            return self._format_leef(rec)
        if dt == "RAW":
            return self._format_raw(rec)
        # JSON / WINEVENT / Incident / XSIAM_* and any future enum:
        # keep JSON. WINEVENT could one day get its own XML/event-log
        # encoder; not required for the broker → vendor_product_raw path.
        return json.dumps(rec, default=str)

    def _format_cef(self, rec: dict[str, Any]) -> str:
        """Build a syslog-wrapped CEF line.

        Shape: `<134>Mon DD HH:MM:SS hostname CEF:0|Vendor|Product|Version|SigID|Name|Severity|ext`

        Vendor/Product come from the constructor (the agent always passes
        them when invoking generateDataWorker via the schema_override
        path — that's what determines the dataset name on the broker).
        A record's own `cefDeviceVendor`/`cefDeviceProduct` never override
        them: they would silently reroute the event to another dataset.

        Version/SignatureID/Name/Severity have neutral defaults, overlaid
        from the record. XSIAM's column names (`cefDeviceVersion`,
        `cefDeviceEventClassId`, `cefName`, `cefSeverity`) win, because
        they are what the bundled schemas declare; the generic aliases
        (`signatureId`, `name`, `msg`, `event`, `severity`) follow.
        """
        vendor = _escape_cef_header(self.vendor or "Phantom")
        product = _escape_cef_header(self.product or "xlog")
        version = _escape_cef_header(
            _first_present(rec, "cefDeviceVersion") or "1.0"
        )
        sig_id = _escape_cef_header(
            _first_present(rec, "cefDeviceEventClassId", "signatureId", "signature_id")
            or "100"
        )
        name = _escape_cef_header(
            _first_present(rec, "cefName", "name", "msg", "event") or "Event"
        )
        severity = _cef_severity(_first_present(rec, "cefSeverity", "severity"))

        # The `cef*` header columns leave the extension entirely (see
        # _CEF_HEADER_COLUMNS). The generic aliases stay: `msg` is a real
        # CEF extension key, and existing schemas rely on it landing there.
        ext = _flatten_extension(
            {k: v for k, v in rec.items() if k not in _CEF_HEADER_COLUMNS}
        )
        header = f"CEF:0|{vendor}|{product}|{version}|{sig_id}|{name}|{severity}|"
        line = (
            f"<{_SYSLOG_PRIORITY}>{_syslog_timestamp()} {_hostname()} "
            f"{header}{ext}"
        )
        return _guard_cef_length(line, ext, header)

    def _format_syslog(self, rec: dict[str, Any]) -> str:
        """Build a syslog line with vendor/product tag + key=value body.

        Shape: `<134>Mon DD HH:MM:SS hostname vendor-product: key=value …`

        XSIAM brokers parse the tag for routing hints when the inner
        payload isn't CEF/LEEF. Most Cortex modeling rules then use
        regextract against the key=value body in their .xif rules.
        """
        vendor = (self.vendor or "phantom").lower().replace(" ", "_")
        product = (self.product or "xlog").lower().replace(" ", "_")
        body = _flatten_extension(rec)
        return (
            f"<{_SYSLOG_PRIORITY}>{_syslog_timestamp()} {_hostname()} "
            f"{vendor}-{product}: {body}"
        )

    def _format_raw(self, rec: dict[str, Any]) -> str:
        """Emit the vendor's OWN log line, syslog-framed, verbatim.

        Why this exists. A CEF event's extensions become dataset COLUMNS and
        the broker leaves `_raw_log` EMPTY -- verified on a Cortex tenant. 94 of
        the bundled sources' modeling rules regex-extract from `_raw_log`
        (Microsoft DNS pulls the ANSWER SECTION span, the PACKET id and the
        M/D/YYYY timestamp straight out of it), so those sources can NEVER map
        over CEF however the schema is shaped. Sending the vendor's native line
        as an unformatted syslog body populates `_raw_log` with the whole line,
        frame included -- also verified on a Cortex tenant.

        The body is the record's `_raw_log`, which is exactly the field those
        94 schemas already declare. Pin it via observables_dict (or let the
        generator pin it to the field's example).

        TWO CAVEATS, both proven empirically:

        * ROUTING. A raw line carries no CEF header, so the broker cannot
          derive vendor/product from the wire and the event lands in
          `unknown_unknown_raw`. Routing MUST come from the Broker VM syslog
          collector configuration (a collector row mapping this source network
          or port to the target vendor/product). Adding a `vendor-product:`
          syslog tag does NOT help -- tested, still unknown/unknown.

        * THE SYSLOG FRAME IS PART OF `_raw_log`. The broker stores
          `<134>Mon DD HH:MM:SS host <body>` in full. Rules matching with `~=`
          are unaffected; a rule anchored with `^` would need the frame
          accounted for.
        """
        body = rec.get("_raw_log") or rec.get("raw_log")
        if not body:
            # No native line in the schema -- fall back rather than emit an
            # empty frame, so a misconfigured source still produces something
            # diagnosable on the wire.
            body = _flatten_extension(rec)
        return (
            f"<{_SYSLOG_PRIORITY}>{_syslog_timestamp()} {_hostname()} {body}"
        )

    def _format_leef(self, rec: dict[str, Any]) -> str:
        """Build a syslog-wrapped LEEF 2.0 line (QRadar/SIEM-flex).

        Shape: `<134>Mon DD HH:MM:SS hostname LEEF:2.0|Vendor|Product|Version|EventID|ext`

        Less common than CEF, but the few connectors that
        prefer LEEF (some IBM/QRadar-targeted ones) get clean output
        instead of mistaken JSON.
        """
        vendor = _escape_cef_header(self.vendor or "Phantom")
        product = _escape_cef_header(self.product or "xlog")
        version = "1.0"
        event_id = _escape_cef_header(
            rec.get("eventId") or rec.get("event_id") or "100"
        )
        ext = _flatten_extension(rec)
        header = f"LEEF:2.0|{vendor}|{product}|{version}|{event_id}|"
        return (
            f"<{_SYSLOG_PRIORITY}>{_syslog_timestamp()} {_hostname()} "
            f"{header}{ext}"
        )

    def _open_socket(self) -> socket.socket:
        if self._proto == "udp":
            return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # TCP: connect upfront so listener auth/handshake errors surface
        # at start time, not on every tick.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((self._host, self._port))
        s.settimeout(None)
        return s
