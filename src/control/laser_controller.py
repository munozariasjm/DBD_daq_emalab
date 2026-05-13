"""Laser stabilisation by sequencing the Matisse's built-in CounterDrift loop.

The DAQ does not run a software PID on the laser. It tells the Matisse what
wavenumber to lock to via MCP commands and verifies the lock against the
external wavemeter. The Matisse firmware does the actual servoing.

Sequence per target wavenumber:

    1. open the CounterDrift / GoTo dialogs (once per session, idempotent)
    2. if |current - target| > goto_threshold, run a MCP_WM.GoTo procedure
    3. set MCP_WM.Counterdrift Setpoint, activate it
    4. wait the appropriate settle window (fresh vs re-aim)
    5. poll the wavemeter and require `required_stable_samples` consecutive
       in-tolerance reads before declaring `is_locked`.
"""

import threading
from collections import deque

from src.utils.units import wn_to_nm_vacuum


class LaserController:
    def __init__(self, matisse_device, epics_client, axis=1, config: dict = {}):
        # `axis` is kept in the signature for compatibility with daq_system.py
        # but unused — there is no axis concept in CounterDrift mode.
        self.matisse = matisse_device
        self.epics = epics_client
        self.config = dict(config)

        # Control parameters
        self.tolerance = float(self.config.get("tolerance", 1e-5))
        self.poll_interval = float(self.config.get("poll_interval", 0.5))
        self.required_stable_samples = int(self.config.get("required_stable_samples", 4))
        self.goto_threshold = float(self.config.get("goto_threshold", 0.01))
        self.dialog_open_delay = float(self.config.get("dialog_open_delay", 0.3))
        self.activation_delay = float(self.config.get("activation_delay", 1.0))
        self.setpoint_settle = float(self.config.get("setpoint_settle", 0.5))
        self.continuous = bool(self.config.get("continuous", False))
        self.wavechannel = int(self.config.get("wavechannel", 1))
        self.wm_avg_samples = max(1, int(self.config.get("wm_averaging_samples", 5)))
        self.wm_pv = self.config.get("wm_pv", f"LaserLab:wavenumber_{self.wavechannel}")

        # State
        self._wm_buffer = deque(maxlen=self.wm_avg_samples)
        self.target_wn = 0.0
        self.is_locked = False
        self._cd_active = False
        self._dialog_opened = False
        # Pre-flight unit check (Matisse Display Unit vs wavemeter). Verified
        # once per controller lifetime — operator is assumed not to flip the
        # Matisse Commander unit setting mid-session.
        self._setup_verified = False

        # Threading
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.control_thread = None
        # Cleared by the loop when it picks up a new target via set_wavenumber.
        self._target_changed = threading.Event()

    # ---- Public API used by GUI / DAQSystem / Scanner ----

    def set_wavenumber(self, target_wn: float):
        """Set the lock target and start (or update) the control loop."""
        target_wn = float(target_wn)
        with self.lock:
            self.target_wn = target_wn
            print(f"[Laser] set_wavenumber({target_wn:.6f})")
            if self.control_thread and self.control_thread.is_alive():
                # Loop already running: ask it to re-aim.
                self._target_changed.set()
                return
            self.stop_event.clear()
            self._wm_buffer.clear()
            self.is_locked = False
            self.control_thread = threading.Thread(
                target=self._control_loop, daemon=True
            )
            self.control_thread.start()

    def start_counterdrift(self, target_wn: float):
        """Engage and hold a wavenumber indefinitely (the loop stays alive)."""
        with self.lock:
            self.continuous = True
        self.set_wavenumber(target_wn)

    def stop_counterdrift(self):
        with self.lock:
            self.continuous = False
        self.stop()

    def is_stable(self, tolerance=None) -> bool:
        """True when the most recent wavemeter read is within tolerance AND the
        control loop has registered a successful lock. Scanner uses this as the
        gate for accumulating events."""
        tol = self.tolerance if tolerance is None else float(tolerance)
        wn = self.get_wavenumber()
        with self.lock:
            target = self.target_wn
            locked = self.is_locked
        return locked and abs(wn - target) < tol

    def get_wavenumber(self) -> float:
        """Single raw wavemeter read (cm^-1) on the configured channel."""
        return float(self.epics.caget(self.wm_pv))

    def stop(self):
        self.stop_event.set()
        thread = self.control_thread
        if thread and thread.is_alive():
            thread.join(timeout=max(5.0, self.activation_delay * 3))
        # Best-effort: release the Matisse's CounterDrift on shutdown.
        if self._cd_active:
            try:
                self.matisse.cd_activate(False)
            except Exception as e:
                print(f"[Laser] cd_activate(False) on stop failed: {e}")
            self._cd_active = False
        with self.lock:
            self.is_locked = False

    def update_config(self, new_config: dict):
        """Hot update. Safe to call while the loop is running."""
        with self.lock:
            self.config.update(new_config)
            self.tolerance = float(self.config.get("tolerance", self.tolerance))
            self.poll_interval = float(self.config.get("poll_interval", self.poll_interval))
            self.required_stable_samples = int(
                self.config.get("required_stable_samples", self.required_stable_samples)
            )
            self.goto_threshold = float(self.config.get("goto_threshold", self.goto_threshold))
            self.dialog_open_delay = float(self.config.get("dialog_open_delay", self.dialog_open_delay))
            self.activation_delay = float(self.config.get("activation_delay", self.activation_delay))
            self.setpoint_settle = float(self.config.get("setpoint_settle", self.setpoint_settle))
            self.continuous = bool(self.config.get("continuous", self.continuous))
            new_channel = int(self.config.get("wavechannel", self.wavechannel))
            if new_channel != self.wavechannel:
                self.wavechannel = new_channel
                self.wm_pv = self.config.get("wm_pv", f"LaserLab:wavenumber_{self.wavechannel}")
                self._wm_buffer.clear()
            new_avg = max(1, int(self.config.get("wm_averaging_samples", self.wm_avg_samples)))
            if new_avg != self.wm_avg_samples:
                self.wm_avg_samples = new_avg
                self._wm_buffer = deque(maxlen=new_avg)
        print(
            f"[Laser] config updated: tol={self.tolerance}, poll={self.poll_interval}, "
            f"goto_thr={self.goto_threshold}, settle=({self.dialog_open_delay},"
            f"{self.activation_delay},{self.setpoint_settle}), cont={self.continuous}"
        )

    # ---- Internal helpers ----

    def _averaged_wavemeter(self) -> float:
        reading = self.get_wavenumber()
        self._wm_buffer.append(reading)
        return sum(self._wm_buffer) / len(self._wm_buffer)

    def _sleep(self, seconds: float) -> bool:
        """Sleep, but return early if stop_event fires. Returns True on stop."""
        if seconds <= 0:
            return self.stop_event.is_set()
        return self.stop_event.wait(seconds)

    def _verify_setup(self) -> bool:
        """One-time pre-flight: do the Matisse and the EPICS wavemeter agree
        on the current laser wavelength?

        `MCP_WM_GET_WAVELENGTH` always returns nm vacuum (docs p. 14); the
        EPICS PV returns cm⁻¹. If the values disagree, this almost always
        means one of:

          1. Matisse Commander Display Unit / CounterDrift Unit is cm⁻¹
             instead of nm — every setpoint we send will be interpreted in
             the wrong unit and the laser will be driven catastrophically
             far from target. Detected when the Matisse reading numerically
             matches the wavemeter's cm⁻¹ value (the Matisse is reporting
             its own readout in the wrong unit).
          2. Wrong wavemeter channel / PV — the EPICS reading isn't this
             laser at all. Detected when the two readings don't match in
             either interpretation.
          3. Matisse or wavemeter offline — read returned 0 or non-finite.

        Returns True if everything looks sane and the controller may engage.
        On failure, prints a loud banner explaining what to fix and returns
        False. The control loop then refuses to activate CounterDrift."""
        try:
            matisse_reading = float(self.matisse.cd_get_wavelength())
        except Exception as e:
            print(f"[Laser] Pre-flight unit check: cd_get_wavelength raised: {e}")
            return False
        wn = self.get_wavenumber()
        if matisse_reading <= 0 or wn <= 0:
            print(
                f"[Laser] Pre-flight unit check: zero/negative reading "
                f"(Matisse={matisse_reading}, EPICS={wn}). Refusing to engage."
            )
            return False

        expected_nm = 1e7 / wn  # what cd_get_wavelength should be, in nm

        if abs(matisse_reading - expected_nm) < 0.5:
            print(
                f"[Laser] Pre-flight unit check OK: Matisse={matisse_reading:.4f} nm, "
                f"EPICS={wn:.6f} cm^-1 (={expected_nm:.4f} nm)"
            )
            return True

        # Catastrophic case: Matisse's "wavelength in nm" reading is actually
        # numerically the wavenumber. Display Unit is set to cm⁻¹.
        if abs(matisse_reading - wn) < 1.0:
            print("[Laser] ============= MATISSE UNIT MISMATCH =============")
            print(f"[Laser] cd_get_wavelength returned: {matisse_reading}")
            print(f"[Laser] EPICS wavemeter returned : {wn:.6f} cm^-1")
            print(f"[Laser] Expected (in nm)         : {expected_nm:.4f}")
            print("[Laser] The Matisse reading matches the wavemeter in cm^-1,")
            print("[Laser] not in nm. Display Unit / CounterDrift Unit are NOT nm.")
            print("[Laser] In Matisse Commander, set BOTH of these to nm:")
            print("[Laser]   - Display Options -> Position Display Mode")
            print("[Laser]   - CounterDrift dialog -> Unit")
            print("[Laser] Refusing to engage CounterDrift.")
            print("[Laser] =================================================")
            return False

        # Neither interpretation matches — wavemeter channel/PV is wrong or
        # the EPICS reading isn't this laser.
        print("[Laser] ========== MATISSE/WAVEMETER DISAGREE ===========")
        print(f"[Laser] cd_get_wavelength : {matisse_reading} (interpreted as nm)")
        print(f"[Laser] EPICS wavemeter   : {wn:.6f} cm^-1 (={expected_nm:.4f} nm)")
        print(f"[Laser] |Matisse - EPICS_nm| = {abs(matisse_reading - expected_nm):.4f} nm")
        print(f"[Laser] These are not consistent with the same laser.")
        print(f"[Laser] Check wavemeter channel (current: {self.wavechannel}) and the")
        print(f"[Laser] EPICS PV path. Refusing to engage CounterDrift.")
        print("[Laser] =================================================")
        return False

    def _ensure_dialogs(self):
        if self._dialog_opened:
            return
        try:
            if not self.matisse.cd_open():
                print("[Laser] WARNING: server rejected cd_open — CounterDrift dialog may not be available")
            if not self.matisse.goto_open():
                print("[Laser] WARNING: server rejected goto_open — GoTo dialog may not be available")
        except Exception as e:
            print(f"[Laser] dialog open failed: {e}")
            return
        self._sleep(self.dialog_open_delay)
        self._dialog_opened = True

    def _run_goto(self, target_nm: float) -> bool:
        """Execute the MCP_WM.GoTo procedure. Returns True if it ran to STOP,
        False if stop_event interrupted us."""
        if self._cd_active:
            try:
                self.matisse.cd_activate(False)
            except Exception as e:
                print(f"[Laser] cd_activate(False) before GoTo failed: {e}")
            self._cd_active = False
        try:
            if not self.matisse.goto_set(target_nm):
                print(f"[Laser] WARNING: server rejected goto_set({target_nm})")
            if not self.matisse.goto_start():
                print("[Laser] WARNING: server rejected goto_start — coarse positioning will not run")
                return False
        except Exception as e:
            print(f"[Laser] goto_set/start failed: {e}")
            return False
        while not self.stop_event.is_set():
            try:
                status = self.matisse.goto_status()
            except Exception as e:
                print(f"[Laser] goto_status failed: {e}")
                return False
            if status.upper() == "STOP":
                return True
            if self._sleep(self.poll_interval):
                return False
        return False

    def _engage(self, target_nm: float, fresh: bool):
        """Send setpoint, activate if needed, wait the appropriate settle."""
        try:
            if not self.matisse.cd_setpoint(target_nm):
                print(f"[Laser] WARNING: server rejected cd_setpoint({target_nm})")
            if not self._cd_active:
                if not self.matisse.cd_activate(True):
                    print("[Laser] WARNING: server rejected cd_activate(True) — lock will not engage")
                self._cd_active = True
                self._sleep(self.activation_delay)
            else:
                self._sleep(self.setpoint_settle)
        except Exception as e:
            print(f"[Laser] _engage failed: {e}")

    # ---- Main control loop ----

    def _control_loop(self):
        print(f"[Laser] control loop starting (target={self.target_wn:.6f})")
        self._ensure_dialogs()

        # Pre-flight: confirm Matisse Display Unit / CounterDrift Unit are
        # set to nm. Skipped on subsequent loop spawns once verified.
        if not self._setup_verified:
            if not self._verify_setup():
                print("[Laser] Pre-flight unit check FAILED — refusing to engage CounterDrift.")
                return
            self._setup_verified = True

        # Outer aim/re-aim loop: each iteration positions and verifies a lock
        # for the current target. We come back here whenever set_wavenumber()
        # nudges _target_changed.
        while not self.stop_event.is_set():
            with self.lock:
                target_wn = self.target_wn
            target_nm = wn_to_nm_vacuum(target_wn)

            # Snapshot current wavemeter to decide coarse vs fine
            current_wn = self._averaged_wavemeter()
            needs_goto = abs(current_wn - target_wn) > self.goto_threshold

            if needs_goto:
                print(f"[Laser] GoTo {target_nm:.6f} nm (delta={current_wn - target_wn:+.4f} cm^-1)")
                if not self._run_goto(target_nm):
                    break  # interrupted

            # Engage CounterDrift on the setpoint
            fresh = not self._cd_active
            print(
                f"[Laser] {'activate' if fresh else 're-aim'} CounterDrift "
                f"at {target_nm:.6f} nm ({target_wn:.6f} cm^-1)"
            )
            self._engage(target_nm, fresh=fresh)
            self._target_changed.clear()
            with self.lock:
                self.is_locked = False
                self._wm_buffer.clear()

            # Verify lock by wavemeter
            stable_samples = 0
            locked_once = False
            while not self.stop_event.is_set():
                if self._target_changed.is_set():
                    break  # re-aim from the outer loop
                wn = self._averaged_wavemeter()
                with self.lock:
                    cur_target = self.target_wn
                if abs(wn - cur_target) < self.tolerance:
                    stable_samples += 1
                    if stable_samples >= self.required_stable_samples:
                        with self.lock:
                            self.is_locked = True
                        locked_once = True
                        if not self.continuous:
                            break
                        if self._sleep(self.poll_interval):
                            break
                        continue
                else:
                    stable_samples = 0
                    if locked_once:
                        with self.lock:
                            self.is_locked = False
                if self._sleep(self.poll_interval):
                    break

            # Did we exit because a new target arrived?
            if self._target_changed.is_set():
                continue
            # Otherwise we either locked (non-continuous) or were stopped
            break

        print(f"[Laser] control loop exiting (locked={self.is_locked})")


if __name__ == "__main__":
    pass
