import os


class Config:
    # XLOG_API_KEY — bearer token the auth middleware enforces. Sourced
    # from the container's environment which docker-compose populates
    # from .env (operators set it there).
    # Empty value = permissive mode (preserves upgrade compatibility
    # with deploys that pre-date the auth middleware).
    XLOG_API_KEY = os.getenv("XLOG_API_KEY", "")
    WORKERS_NUMBER = os.getenv("WORKERS_NUMBER", "25")
    # Reaper. Detector A (dead thread) is unambiguous and always on.
    # Detector B (stall) is heuristic and OFF by default — a slow worker is
    # not a stalled one, and reaping a healthy baseline is worse than the
    # capacity leak it would fix. Set a floor in seconds to enable it.
    XLOG_REAPER_INTERVAL_SECONDS = os.getenv("XLOG_REAPER_INTERVAL_SECONDS", "60")
    XLOG_REAPER_STALL_SECONDS = os.getenv("XLOG_REAPER_STALL_SECONDS", "0")

    # ─── generation-rate ceilings ────────────────────────────────────────
    # Workers are admitted by app/worker_registry.py, which prices each one
    # in events/sec. These bound VOLUME, not access.
    #
    # The ceiling is on the integral as well as the derivative. A high rate
    # is not refused outright — it is refused as a SUSTAINED rate, while a
    # BURST that declares its own size (duration_seconds or max_events) is
    # granted up to a much higher rate but a bounded total. That split is
    # what keeps Phantom's actual purpose intact: "a few hundred events
    # quickly" is served, "a few hundred events per second forever" is not.
    #
    # Set any ceiling to 0 to disable it (logged as a WARNING at boot).

    # Sustained per-worker ceiling. 10/sec is 20x the intended ~0.5/sec
    # steady state and 20x below a runaway 200/sec worker.
    XLOG_MAX_WORKER_EVENTS_PER_SEC = os.getenv("XLOG_MAX_WORKER_EVENTS_PER_SEC", "10")
    # Ceiling for a declared, bounded burst.
    XLOG_MAX_BURST_EVENTS_PER_SEC = os.getenv("XLOG_MAX_BURST_EVENTS_PER_SEC", "500")
    # Hard total for one burst grant, regardless of its rate.
    XLOG_MAX_BURST_EVENTS = os.getenv("XLOG_MAX_BURST_EVENTS", "50000")
    # Burst grants are counted separately from the sustained aggregate;
    # without that split the two ceilings contradict each other.
    XLOG_MAX_CONCURRENT_BURSTS = os.getenv("XLOG_MAX_CONCURRENT_BURSTS", "1")
    # Aggregate sustained ceiling across every live worker. 50/sec is
    # 180,000/hour — under a fifth of the ~1M events a runaway worker can emit in an hour.
    XLOG_MAX_TOTAL_EVENTS_PER_SEC = os.getenv("XLOG_MAX_TOTAL_EVENTS_PER_SEC", "50")

    # ─── per-worker lifetime bounds (OFF by default) ─────────────────────
    # Phantom advertises CONTINUOUS simulation, so nothing expires unless an
    # operator opts in. The rate ceilings above already prevent floods; these
    # bound what a forgotten worker accumulates over time. 0 = no bound.
    # Suggested if you enable them: 50000 events / 86400 seconds.
    XLOG_WORKER_MAX_EVENTS = os.getenv("XLOG_WORKER_MAX_EVENTS", "0")
    XLOG_WORKER_MAX_LIFETIME_SECONDS = os.getenv("XLOG_WORKER_MAX_LIFETIME_SECONDS", "0")

    # Rate at or above which a worker's startup line is flagged
    # ** HIGH RATE **. Was a hardcoded literal in override_sender.py.
    XLOG_HIGH_RATE_WARN_EVENTS_PER_SEC = os.getenv("XLOG_HIGH_RATE_WARN_EVENTS_PER_SEC", "10")
    LOGGING_DIR = os.getenv("LOGGING_DIR", "logs")
    LOGGING_STORAGE_SIZE = os.getenv("LOGGING_STORAGE_SIZE", "10M")
    LOGGING_TRUNCATE_LIMIT = os.getenv("LOGGING_TRUNCATE_LIMIT", "100")
    XSIAM_MANDATORY_PARSED_FIELDS = os.getenv(
        "XSIAM_MANDATORY_PARSED_FIELDS",
        "remote_ip,remote_port,local_ip,local_port,event_timestamp,severity,alert_name",
    )
    XSIAM_OPTIONAL_PARSED_FIELDS = os.getenv(
        "XSIAM_OPTIONAL_PARSED_FIELDS",
        "alert_description,action_status,local_ip_v6,remote_ip_v6",
    )
