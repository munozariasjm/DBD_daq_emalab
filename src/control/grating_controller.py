"""Closed-loop wavenumber control for the grating laser.

The Matisse holds a wavelength on its own: once CounterDrift is activated its
firmware servos the laser and LaserController only has to set a setpoint and
watch the wavemeter. The grating laser has no such firmware lock. Its server
(``LASERLABCOMPUTER/grating_controller.py``, the ``laser==True`` / PI-stage
path) is a bare positioner — ``MOV(target)`` moves the grating's drive stage
and ``qPOS()`` reads it; there is no wavelength concept on that side at all.

So the DAQ closes the loop itself with the original grating "go_to" search:
read the EPICS wavemeter, and walk the stage position toward the target one
``step_fine`` at a time (with a ``step_coarse`` fallback when a fine step would
not move us), until the wavemeter has sat within ``tolerance`` for
``required_stable_samples`` consecutive reads. This grating has a *negative*
slope — moving the stage in the + direction lowers the wavenumber — so when the
wavemeter reads above target we step the position up, and vice versa.

This is the same algorithm and the same parameters the grating was scanned with
(see ``control_settings.grating`` in settings.json): tolerance 0.0001 cm^-1,
step_fine 0.0001, step_coarse 0.001. It is deliberately a small-step search, not
a PID, and there is no command clamp — the stage's own travel limits bound it.

This class mirrors LaserController's public surface (set_wavenumber /
start_counterdrift / stop_counterdrift / is_stable / get_wavenumber / stop /
update_config / tolerance / config) so Scanner and DAQSystem drive either laser
through exactly the same calls.
"""

import threading


class GratingController:
    def __init__(self, grating_device, epics_client, config: dict = {}):
        self.grating = grating_device
        self.epics = epics_client
        self.config = dict(config)

        # Control-loop parameters (defaults = the values the grating was run with).
        self.tolerance = float(self.config.get("tolerance", 0.0001))
        self.step_fine = float(self.config.get("step_fine", 0.0001))
        self.step_coarse = float(self.config.get("step_coarse", 0.001))
        self.poll_interval = float(self.config.get("poll_interval", 0.01))
        self.required_stable_samples = int(self.config.get("required_stable_samples", 4))

        self.wavechannel = int(self.config.get("wavechannel", 1))
        self.wm_pv = self.config.get("wm_pv", f"LaserLab:wavenumber_{self.wavechannel}")

        # State
        self.target_wn = 0.0
        self.is_moving = False

        # Threading
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.control_thread = None

    # ---- Public API used by GUI / DAQSystem / Scanner ----

    def set_wavenumber(self, target_wn: float):
        """Set the target and start (or re-aim) the stepping loop."""
        with self.lock:
            self.target_wn = float(target_wn)
            print(f"[Grating] set_wavenumber({self.target_wn:.6f})")
            self.stop_event.clear()
            if self.control_thread and self.control_thread.is_alive():
                # Loop already running: it reads target_wn each step and re-aims.
                return
            self.is_moving = True
            self.control_thread = threading.Thread(target=self._control_loop, daemon=True)
            self.control_thread.start()

    def start_counterdrift(self, target_wn: float):
        """Engage a wavenumber (parity with LaserController)."""
        self.set_wavenumber(target_wn)

    def stop_counterdrift(self):
        self.stop()

    def is_stable(self, tolerance=None) -> bool:
        """True when the stepping loop has settled AND the latest wavemeter read
        is in tolerance. Scanner gates event accumulation on this."""
        tol = self.tolerance if tolerance is None else float(tolerance)
        wn = self.get_wavenumber()
        with self.lock:
            target = self.target_wn
            moving = self.is_moving
        return (not moving) and abs(wn - target) < tol

    def get_wavenumber(self) -> float:
        """Single raw wavemeter read (cm^-1) on the configured channel."""
        return float(self.epics.caget(self.wm_pv))

    def stop(self):
        self.stop_event.set()
        thread = self.control_thread
        if thread and thread.is_alive():
            thread.join(timeout=max(5.0, self.poll_interval * 5))
        with self.lock:
            self.is_moving = False

    def update_config(self, new_config: dict):
        """Hot update. Safe to call while the loop is running."""
        with self.lock:
            self.config.update(new_config)
            self.tolerance = float(self.config.get("tolerance", self.tolerance))
            self.step_fine = float(self.config.get("step_fine", self.step_fine))
            self.step_coarse = float(self.config.get("step_coarse", self.step_coarse))
            self.poll_interval = float(self.config.get("poll_interval", self.poll_interval))
            self.required_stable_samples = int(
                self.config.get("required_stable_samples", self.required_stable_samples)
            )
            new_channel = int(self.config.get("wavechannel", self.wavechannel))
            if new_channel != self.wavechannel:
                self.wavechannel = new_channel
                self.wm_pv = self.config.get("wm_pv", f"LaserLab:wavenumber_{self.wavechannel}")
        print(
            f"[Grating] config updated: tol={self.tolerance}, step_fine={self.step_fine}, "
            f"step_coarse={self.step_coarse}, poll={self.poll_interval}, "
            f"stable={self.required_stable_samples}, chan={self.wavechannel}"
        )

    # ---- Internal helpers ----

    def _read_position(self) -> float:
        try:
            return float(self.grating.qPOS())
        except Exception as e:
            print(f"[Grating] qPOS failed: {e}")
            return 0.0

    # ---- Main control loop ----

    def _control_loop(self):
        with self.lock:
            target = self.target_wn
        print(f"[Grating] control loop starting (target={target:.6f})")

        wn = self.get_wavenumber()
        position = self._read_position()
        prevpos = position
        stable_samples = 0

        while not self.stop_event.is_set():
            wn = self.get_wavenumber()
            position = self._read_position()
            with self.lock:
                target = self.target_wn

            # Stability: enough consecutive in-tolerance reads -> done.
            if abs(wn - target) < self.tolerance:
                stable_samples += 1
                if stable_samples >= self.required_stable_samples:
                    break
                if self.stop_event.wait(self.poll_interval):
                    break
                continue
            stable_samples = 0

            # Negative slope: stepping the position up lowers the wavenumber.
            if wn >= target + self.tolerance:
                # Wavemeter above target -> step position up to bring it down.
                if abs((position + self.step_fine) - prevpos) > 1e-9:
                    move_cmd = position + self.step_fine
                else:
                    move_cmd = position - self.step_coarse
            else:
                # Wavemeter below target -> step position down to raise it.
                if abs((position - self.step_fine) - prevpos) > 1e-9:
                    move_cmd = position - self.step_fine
                else:
                    move_cmd = position + self.step_coarse

            try:
                if not self.grating.MOV(move_cmd):
                    print(f"[Grating] WARNING: server rejected MOV({move_cmd:.6f})")
            except Exception as e:
                print(f"[Grating] MOV failed: {e}")
                break

            print(f"[Grating] pos {position:.6f} -> {move_cmd:.6f}, WN={wn:.6f} "
                  f"(target {target:.6f}, |Δ|={abs(wn - target):.2e})")

            if self.stop_event.wait(self.poll_interval):
                break
            prevpos = position

        with self.lock:
            self.is_moving = False
        print(f"[Grating] control loop exiting (WN={wn:.6f}, target={target:.6f})")


if __name__ == "__main__":
    pass
