import time
import threading
from collections import deque
from src.simulation.hardware_mocks import MockPIGCSDevice, MockEpicsClient
from src.control.pid import PIDController
from src.devices.laser import LaserCommError

class LaserController:
    """
    Encapsulates the logic from the 'go_to' script to control the Laser
    via a PI Stage and a Wavemeter (EPICS).

    Supports two controller modes: 'pid' and 'bangbang'.
    Supports counterdrift mode: loop keeps running after reaching target.
    """
    def __init__(self, pi_device, epics_client, axis=1, config: dict = {}):
        self.device = pi_device
        self.epics = epics_client
        self.axis = axis
        self.config = config

        # Control Loop Parameters
        self.tolerance = self.config.get("tolerance", 0.01)
        self.step_fine = self.config.get("step_fine", 0.0001)
        self.step_coarse = self.config.get("step_coarse", 0.05)
        self.poll_interval = self.config.get("poll_interval", 0.1)
        self.coarse_approach_thresh = self.config.get("coarse_approach_threshold", 1.0)
        self.required_stable_samples = self.config.get("required_stable_samples", 4)

        # Controller mode and voltage limits
        self.controller_mode = self.config.get("controller_mode", "pid")
        self.voltage_min = self.config.get("voltage_min", 0.0)
        self.voltage_max = self.config.get("voltage_max", 0.7)
        self.max_voltage_step = self.config.get("max_voltage_step", 0.05)

        # PID controller
        pid_config = self.config.get("pid", {})
        pid_mode = pid_config.get("mode", "positional")
        self.pid = PIDController(
            kp=pid_config.get("kp", -0.1),
            ki=pid_config.get("ki", -0.05),
            kd=pid_config.get("kd", -0.01),
            d_filter_coeff=pid_config.get("d_filter_coeff", 0.1),
            output_min=self.voltage_min,
            output_max=self.voltage_max,
            mode=pid_mode,
        )

        # PID enabled (False = external laser control, no MOV commands)
        self.pid_enabled = self.config.get("pid_enabled", True)

        # Counterdrift mode
        self.counterdrift_mode = self.config.get("counterdrift_mode", False)

        # Auto-reset settings
        self.auto_reset_enabled = self.config.get("auto_reset_enabled", False)
        self.auto_reset_margin = self.config.get("auto_reset_margin", 0.05)
        self.auto_reset_target = self.config.get("auto_reset_target", 0.35)

        # Wavemeter averaging
        wm_samples = self.config.get("wm_averaging_samples", 1)
        self._wm_buffer = deque(maxlen=max(1, wm_samples))

        self.target_wn = 0.0
        self.current_wn = 0.0
        self.is_moving = False
        self.voltage_limited = False
        self._prev_voltage = 0.0
        self.comm_error = None  # Set to error message string on communication failure

        # Threading for the control loop
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.control_thread = None

    def update_config(self, config: dict):
        """
        Updates the control loop parameters at runtime.
        """
        with self.lock:
            self.config.update(config)
            self.tolerance = self.config.get("tolerance", 0.01)
            self.step_fine = self.config.get("step_fine", 0.0001)
            self.step_coarse = self.config.get("step_coarse", 0.05)
            self.poll_interval = self.config.get("poll_interval", 0.1)
            self.coarse_approach_thresh = self.config.get("coarse_approach_threshold", 1.0)
            self.required_stable_samples = self.config.get("required_stable_samples", 4)

            self.controller_mode = self.config.get("controller_mode", self.controller_mode)
            self.voltage_min = self.config.get("voltage_min", self.voltage_min)
            self.voltage_max = self.config.get("voltage_max", self.voltage_max)
            self.max_voltage_step = self.config.get("max_voltage_step", 0.05)

            # PID enabled
            self.pid_enabled = self.config.get("pid_enabled", self.pid_enabled)

            # Counterdrift & auto-reset
            self.counterdrift_mode = self.config.get("counterdrift_mode", self.counterdrift_mode)
            self.auto_reset_enabled = self.config.get("auto_reset_enabled", self.auto_reset_enabled)
            self.auto_reset_margin = self.config.get("auto_reset_margin", self.auto_reset_margin)
            self.auto_reset_target = self.config.get("auto_reset_target", self.auto_reset_target)

            # Wavemeter averaging
            wm_samples = self.config.get("wm_averaging_samples", self._wm_buffer.maxlen)
            if wm_samples != self._wm_buffer.maxlen:
                self._wm_buffer = deque(maxlen=max(1, wm_samples))

            # Update PID limits
            self.pid.output_min = self.voltage_min
            self.pid.output_max = self.voltage_max

            pid_config = self.config.get("pid", {})
            if pid_config:
                self.pid.update_gains(
                    kp=pid_config.get("kp"),
                    ki=pid_config.get("ki"),
                    kd=pid_config.get("kd"),
                    d_filter_coeff=pid_config.get("d_filter_coeff"),
                )
                if "mode" in pid_config:
                    self.pid.mode = pid_config["mode"]

            print(f"[LaserController] Config updated: mode={self.controller_mode}, "
                  f"tol={self.tolerance}, poll={self.poll_interval}, "
                  f"pid_enabled={self.pid_enabled}, counterdrift={self.counterdrift_mode}")

    def set_wavenumber(self, target_wn):
        """
        Starts the background control loop to reach target_wn.
        If loop is already running, updates the target with a soft PID reset
        (keeps accumulated output, clears derivative state).
        If pid_enabled is False, just records the target (external GUI controls laser).
        Raises LaserCommError if communication with the laser server fails.
        """
        with self.lock:
            self.target_wn = target_wn
            self.voltage_limited = False
            self.comm_error = None

            print(f"[LaserController] set_wavenumber({target_wn:.6f}) called "
                  f"[pid_enabled={self.pid_enabled}]")

            if not self.pid_enabled:
                print(f"[LaserController] PID disabled — skipping control loop")
                self.is_moving = False
                return

            if self.control_thread and self.control_thread.is_alive():
                # Loop already running — reset PID with bumpless transfer
                current_voltage = self._get_voltage()
                print(f"[LaserController] Loop running, soft-reset PID at V={current_voltage:.5f}")
                self.pid.reset(initial_output=current_voltage)
            else:
                # Start new loop
                self.stop_event.clear()
                self._wm_buffer.clear()
                # Bumpless transfer: initialize PID at current piezo voltage
                current_voltage = self._get_voltage()
                print(f"[LaserController] Starting new loop, current piezo V={current_voltage:.5f}")
                self.pid.reset(initial_output=current_voltage)
                self.is_moving = True
                self.control_thread = threading.Thread(target=self._control_loop, daemon=True)
                self.control_thread.start()

    def start_counterdrift(self, target_wn):
        """Start counterdrift mode: loop runs continuously, correcting drift.
        If pid_enabled is False, just sets target and counterdrift flag."""
        with self.lock:
            self.counterdrift_mode = True
        self.set_wavenumber(target_wn)

    def stop_counterdrift(self):
        """Stop counterdrift and the control loop."""
        with self.lock:
            self.counterdrift_mode = False
        self.stop()

    def get_wavenumber(self):
        """
        Returns the current wavenumber from EPICS.
        """
        return float(self.epics.caget('LaserLab:wavenumber_1'))

    def _get_averaged_wavenumber(self):
        """Read wavemeter and return rolling average."""
        reading = self.get_wavenumber()
        self._wm_buffer.append(reading)
        return sum(self._wm_buffer) / len(self._wm_buffer)

    def _get_voltage(self):
        """Helper to safely extract voltage from either a local dict or a remote float."""
        pos = self.device.qPOS(self.axis)
        return pos if isinstance(pos, float) else pos[self.axis]

    def is_stable(self, tolerance=None):
        """
        Returns True if current WN is within tolerance of Target WN.
        If pid_enabled is False or counterdrift mode: wavemeter reading only.
        Otherwise: also requires control loop to have finished (not is_moving).
        """
        if tolerance is None:
             tolerance = self.tolerance

        wn = self.get_wavenumber()
        if not self.pid_enabled or self.counterdrift_mode:
            return abs(wn - self.target_wn) < tolerance
        return abs(wn - self.target_wn) < tolerance and not self.is_moving

    def stop(self):
        self.stop_event.set()
        if self.control_thread:
            self.control_thread.join()

    def _compute_bangbang(self, current_wn, current_voltage):
        """Compute next voltage using bang-bang (coarse/fine step) logic."""
        step_fine = self.step_fine
        step_coarse = self.step_coarse
        voltage_cmd = 0.0

        if current_wn >= self.target_wn + self.tolerance:
            if abs((current_voltage - step_fine) - self._prev_voltage) > 1e-9:
                voltage_cmd = current_voltage + step_fine
            else:
                voltage_cmd = current_voltage - step_coarse
        else:
            if abs((current_voltage + step_fine) - self._prev_voltage) > 1e-9:
                voltage_cmd = current_voltage - step_fine
            else:
                voltage_cmd = current_voltage + step_coarse

        return voltage_cmd

    def _compute_pid(self, current_wn, dt):
        """Compute next voltage using PID controller with real elapsed time."""
        return self.pid.compute(self.target_wn, current_wn, dt)

    def _clamp_voltage(self, voltage):
        """Clamp voltage to configured limits."""
        return max(self.voltage_min, min(self.voltage_max, voltage))

    def _perform_auto_reset(self):
        """
        Ramp piezo back to midpoint when near voltage limits.
        Ramps in max_voltage_step increments to avoid losing laser lock.
        Returns True if a reset was performed.
        """
        voltage = self._get_voltage()

        near_min = voltage < (self.voltage_min + self.auto_reset_margin)
        near_max = voltage > (self.voltage_max - self.auto_reset_margin)

        if not (near_min or near_max):
            return False

        print(f"[LaserController] Auto-reset: piezo at {voltage:.4f}V, "
              f"ramping to {self.auto_reset_target:.4f}V")

        target_v = self.auto_reset_target
        while not self.stop_event.is_set():
            voltage = self._get_voltage()
            diff = target_v - voltage
            if abs(diff) < 0.001:
                break

            step = min(self.max_voltage_step, abs(diff))
            next_v = voltage + (step if diff > 0 else -step)
            next_v = self._clamp_voltage(next_v)
            self.device.MOV(self.axis, next_v)
            # Sleep between steps for network latency (XML-RPC to LASERLABCOMPUTER)
            time.sleep(max(self.poll_interval, 0.05))

        # Re-initialize PID at new position
        self.pid.reset(initial_output=self.auto_reset_target)
        self._wm_buffer.clear()
        print(f"[LaserController] Auto-reset complete at {self.auto_reset_target:.4f}V")
        return True

    def _control_loop(self):
        """
        Main control loop dispatching to PID or bang-bang strategy.
        In counterdrift mode, loop continues running after reaching stability.
        Sets self.comm_error and stops on communication failure.
        """
        print(f"[LaserController] Starting control loop for Target {self.target_wn} "
              f"(mode={self.controller_mode}, counterdrift={self.counterdrift_mode})")

        try:
            self._run_control_loop()
        except LaserCommError as e:
            print(f"[LaserController] COMMUNICATION ERROR — loop stopped: {e}")
            self.comm_error = str(e)
        finally:
            self.is_moving = False

    def _run_control_loop(self):
        wn = self._get_averaged_wavenumber()
        voltage = self._get_voltage()
        self._prev_voltage = voltage

        stable_samples = 0
        REQUIRED_STABLE_SAMPLES = self.required_stable_samples
        last_time = time.time()

        while not self.stop_event.is_set():
            wn = self._get_averaged_wavenumber()
            voltage = self._get_voltage()

            # Compute real elapsed time
            now = time.time()
            dt = now - last_time
            last_time = now

            # Check stability
            if abs(wn - self.target_wn) < self.tolerance:
                stable_samples += 1
                if stable_samples >= REQUIRED_STABLE_SAMPLES:
                    if self.counterdrift_mode:
                        # Stay running, just sleep and continue correcting
                        self.stop_event.wait(self.poll_interval)
                        continue
                    else:
                        break

                self.stop_event.wait(self.poll_interval)
                continue
            else:
                stable_samples = 0

            # Auto-reset if near piezo voltage limits
            if self.auto_reset_enabled and self.controller_mode == "pid":
                if self._perform_auto_reset():
                    last_time = time.time()
                    continue

            # Dispatch to controller strategy
            if self.controller_mode == "pid":
                voltage_cmd = self._compute_pid(wn, dt)
            else:
                voltage_cmd = self._compute_bangbang(wn, voltage)

            # 1. Clamp voltage to hardware limits (0.0 - 0.7V)
            clamped = self._clamp_voltage(voltage_cmd)

            # 2. Apply step size limit (delta <= max_voltage_step) relative to CURRENT voltage
            delta = clamped - voltage
            if abs(delta) > self.max_voltage_step:
                clamped = voltage + (self.max_voltage_step if delta > 0 else -self.max_voltage_step)
                self.voltage_limited = True
            elif abs(clamped - voltage_cmd) > 1e-9:
                self.voltage_limited = True
            else:
                self.voltage_limited = False

            voltage_cmd = clamped

            print(f"[LaserController] MOV {voltage_cmd:.5f} "
                  f"(current={voltage:.5f}, WN={wn:.4f}, target_WN={self.target_wn:.4f})")
            self.device.MOV(self.axis, voltage_cmd)

            if self.stop_event.wait(self.poll_interval):
                break

            self._prev_voltage = voltage

        print(f"[LaserController] Target reached or stopped. Final WN: {wn:.4f}")

if __name__ == "__main__":
    pass