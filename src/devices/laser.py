"""Client-side handles to the LASERLABCOMPUTER laser server and the EPICS
wavemeter PVs. The Matisse is reached over XML-RPC; EPICS is reached
directly.
"""

import os
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


class MatisseDevice:
    """Thin XML-RPC proxy mirroring the LaserServerInterface methods.

    All calls hold a process-local lock so the GUI and Scanner threads can't
    interleave Matisse commands on the wire. The server side has its own lock
    too; this one mostly avoids needless XML-RPC concurrency in our process.
    """

    def __init__(self, controller_name: str = "", initialization_params: dict = {}):
        self.url = f"http://{LAB_COMPUTER_IP}:{LAB_COMPUTER_PORT}"
        self.lock = Lock()
        self.proxy = xmlrpc.client.ServerProxy(
            self.url,
            allow_none=True,
            use_builtin_types=True,
        )
        print(f"[Matisse] Connected to server proxy at {self.url}")

    # ---- CounterDrift ----

    def cd_open(self) -> bool:
        with self.lock:
            return bool(self.proxy.cd_open())

    def cd_setpoint(self, nm: float) -> bool:
        with self.lock:
            return bool(self.proxy.cd_setpoint(float(nm)))

    def cd_activate(self, state: bool) -> bool:
        with self.lock:
            return bool(self.proxy.cd_activate(bool(state)))

    def cd_get_wavelength(self) -> float:
        with self.lock:
            return float(self.proxy.cd_get_wavelength())

    # ---- GoTo ----

    def goto_open(self) -> bool:
        with self.lock:
            return bool(self.proxy.goto_open())

    def goto_set(self, nm: float) -> bool:
        with self.lock:
            return bool(self.proxy.goto_set(float(nm)))

    def goto_start(self) -> bool:
        with self.lock:
            return bool(self.proxy.goto_start())

    def goto_status(self) -> str:
        with self.lock:
            return str(self.proxy.goto_status())


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
