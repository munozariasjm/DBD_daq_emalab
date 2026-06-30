"""Closed-loop wavenumber control for the grating laser.

The Matisse holds a wavelength on its own: once CounterDrift is activated its
firmware servos the laser and LaserController only has to set a setpoint and
watch the wavemeter. The grating laser has no such firmware lock. Its server
(``LASERLABCOMPUTER/grating_controller.py``) is a bare positioner — it exposes
only ``MOV(axis, target)`` (move the PI stage) and ``qPOS(axis)`` (read it);
there is no wavelength concept on that side at all. The axis is a property of
the stage, so it is owned by ``GratingDevice``; this controller just calls
``MOV``/``qPOS`` and never sees an axis number.

So the DAQ closes the loop itself. It reads the EPICS wavemeter, computes the
wavenumber error, and nudges the stage via ``MOV`` until the measured
wavenumber sits within tolerance of the target — the software equivalent of
what CounterDrift does in firmware for the Matisse.

The only rig-specific number this needs is the calibration ``wn_per_unit``:
how many cm^-1 the wavenumber changes per one stage position unit, *including
sign*. It is a config knob (set/tuned on the bench), not hard-coded. Three
independent guards keep a wrong sign or a bad calibration from driving the
stage into a hard stop:

  * ``step_limit`` — max stage motion commanded per poll,
  * ``pos_min`` / ``pos_max`` — hard travel clamp on the commanded position,
  * a divergence / out-of-range runaway abort that latches (mirrors the
    Matisse runaway guard) when the error grows instead of shrinking, or the
    commanded position is pinned at a travel limit while still off target.

This class deliberately mirrors LaserController's public surface (set_wavenumber
/ start_counterdrift / stop_counterdrift / is_stable / get_wavenumber / stop /
update_config / tolerance / config) so Scanner and DAQSystem drive either laser
through exactly the same calls.
"""

import threading
import time
from collections import deque


class GratingPID:
    """Discrete PI servo: wavenumber error (cm^-1) -> stage step (units).

    Output is an *incremental* stage move applied on top of the commanded
    position each poll, so the laser converges geometrically rather than
    jumping. The ``wn_per_unit`` calibration converts the wavenumber-domain
    PID output into stage units; ``step_limit`` clamps a single move and
    drives integral anti-windup.

    With ki=0 (the default) this is a damped proportional feed-forward:
    ``step = kp * error / wn_per_unit`` clamped to step_limit. Adding ki
    removes residual steady-state error from calibration drift. The PID owns
    these gains; the controller does not keep its own copies.
    """

    def __init__(self, kp, ki, wn_per_unit, step_limit):
        self.kp = float(kp)
        self.ki = float(ki)
        self.wn_per_unit = float(wn_per_unit)
        self.step_limit = float(step_limit)
        self.reset()

    def reset(self):
        self._integral = 0.0

    def compute(self, error: float, dt: float) -> float:
        """Return the stage position increment (units) for this poll."""
        if dt <= 0 or self.wn_per_unit == 0:
            return 0.0
        units_per_wn = 1.0 / self.wn_per_unit

        # Integral accumulated before the clamp so anti-windup can undo it.
        self._integral += error * dt
        wn_output = self.kp * error + self.ki * self._integral
        step = wn_output * units_per_wn

        if step > self.step_limit:
            step = self.step_limit
            self._integral -= error * dt  # anti-windup: don't accumulate while saturated
        elif step < -self.step_limit:
            step = -self.step_limit
            self._integral -= error * dt
        return step


class GratingController:
    def __init__(self, grating_device, epics_client, config: dict = {}):
        self.grating = grating_device
        self.epics = epics_client
        self.config = dict(config)

        # Servo gains live on the PID (single source of truth). The only
        # rig-specific number is wn_per_unit: cm^-1 per stage unit, SIGNED. A
        # wrong magnitude only slows convergence; a wrong sign is caught by the
        # runaway guard below.
        self._pid = GratingPID(
            kp=float(self.config.get("kp", 0.5)),
            ki=float(self.config.get("ki", 0.0)),
            wn_per_unit=float(self.config.get("wn_per_unit", -1.0)),
            step_limit=float(self.config.get("step_limit", 5.0)),
        )

        # Lock parameters
        self.tolerance = float(self.config.get("tolerance", 1e-4))
        self.poll_interval = float(self.config.get("poll_interval", 0.3))
        self.required_stable_samples = int(self.config.get("required_stable_samples", 4))
        # Hard travel limits of the stage (stage units). Defaults are wide; set
        # these to the real mechanical limits to protect the hardware.
        self.pos_min = float(self.config.get("pos_min", -1e9))
        self.pos_max = float(self.config.get("pos_max", 1e9))

        # Runaway guard: abort if the error keeps growing (wrong sign / dead
        # feedback) or the commanded position is pinned at a travel limit while
        # still off target, for this many consecutive polls.
        self.runaway_samples = int(self.config.get("runaway_samples", 5))
        # Margin (cm^-1) by which the error must grow to count as diverging, so
        # wavemeter noise alone never trips the guard.
        self.runaway_margin = float(self.config.get("runaway_margin", 1e-4))

        # Default to holding the lock: the grating has no firmware hold, so the
        # servo must keep running to reject drift while a bin accumulates.
        self.continuous = bool(self.config.get("continuous", True))

        self.wavechannel = int(self.config.get("wavechannel", 1))
        self.wm_avg_samples = max(1, int(self.config.get("wm_averaging_samples", 5)))
        self.wm_pv = self.config.get("wm_pv", f"LaserLab:wavenumber_{self.wavechannel}")

        # State
        self._wm_buffer = deque(maxlen=self.wm_avg_samples)
        self.target_wn = 0.0
        self.is_locked = False
        # Commanded stage position (units). Seeded from qPOS on first engage;
        # tracked internally thereafter since MOV is absolute.
        self._commanded_pos = None
        # Latched True after a runaway abort so later bins refuse to re-engage.
        self._aborted = False

        # Threading
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.control_thread = None
        self._target_changed = threading.Event()

    # ---- Public API used by GUI / DAQSystem / Scanner ----

    def set_wavenumber(self, target_wn: float):
        """Set the lock target and start (or re-aim) the servo loop."""
        target_wn = float(target_wn)
        with self.lock:
            self.target_wn = target_wn
            print(f"[Grating] set_wavenumber({target_wn:.6f})")
            if self.control_thread and self.control_thread.is_alive():
                self._target_changed.set()
                return
            self.stop_event.clear()
            self._wm_buffer.clear()
            self.is_locked = False
            self.control_thread = threading.Thread(target=self._control_loop, daemon=True)
            self.control_thread.start()

    def start_counterdrift(self, target_wn: float):
        """Engage and hold a wavenumber indefinitely (parity with LaserController)."""
        with self.lock:
            self.continuous = True
        self.set_wavenumber(target_wn)

    def stop_counterdrift(self):
        with self.lock:
            self.continuous = False
        self.stop()

    def is_stable(self, tolerance=None) -> bool:
        """True when the loop has locked AND the latest wavemeter read is in
        tolerance. Scanner gates event accumulation on this."""
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
            thread.join(timeout=max(5.0, self.poll_interval * 5))
        with self.lock:
            self.is_locked = False

    def update_config(self, new_config: dict):
        """Hot update. Safe to call while the loop is running."""
        with self.lock:
            self.config.update(new_config)
            # Gains write straight to the PID (its the single source of truth).
            self._pid.kp = float(self.config.get("kp", self._pid.kp))
            self._pid.ki = float(self.config.get("ki", self._pid.ki))
            self._pid.wn_per_unit = float(self.config.get("wn_per_unit", self._pid.wn_per_unit))
            self._pid.step_limit = float(self.config.get("step_limit", self._pid.step_limit))
            self.tolerance = float(self.config.get("tolerance", self.tolerance))
            self.poll_interval = float(self.config.get("poll_interval", self.poll_interval))
            self.required_stable_samples = int(
                self.config.get("required_stable_samples", self.required_stable_samples)
            )
            self.pos_min = float(self.config.get("pos_min", self.pos_min))
            self.pos_max = float(self.config.get("pos_max", self.pos_max))
            self.runaway_samples = int(self.config.get("runaway_samples", self.runaway_samples))
            self.runaway_margin = float(self.config.get("runaway_margin", self.runaway_margin))
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
            f"[Grating] config updated: tol={self.tolerance}, poll={self.poll_interval}, "
            f"wn_per_unit={self._pid.wn_per_unit}, kp={self._pid.kp}, ki={self._pid.ki}, "
            f"step_limit={self._pid.step_limit}, pos=[{self.pos_min},{self.pos_max}], "
            f"cont={self.continuous}"
        )

    # ---- Internal helpers ----

    def _averaged_wavemeter(self) -> float:
        reading = self.get_wavenumber()
        self._wm_buffer.append(reading)
        return sum(self._wm_buffer) / len(self._wm_buffer)

    def _sleep(self, seconds: float) -> bool:
        """Sleep, returning True early if stop_event fires."""
        if seconds <= 0:
            return self.stop_event.is_set()
        return self.stop_event.wait(seconds)

    def _seed_position(self):
        """Read the current stage position once so commanded moves are absolute
        and start from where the stage actually is."""
        if self._commanded_pos is not None:
            return
        try:
            self._commanded_pos = float(self.grating.qPOS())
            print(f"[Grating] seeded stage position at {self._commanded_pos:.4f}")
        except Exception as e:
            self._commanded_pos = 0.0
            print(f"[Grating] qPOS failed ({e}); seeding commanded position at 0.0")

    def _move(self, new_pos: float) -> bool:
        """Clamp to travel limits and issue an absolute MOV. Returns True if the
        commanded position was pinned at a travel limit (caller's out-of-range
        signal)."""
        clamped = max(self.pos_min, min(self.pos_max, new_pos))
        at_limit = clamped != new_pos
        self._commanded_pos = clamped
        try:
            if not self.grating.MOV(clamped):
                print(f"[Grating] WARNING: server rejected MOV({clamped:.4f})")
        except Exception as e:
            print(f"[Grating] MOV failed: {e}")
        return at_limit

    def _handle_runaway(self, wn: float, target: float, reason: str):
        delta = abs(wn - target)
        print("[Grating] ============== SERVO RUNAWAY ==============")
        print(f"[Grating] Wavemeter {wn:.6f} cm^-1 is {delta:.4f} from target {target:.6f}.")
        print(f"[Grating] Reason: {reason}")
        print("[Grating] Most likely 'wn_per_unit' has the WRONG SIGN, the wavemeter")
        print("[Grating] channel is not this laser, or the stage is out of travel.")
        print("[Grating] Disengaging and latching aborted. Fix the calibration and")
        print("[Grating] restart the DAQ.")
        print("[Grating] ===========================================")
        self._aborted = True
        with self.lock:
            self.is_locked = False
        self.stop_event.set()

    # ---- Main control loop ----

    def _control_loop(self):
        print(f"[Grating] control loop starting (target={self.target_wn:.6f})")
        if self._aborted:
            print("[Grating] ABORTED state from a prior runaway — not engaging. "
                  "Fix 'wn_per_unit' / wavemeter channel and restart the DAQ.")
            return

        self._seed_position()

        # Outer aim/re-aim loop: re-entered whenever set_wavenumber() nudges
        # _target_changed.
        while not self.stop_event.is_set():
            with self.lock:
                target_wn = self.target_wn
            self._pid.reset()
            self._target_changed.clear()
            with self.lock:
                self.is_locked = False
                self._wm_buffer.clear()

            print(f"[Grating] servo to {target_wn:.6f} cm^-1 "
                  f"(wn_per_unit={self._pid.wn_per_unit}, kp={self._pid.kp})")

            stable_samples = 0
            diverge_count = 0
            limit_count = 0
            prev_abs_error = None
            printed_locked = False
            last_t = time.time()

            while not self.stop_event.is_set():
                if self._target_changed.is_set():
                    break  # re-aim from the outer loop

                wn = self._averaged_wavemeter()
                with self.lock:
                    cur_target = self.target_wn
                error = cur_target - wn
                abs_error = abs(error)

                now = time.time()
                dt = now - last_t
                last_t = now

                if abs_error < self.tolerance:
                    stable_samples += 1
                    diverge_count = 0
                    limit_count = 0
                    prev_abs_error = abs_error
                    if stable_samples >= self.required_stable_samples:
                        with self.lock:
                            self.is_locked = True
                        if not printed_locked:
                            print(f"[Grating] LOCK ACQUIRED at {wn:.6f} cm^-1 "
                                  f"(target {cur_target:.6f}, |Δ|={abs_error:.2e})")
                            printed_locked = True
                        if not self.continuous:
                            break
                        if self._sleep(self.poll_interval):
                            break
                        continue
                else:
                    if printed_locked:
                        with self.lock:
                            self.is_locked = False
                        print(f"[Grating] LOCK LOST at {wn:.6f} cm^-1 "
                              f"(target {cur_target:.6f}, |Δ|={abs_error:.2e})")
                        printed_locked = False
                    stable_samples = 0

                    # Runaway: error growing instead of shrinking => wrong sign /
                    # dead feedback. prev_abs_error is only set after a move, so
                    # this measures the response to our own correction.
                    if prev_abs_error is not None and abs_error > prev_abs_error + self.runaway_margin:
                        diverge_count += 1
                        if diverge_count >= self.runaway_samples:
                            self._handle_runaway(wn, cur_target, "error diverging after corrective moves")
                            return
                    else:
                        diverge_count = 0

                    step = self._pid.compute(error, dt)
                    at_limit = self._move(self._commanded_pos + step)
                    prev_abs_error = abs_error

                    # Out of travel while still off target.
                    if at_limit:
                        limit_count += 1
                        if limit_count >= self.runaway_samples:
                            self._handle_runaway(wn, cur_target, "commanded position pinned at travel limit")
                            return
                    else:
                        limit_count = 0

                if self._sleep(self.poll_interval):
                    break

            if self._target_changed.is_set():
                continue
            break

        print(f"[Grating] control loop exiting (locked={self.is_locked})")


if __name__ == "__main__":
    pass
