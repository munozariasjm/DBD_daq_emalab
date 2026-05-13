"""Client-side handles to the LASERLABCOMPUTER laser server and the EPICS
wavemeter PVs. The Matisse is reached over XML-RPC; EPICS is reached
directly.

Every XML-RPC call goes through `_call`, which prints a clearly formatted
banner on the DAQ terminal whenever the server is unreachable, hung, or
returning XML-RPC faults. Repeated failures are deduplicated to one short
"still unreachable" line so the log isn't flooded; the next successful call
prints a "server reachable again" notice so a recovery is also visible.
"""

import os
import socket
import xmlrpc.client
from threading import Lock

try:
    import epics
except ImportError:
    print("[HW] Warning: epics module not found.")
    epics = None


LAB_COMPUTER_IP = "10.54.6.1"
LAB_COMPUTER_PORT = "8000"

if os.environ.get("SIMULATION", "0") == "1":
    LAB_COMPUTER_IP = "localhost"


# Exception types that mean "the laser server is unreachable / unresponsive".
_NETWORK_ERRORS = (
    xmlrpc.client.Fault,
    xmlrpc.client.ProtocolError,
    ConnectionRefusedError,
    ConnectionResetError,
    ConnectionAbortedError,
    socket.timeout,
    socket.gaierror,
    OSError,
)


class MatisseDevice:
    """Thin XML-RPC proxy mirroring the LaserServerInterface methods."""

    def __init__(self, controller_name: str = "", initialization_params: dict = {}):
        self.url = f"http://{LAB_COMPUTER_IP}:{LAB_COMPUTER_PORT}"
        self.lock = Lock()
        self.proxy = xmlrpc.client.ServerProxy(
            self.url,
            allow_none=True,
            use_builtin_types=True,
        )
        # None = unknown, True = last call OK, False = last call failed.
        # Used to dedupe noisy outage logs.
        self._healthy = None
        print(f"[Matisse] Connecting to laser server at {self.url} ...")
        self._ping_on_startup()

    # ---- Connectivity ----

    def _ping_on_startup(self):
        # Step 1: TCP-level reachability. Succeeds fast if anything is
        # listening on host:port, fails fast (ConnectionRefused / EHOSTUNREACH
        # / DNS error) otherwise. Independent of which XML-RPC methods the
        # deployed server exposes.
        host = LAB_COMPUTER_IP
        try:
            port = int(LAB_COMPUTER_PORT)
        except (TypeError, ValueError):
            port = 8000
        try:
            with socket.create_connection((host, port), timeout=2.0):
                pass
        except _NETWORK_ERRORS as e:
            self._log_outage("tcp_connect", (host, port), e)
            self._healthy = False
            return

        # Step 2: server is reachable. Try the new ping() for a hardware-side
        # health check. If the deployed server is older and doesn't implement
        # ping(), it returns an XML-RPC Fault (NOT a network error) — treat
        # that as "reachable, older API" rather than an outage.
        try:
            with self.lock:
                ok = bool(self.proxy.ping())
        except xmlrpc.client.Fault:
            print(
                f"[Matisse] Server reachable at {self.url} (older API: no ping). "
                "Hardware health will only surface on first real command."
            )
            self._healthy = True
            return
        except _NETWORK_ERRORS as e:
            self._log_outage("ping", (), e)
            self._healthy = False
            return

        if ok:
            print(f"[Matisse] Server ping OK at {self.url}")
            self._healthy = True
        else:
            # Server is up but its Matisse handle is None — the laser itself
            # is not initialised. The DAQ can still boot; the operator needs
            # to restart Matisse Commander / the server.
            print("[Matisse] =========== LASER SERVER WARNING ===========")
            print(f"[Matisse] Server at {self.url} is reachable but reports")
            print("[Matisse] that the Matisse handle is NOT initialised.")
            print("[Matisse] Restart laser_server.py with Matisse Commander")
            print("[Matisse] running and the USB device available.")
            print("[Matisse] ============================================")
            self._healthy = False

    def is_healthy(self) -> bool:
        return self._healthy is True

    # ---- Internal call wrapper ----

    def _call(self, method: str, *args):
        """Invoke `method` on the server proxy with logging on failure.

        On any network/XML-RPC error, prints a banner on first occurrence
        (subsequent identical failures get one short line) and re-raises so
        the controller's per-call exception handler can react. On recovery,
        prints a "reachable again" message exactly once per outage."""
        try:
            with self.lock:
                result = getattr(self.proxy, method)(*args)
        except _NETWORK_ERRORS as e:
            self._log_outage(method, args, e)
            self._healthy = False
            raise
        if self._healthy is False:
            print(f"[Matisse] Server reachable again at {self.url}")
        self._healthy = True
        return result

    def _log_outage(self, method, args, err):
        if self._healthy is False:
            print(
                f"[Matisse] {method}{tuple(args)}: still unreachable "
                f"({type(err).__name__}: {err})"
            )
            return
        print("[Matisse] =============== LASER SERVER ERROR ===============")
        print(f"[Matisse] URL    : {self.url}")
        print(f"[Matisse] Call   : {method}{tuple(args)}")
        print(f"[Matisse] Error  : {type(err).__name__}: {err}")
        print("[Matisse] Hint   : check that LASERLABCOMPUTER/laser_server.py")
        print(f"[Matisse]          is running and that {self.url} is reachable.")
        print("[Matisse] ==================================================")

    # ---- CounterDrift ----

    def cd_open(self) -> bool:
        return bool(self._call("cd_open"))

    def cd_setpoint(self, nm: float) -> bool:
        return bool(self._call("cd_setpoint", float(nm)))

    def cd_activate(self, state: bool) -> bool:
        return bool(self._call("cd_activate", bool(state)))

    def cd_get_wavelength(self) -> float:
        return float(self._call("cd_get_wavelength"))

    # ---- GoTo ----

    def goto_open(self) -> bool:
        return bool(self._call("goto_open"))

    def goto_set(self, nm: float) -> bool:
        return bool(self._call("goto_set", float(nm)))

    def goto_start(self) -> bool:
        return bool(self._call("goto_start"))

    def goto_status(self) -> str:
        return str(self._call("goto_status"))


class ComClient:
    """Thin wrapper around epics.caget so the controller has one indirection
    point for wavemeter reads. Kept for compatibility with the existing
    daq_system.py wiring."""

    def __init__(self, matisse_device, **kwargs):
        self.matisse = matisse_device

    def caget(self, pvname: str):
        try:
            return epics.caget(pvname)
        except Exception as e:
            print(f"[EPICS Client Error] {e}")
            return 0.0
