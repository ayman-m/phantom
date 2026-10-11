import datetime
import threading
import time
from typing import List, Dict, Any

import httpx


class WebhookSender:
    def __init__(
        self,
        worker_name: str,
        destination: str,
        payloads: List[Dict[str, Any]],
        interval: int,
        verify_ssl: bool,
        headers: Dict[str, str],
    ):
        self.worker_name = worker_name
        self.destination = destination
        self.payloads = payloads
        self.interval = int(interval)
        self.verify_ssl = verify_ssl
        self.headers = headers
        self.created_at = datetime.datetime.now()
        self.count = str(len(payloads))
        self.data_type = "JSON"
        self.status = "Stopped"
        self._stop_event = threading.Event()
        self._thread = None

    @property
    def max_total_events(self):
        """BOUNDED BY CONSTRUCTION — `_run` walks a fixed payload list once."""
        return len(self.payloads)

    @property
    def events_per_second(self) -> float:
        """This sender's SUSTAINED rate.

        Bounded by construction: `_run` iterates a FIXED `payloads` list once
        and exits, so this worker always self-terminates and its total is
        `len(payloads)` no matter what. `count` here is that length — a total,
        like the legacy Sender's, not a per-tick figure.

        The rate is one payload per interval. A non-positive interval means no
        throttle at all (`_run` skips the sleep entirely when interval <= 0),
        which is reported as unbounded so admission prices it honestly — even
        though the fixed payload list caps the damage.
        """
        if self.interval <= 0:
            return float("inf")
        return 1.0 / self.interval

    def start(self):
        if self.status == "Running":
            return
        self.status = "Running"
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        self.status = "Stopped"

    def _run(self):
        with httpx.Client(timeout=10.0, verify=self.verify_ssl) as client:
            for payload in self.payloads:
                if self._stop_event.is_set():
                    break
                try:
                    client.post(self.destination, json=payload, headers=self.headers)
                except Exception:
                    pass
                if self.interval > 0:
                    time.sleep(self.interval)
        if not self._stop_event.is_set():
            self.status = "Completed"
