from datetime import datetime
from enum import Enum
import threading
import socket
import requests
import warnings
from typing import Optional
from urllib3.exceptions import InsecureRequestWarning

from app.logforge.rfaker import Observables, Events


class WorkerTypeEnum(str, Enum):
    SYSLOG = "SYSLOG"
    CEF = "CEF"
    LEEF = "LEEF"
    WINEVENT = "WINEVENT"
    JSON = "JSON"
    INCIDENT = "INCIDENT"


class Sender:
    """
    A class for sending fake data to a destination via a TCP or UDP socket or HTTP request.

    Args:
        worker_name (str): Name of the worker.
        data_type (str): Type of the data to send.
        count (int): Number of messages to send.
        interval (int): Time interval (in seconds) between each message sent.
        destination (str): Destination address in the format <protocol>://<ip_address>:<port>.
        observables (Observables): Host name or IP address to use for fake data.
        fields (str): Comma-separated list of incident fields to include in the fake data.

    Attributes:
        thread (threading.Thread): Thread object for the worker.
        worker_name (str): Name of the worker.
        data_type (WorkerTypeEnum): Type of the data to send.
        count (int): Number of messages to send.
        interval (int): Time interval (in seconds) between each message sent.
        destination (str): Destination address in the format <protocol>://<ip_address>:<port>.
        created_at (datetime): Timestamp of when the worker was created.
        status (str): Status of the worker (Running, Stopped, Connection Error).
        observables (list): Host name or IP address to use for fake data.
        fields (str): Comma-separated list of incident fields to include in the fake data.

    Methods:
        start() -> str:
            Starts the worker thread.

            Returns:
                str: Current status of the worker (Running, Stopped).

        stop() -> str:
            Stops the worker thread.

            Returns:
                str: Current status of the worker (Running, Stopped).

        send_data() -> None:
            Sends fake data to the destination address.

            Returns:
                None.
    """

    def __init__(self, data_type: str, destination: str, headers: Optional[dict] = None,
                 worker_name: Optional[str] = 'worker_'+str(datetime.now()), count: Optional[int] = 1,
                 interval: Optional[int] = 1, vendor: Optional[str] = None, product: Optional[str] = None,
                 version: Optional[str] = None, required_fields: Optional[str] = None,
                 observables: Optional[Observables] = None, fields: Optional[str] = None,
                 verify_ssl: Optional[bool] = None, datetime_obj: Optional[datetime] = None,
                 data_json: Optional[dict] = None, data_text: Optional[str] = None):
        """
        Constructor for DataSenderWorker class.

        :param data_type: A value from the WorkerTypeEnum indicating the type of data to send. Options include:
            - SYSLOG
            - CEF
            - LEEF
            - WINEVENT
            - JSON
            - INCIDENT
        :param destination: str, destination address and port in the format <scheme>://<address>:<port>.
        :param worker_name: str, name of the worker.
        :param count: int, number of times to send the data.
        :param interval: int, time interval between two consecutive data sends.
        :param vendor: Optional. The vendor.
        :param product: Optional. The product.
        :param version: Optional. The version.
        :param required_fields: Optional. A list of fields that are required to present in the generated data, whether
         from observables or randomely.
        :param observables: Optional. Observables, list of observables.
        :param fields: Optional. comma-separated list of fields to include in incident data.
        :param verify_ssl: Optional. handling ssl verification errors.
        :param datetime_obj: Optional. time to start from.
        :param data_json: Optional. JSON data to send.
        :param data_text: Optional. Text data to send.

        :return: None
        """
        if headers is None:
            self.headers = {}
        else:
            self.headers = headers
        self.thread = None
        # Signalled by stop() so a worker sleeping between sends wakes at once
        # instead of serving out its full interval. Without this a worker with
        # a long interval stayed "Running" long after being asked to stop.
        self._wake = threading.Event()
        self.worker_name = worker_name
        if isinstance(data_type, WorkerTypeEnum):
            data_type = data_type.value
        self.data_type = data_type
        self.count = count
        self.interval = interval
        self.vendor = vendor
        self.product = product
        self.version = version
        self.required_fields = required_fields
        self.destination = destination
        self.created_at = datetime.now()
        self.status = "Stopped"
        self.response = None
        self.observables = observables
        self.fields = fields
        self.verify_ssl = verify_ssl
        self.datetime_obj = datetime_obj
        self.data_json = data_json
        self.data_text = data_text
        # Pre-generated events awaiting send. See _refill_buffer.
        self._buffer = []

    def start(self) -> str:
        """
        Starts the worker thread.

        Returns:
            str: Current status of the worker (Running, Stopped).
        """
        if self.status == "Stopped":
            self._wake.clear()
            self.thread = threading.Thread(target=self.send_data, args=())
            self.status = "Running"
            print(f"Starting worker: {self.worker_name}")
            self.thread.start()
        return self.status

    # How long stop() waits for the send thread to unwind. Bounded because the
    # thread can be blocked in a socket write to a dead destination, and a
    # resolver must never hang on that.
    _STOP_JOIN_TIMEOUT = 2.0

    @property
    def max_total_events(self) -> Optional[int]:
        """This sender is BOUNDED BY CONSTRUCTION — `count` is its total.

        The loop is `while status == "Running" and count > 0`, decrementing
        once per iteration, so the worker delivers exactly `count` events and
        then stops. There is no way for it to run forever.

        That is why admission prices this class by TOTAL rather than by rate:
        a bounded 100-event run is harmless however fast it goes, whereas an
        unbounded worker's total is its rate times forever.
        """
        try:
            return max(int(self.count), 0)
        except (TypeError, ValueError):
            return None

    @property
    def events_per_second(self) -> float:
        """This sender's SUSTAINED rate.

        On THIS class `count` is a TOTAL, not a per-tick figure: the send loop
        is `while status == "Running" and count > 0`, decrementing once per
        iteration and emitting exactly one message each time. So the rate is
        `1 / interval` regardless of count, and the worker self-terminates
        after roughly `count * interval` seconds.

        That is the opposite of OverrideSender, which regenerates `count`
        records every tick and never terminates. Same argument names, ~200x
        difference in delivered volume — which is precisely why admission asks
        the sender for its rate instead of computing one from the request.
        """
        interval = int(self.interval or 0)
        if interval <= 0:
            # No throttle at all; see worker_registry.rate_from.
            return float("inf")
        return 1.0 / interval

    def stop(self) -> str:
        """
        Stops the worker thread.

        Returns:
            str: Current status of the worker (Running, Stopped).
        """
        if self.status == "Running":
            # Flip the status BEFORE joining. The send loop's condition is
            # `while self.status == "Running" and self.count > 0`, so joining
            # first meant the thread never saw the stop signal and stop()
            # blocked until `count` exhausted on its own — potentially days
            # for a large count or long interval, with the caller hung and
            # the worker uncounted against nothing.
            self.status = "Stopped"
            # Wake the loop if it is mid-sleep, then wait only briefly. The
            # thread may still be blocked in a socket write to a dead
            # destination; stopping is asynchronous by contract (OverrideSender
            # behaves the same way), so we must not block the resolver on it.
            self._wake.set()
            self.thread.join(timeout=self._STOP_JOIN_TIMEOUT)
        return self.status

    # How many events to synthesize per generator call. Event synthesis is the
    # expensive part of a tick — the wire write is trivial by comparison — so
    # generating in batches is what decouples throughput from `interval`.
    # 50 keeps peak memory small while amortizing ~98% of the per-call overhead.
    _BATCH_SIZE = 50

    def _refill_buffer(self) -> None:
        """Synthesize the next batch of events into `self._buffer`.

        Generating once PER EVENT (`Events.<fmt>(count=1)` inside the send loop)
        would pay the full generator setup cost on every call, so a worker would
        deliver only ~10 events/min no matter how small `interval` was — the loop
        would be generation-bound, not paced. Requesting a batch and sending
        from it makes the send loop actually honor `interval`.

        Only the number of events still owed is generated, so `count` semantics
        and mid-stream stops are unchanged.
        """
        want = min(self._BATCH_SIZE, self.count)
        if want <= 0:
            return
        if self.data_type == "SYSLOG":
            self._buffer = list(Events.syslog(
                count=want, datetime_iso=self.datetime_obj,
                observables=self.observables, required_fields=self.required_fields))
        elif self.data_type == "CEF":
            self._buffer = list(Events.cef(
                count=want, datetime_iso=self.datetime_obj, vendor=self.vendor,
                product=self.product, version=self.version,
                required_fields=self.required_fields, observables=self.observables))
        elif self.data_type == "LEEF":
            self._buffer = list(Events.leef(
                count=want, datetime_iso=self.datetime_obj, vendor=self.vendor,
                product=self.product, version=self.version,
                required_fields=self.required_fields, observables=self.observables))
        elif self.data_type == "JSON":
            self._buffer = list(Events.json(
                count=want, datetime_iso=self.datetime_obj,
                observables=self.observables, vendor=self.vendor,
                product=self.product, version=self.version,
                required_fields=self.required_fields))
        elif self.data_type == "INCIDENT":
            self._buffer = [
                {"alert": a} for a in Events.incidents(
                    count=want, observables=self.observables, vendor=self.vendor,
                    version=self.version, product=self.product,
                    datetime_iso=self.datetime_obj,
                    required_fields=self.required_fields, fields=self.fields)
            ]

    def _next_message(self):
        """Return the next event to send, refilling the batch buffer as needed.

        A caller-supplied literal (`data_text` / `data_json`) bypasses generation
        entirely and is returned verbatim, exactly as before.
        """
        if self.data_type in ["SYSLOG", "CEF", "LEEF"] and self.data_text:
            return self.data_text
        if self.data_type in ["JSON", "INCIDENT"] and self.data_json:
            return self.data_json
        if not self._buffer:
            self._refill_buffer()
        if not self._buffer:
            return None
        return self._buffer.pop(0)

    def send_data(self) -> None:
        """
        Sends fake data to the destination address.

        Returns:
            None.
        """
        fake_message = None
        while self.status == "Running" and self.count > 0:
            try:
                self.count -= 1
                message = self._next_message()
                if message is None:
                    self.status = "Stopped"
                    break
                if self.data_type in ["SYSLOG", "CEF", "LEEF"]:
                    fake_message = [message]
                    ip_address = self.destination.split(':')[1]
                    port = self.destination.split(':')[2]
                    if 'tcp' in self.destination:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(5)
                        sock.connect((ip_address, int(port)))
                        print(f"Worker: {self.worker_name} sending log message to {ip_address} ")
                        sock.sendall(fake_message[0].encode())
                        sock.close()
                    else:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        sock.settimeout(5)
                        print(f"Worker: {self.worker_name} sending log message to {ip_address} ")
                        sock.sendto(fake_message[0].encode(), (ip_address, int(port)))
                elif self.data_type in ["JSON", "INCIDENT"]:
                    fake_message = [message]
                    if '://' not in self.destination:
                        url = 'http://' + self.destination
                    else:
                        url = self.destination
                    warnings.filterwarnings("ignore", category=InsecureRequestWarning)
                    print(f"Worker: {self.worker_name} sending log message to {url} ")
                    response = requests.post(url, json=fake_message[0], timeout=(2, 5), headers=self.headers,
                                             verify=self.verify_ssl)
                    self.response = response.text
                    response.raise_for_status()
            except (ConnectionRefusedError, socket.timeout, requests.exceptions.RequestException) as e:
                print(f"Connection error: {e}")
                self.status = "Connection Error"
                break
            except requests.exceptions.SSLError as e:
                print(f"SSL error: {e}")
                self.status = "SSL Error"
                break
            except Exception as e:
                print(f"Unexpected error: {e}")
                self.status = "Stopped"
                break
            # Interruptible: returns immediately once stop() sets _wake, so a
            # long interval no longer delays shutdown. Equivalent to
            # time.sleep(interval) when nothing is stopping the worker.
            if self._wake.wait(self.interval):
                break
        if self.status == "Running":
            self.status = "Stopped"
