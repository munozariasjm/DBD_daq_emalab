"""Simulation stand-ins for the Matisse laser and the EPICS wavemeter.

`MockMatisseDevice` mimics the Sirah.SirahMatisse handle: it accepts MCP
commands via ask(cmd) -> str and maintains the small bit of internal state
needed to satisfy the controller's CounterDrift / GoTo sequence.

`MockEpicsClient` queries the same MockMatisseDevice for the simulated
wavenumber so the wavemeter readback stays consistent with whatever the
fake laser is doing.
"""

import random
import threading
import time

from src.utils.units import nm_vacuum_to_wn, wn_to_nm_vacuum


class MockMatisseDevice:
    """Stand-in for `pylablib.devices.Sirah.SirahMatisse`.

    Public surface that the server uses: `ask(cmd) -> str` and `close()`.
    Public surface that the EPICS mock reads: `sim_wn` (cm^-1).
    """

    def __init__(self, initialization_params: dict = {}):
        self._lock = threading.Lock()
        # Simulated laser state
        self.sim_wn = float(initialization_params.get("initial_wn", 12625.0))
        self._cd_active = False
        self._cd_setpoint_nm = wn_to_nm_vacuum(self.sim_wn)
        self._goto_target_nm = wn_to_nm_vacuum(self.sim_wn)
        self._goto_running = False
        self._cd_dialog_open = False
        self._goto_dialog_open = False
        # Slew dynamics (cm^-1 per second toward target when active)
        self._slew_rate = float(initialization_params.get("slew_rate", 50.0))
        self._last_update = time.time()
        # Wavemeter noise (cm^-1)
        self.noise = float(initialization_params.get("noise_level", 1e-6))

    # ---- Sim physics ----

    def _advance(self):
        now = time.time()
        dt = max(0.0, now - self._last_update)
        self._last_update = now
        target_wn = None
        if self._goto_running:
            target_wn = nm_vacuum_to_wn(self._goto_target_nm)
        elif self._cd_active:
            target_wn = nm_vacuum_to_wn(self._cd_setpoint_nm)
        if target_wn is None:
            return
        diff = target_wn - self.sim_wn
        step = self._slew_rate * dt
        if abs(diff) <= step:
            self.sim_wn = target_wn
            if self._goto_running:
                self._goto_running = False
        else:
            self.sim_wn += step if diff > 0 else -step

    # ---- MCP command dispatcher ----

    def ask(self, cmd: str) -> str:
        with self._lock:
            self._advance()
            stripped = cmd.strip()
            # Mirror the real server: tolerate the `#SERVER ` routing prefix
            # that Matisse Commander requires before MCP commands.
            if stripped.startswith("#SERVER"):
                stripped = stripped[len("#SERVER"):].lstrip()
            parts = stripped.split()
            if not parts:
                return "Ok"
            head = parts[0]
            if head == "MCP_WM_CounterDrift":
                self._cd_dialog_open = True
                return "Ok"
            if head == "MCP_WM_GotoPosition":
                self._goto_dialog_open = True
                return "Ok"
            if head == "MCP_WM_GET_WAVELENGTH":
                return f"{wn_to_nm_vacuum(self.sim_wn):.8f}"
            if head == "MCP_WM.Counterdrift":
                sub = parts[1] if len(parts) > 1 else ""
                if sub == "Setpoint" and len(parts) >= 3:
                    self._cd_setpoint_nm = float(parts[2])
                    return "Ok"
                if sub == "Activate" and len(parts) >= 3:
                    self._cd_active = parts[2].lower() == "true"
                    return "Ok"
            if head == "MCP_WM.GoTo":
                sub = parts[1] if len(parts) > 1 else ""
                if sub == "Goto" and len(parts) >= 3:
                    self._goto_target_nm = float(parts[2])
                    return "Ok"
                if sub == "Start":
                    self._goto_running = True
                    return "Ok"
                if sub == "Stop":
                    self._goto_running = False
                    return "Ok"
                if sub == "status":
                    return "RUNNING" if self._goto_running else "STOP"
            return "Ok"

    def close(self):
        with self._lock:
            self._cd_active = False
            self._goto_running = False

    # ---- High-level API mirroring MatisseDevice (XML-RPC client) ----
    # These let the simulation DAQSystem use this mock directly without going
    # through laser_server.py / XML-RPC. Each forwards to ask().

    def cd_open(self) -> bool:
        self.ask("MCP_WM_CounterDrift")
        return True

    def cd_setpoint(self, nm: float) -> bool:
        self.ask(f"MCP_WM.Counterdrift Setpoint {float(nm)}")
        return True

    def cd_activate(self, state: bool) -> bool:
        self.ask(f"MCP_WM.Counterdrift Activate {'true' if state else 'false'}")
        return True

    def cd_get_wavelength(self) -> float:
        reply = self.ask("MCP_WM_GET_WAVELENGTH")
        return float(reply.split()[0]) if reply else 0.0

    def goto_open(self) -> bool:
        self.ask("MCP_WM_GotoPosition")
        return True

    def goto_set(self, nm: float) -> bool:
        self.ask(f"MCP_WM.GoTo Goto {float(nm)}")
        return True

    def goto_start(self) -> bool:
        self.ask("MCP_WM.GoTo Start")
        return True

    def goto_status(self) -> str:
        return self.ask("MCP_WM.GoTo status")


class MockGratingDevice:
    """Stand-in for the grating PI motion stage exposed by grating_controller.py.

    Public surface the controller uses: ``MOV(target) -> bool`` and
    ``qPOS() -> float``. Public surface the EPICS mock reads: ``sim_wn``
    (cm^-1), kept consistent with the stage position through a linear slope:

        sim_wn = initial_wn + (pos - initial_pos) * wn_per_unit

    ``wn_per_unit`` models the real grating's position->wavenumber slope. It is a
    simulation parameter only (the stepping controller does not use a slope); it
    must stay NEGATIVE so the controller's negative-slope assumption (step the
    stage up to lower the wavenumber) converges. The stage slews toward the last
    MOV target at ``slew_rate`` stage units per second for realistic settling.
    """

    def __init__(self, initialization_params: dict = {}):
        self._lock = threading.Lock()
        self._pos = float(initialization_params.get("initial_pos", 0.0))
        self._pos0 = self._pos
        self._target_pos = self._pos
        self._wn0 = float(initialization_params.get("initial_wn", 12625.0))
        # cm^-1 per stage unit (SIGNED). Negative for the real grating; see the
        # class docstring.
        self._wn_per_unit = float(initialization_params.get("wn_per_unit", -1.0))
        self._slew_rate = float(initialization_params.get("slew_rate", 50.0))
        self._last_update = time.time()
        self.noise = float(initialization_params.get("noise_level", 1e-6))
        self.sim_wn = self._wn0

    def _advance(self):
        now = time.time()
        dt = max(0.0, now - self._last_update)
        self._last_update = now
        diff = self._target_pos - self._pos
        step = self._slew_rate * dt
        if abs(diff) <= step:
            self._pos = self._target_pos
        else:
            self._pos += step if diff > 0 else -step
        self.sim_wn = self._wn0 + (self._pos - self._pos0) * self._wn_per_unit

    # ---- API mirroring GratingDevice (XML-RPC client) ----

    def MOV(self, target) -> bool:
        with self._lock:
            self._advance()
            self._target_pos = float(target)
        return True

    def qPOS(self) -> float:
        with self._lock:
            self._advance()
            return float(self._pos)

    def close(self):
        with self._lock:
            self._target_pos = self._pos


class MockEpicsClient:
    """Mocks epics.caget for the wavemeter PVs by reading the mock laser device
    (MockMatisseDevice or MockGratingDevice).

    Constructor signature matches the real ComClient so daq_system.py can
    swap them transparently.
    """

    def __init__(self, matisse_device, initialization_params: dict = {}):
        self.matisse = matisse_device
        self.noise = float(initialization_params.get("noise_level", 1e-6))

    def caget(self, pvname: str):
        if "wavenumber" in pvname:
            base = getattr(self.matisse, "sim_wn", 12625.0)
            # Tick the sim forward whenever the wavemeter is read, so even
            # idle controller iterations advance the slew dynamics.
            if hasattr(self.matisse, "_lock") and hasattr(self.matisse, "_advance"):
                with self.matisse._lock:
                    self.matisse._advance()
                    base = self.matisse.sim_wn
            return base + random.uniform(-self.noise, self.noise)
        return 0.0
