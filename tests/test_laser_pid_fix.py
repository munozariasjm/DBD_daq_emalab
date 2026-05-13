import sys
import os
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.control.pid import PIDController
from src.control.laser_controller import LaserController
from src.simulation.hardware_mocks import MockPIGCSDevice, MockEpicsClient

def _make_controller(mode="pid", voltage_min=0.0, voltage_max=0.7,
                     max_voltage_step=0.05,
                     slope=5.0, offset=16666.0, noise=0.0,
                     kp=0.5, ki=0.1, kd=0.0, tolerance=0.007,
                     poll_interval=0.01, move_speed=500.0,
                     pid_mode="positional", counterdrift_mode=False,
                     auto_reset_enabled=False, wm_averaging_samples=1):
    pi = MockPIGCSDevice(initialization_params={"move_speed": move_speed})
    pi.ConnectRS232(1, 9600)
    pi.SVO(1, True)
    epics = MockEpicsClient(pi, initialization_params={
        "slope": slope,
        "offset": offset,
        "noise_level": noise,
    })
    config = {
        "controller_mode": mode,
        "tolerance": tolerance,
        "poll_interval": poll_interval,
        "required_stable_samples": 3,
        "voltage_min": voltage_min,
        "voltage_max": voltage_max,
        "max_voltage_step": max_voltage_step,
        "counterdrift_mode": counterdrift_mode,
        "auto_reset_enabled": auto_reset_enabled,
        "auto_reset_margin": 0.05,
        "auto_reset_target": 0.35,
        "wm_averaging_samples": wm_averaging_samples,
        "pid": {"kp": kp, "ki": ki, "kd": kd, "d_filter_coeff": 0.1, "mode": pid_mode}
    }
    return LaserController(pi, epics, axis=1, config=config), pi, epics


# ============================================================
# Existing tests (preserved)
# ============================================================

class TestLaserControllerPIDFix:
    def test_pid_reaches_target_absolute(self):
        ctrl, pi, epics = _make_controller(kp=0.2, ki=0.5, tolerance=0.01)
        target = 16668.5
        ctrl.set_wavenumber(target)

        deadline = time.time() + 5.0
        while time.time() < deadline:
            if ctrl.is_stable(): break
            time.sleep(0.1)

        ctrl.stop()
        final_wn = ctrl.get_wavenumber()
        assert abs(final_wn - target) < 0.1

    def test_voltage_clamping_to_07(self):
        ctrl, pi, _ = _make_controller(kp=100.0)
        ctrl.set_wavenumber(16700.0)
        time.sleep(0.3)
        ctrl.stop()
        voltage = pi.qPOS(1)[1]
        assert 0.0 <= voltage <= 0.7001

    def test_voltage_limited_flag_logic(self):
        ctrl, pi, _ = _make_controller(kp=100.0, max_voltage_step=0.001)
        ctrl.set_wavenumber(16700.0)
        time.sleep(0.1)
        assert ctrl.voltage_limited is True
        ctrl.stop()

        ctrl.update_config({"pid": {"kp": 0.001}, "max_voltage_step": 1.0})
        ctrl.set_wavenumber(16666.05)
        time.sleep(0.2)
        assert ctrl.voltage_limited is False
        ctrl.stop()

    def test_max_voltage_step_limit(self):
        ctrl, pi, _ = _make_controller(kp=10.0, max_voltage_step=0.05, move_speed=10000.0)
        ctrl.set_wavenumber(16668.5)

        deadline = time.time() + 1.0
        first_step = None
        while time.time() < deadline:
            v = pi.qPOS(1)[1]
            if v > 0.001:  # ignore qPOS jitter
                first_step = v
                break
            time.sleep(0.01)

        ctrl.stop()
        assert first_step is not None
        assert abs(first_step - 0.05) < 0.01, f"First step was {first_step}, expected ~0.05"

    def test_negative_gains_with_negative_slope(self):
        ctrl, pi, epics = _make_controller(
            kp=-0.2, ki=-0.5, slope=-5.0, offset=16680.0, tolerance=0.01)
        target = 16677.5
        ctrl.set_wavenumber(target)

        deadline = time.time() + 5.0
        while time.time() < deadline:
            if ctrl.is_stable(): break
            time.sleep(0.1)

        ctrl.stop()
        final_wn = ctrl.get_wavenumber()
        assert abs(final_wn - target) < 0.1


# ============================================================
# New tests: Incremental PID
# ============================================================

class TestIncrementalPID:
    def test_bumpless_transfer_no_voltage_jump(self):
        """Incremental PID initialized at current voltage should not jump."""
        pid = PIDController(kp=-0.1, ki=-0.05, kd=0.0,
                            output_min=0.0, output_max=0.7, mode="incremental")
        # Simulate: piezo is at 0.4V, laser is near target
        initial_voltage = 0.4
        pid.reset(initial_output=initial_voltage)

        # Small error: target - measurement = 0.001 cm^-1
        output = pid.compute(setpoint=16668.0, measurement=16667.999, dt=0.1)

        # Output should be very close to 0.4V, not jump to 0
        assert abs(output - initial_voltage) < 0.01, (
            f"Voltage jumped from {initial_voltage} to {output}")

    def test_incremental_accumulates_from_initial(self):
        """Incremental PID should accumulate deltas from initial_output."""
        pid = PIDController(kp=0.0, ki=1.0, kd=0.0,
                            output_min=0.0, output_max=5.0, mode="incremental")
        pid.reset(initial_output=2.0)

        # Error = 1.0, ki=1.0, dt=0.1 → delta = 1.0 * 1.0 * 0.1 = 0.1
        out = pid.compute(setpoint=10.0, measurement=9.0, dt=0.1)
        assert out == pytest.approx(2.1, abs=0.01)

    def test_incremental_respects_clamp(self):
        """Incremental PID should clamp at output_max."""
        pid = PIDController(kp=0.0, ki=10.0, kd=0.0,
                            output_min=0.0, output_max=0.7, mode="incremental")
        pid.reset(initial_output=0.6)

        # Large positive delta should be clamped
        for _ in range(10):
            out = pid.compute(setpoint=10.0, measurement=5.0, dt=0.1)
        assert out == pytest.approx(0.7)

    def test_incremental_anti_windup(self):
        """Accumulated output should not wind up past limits."""
        pid = PIDController(kp=0.0, ki=10.0, kd=0.0,
                            output_min=0.0, output_max=0.7, mode="incremental")
        pid.reset(initial_output=0.5)

        # Push to max
        for _ in range(20):
            pid.compute(setpoint=10.0, measurement=5.0, dt=0.1)
        assert pid._accumulated_output == pytest.approx(0.7)

        # Now reverse — should respond immediately, not need to unwind
        out = pid.compute(setpoint=5.0, measurement=10.0, dt=0.1)
        assert out < 0.7

    def test_positional_backward_compat(self):
        """Positional mode should behave exactly as before."""
        pid = PIDController(kp=1.0, ki=0.0, kd=0.0, mode="positional")
        output = pid.compute(setpoint=10.0, measurement=8.0, dt=0.1)
        assert output == pytest.approx(2.0)

    def test_soft_reset_keeps_accumulated(self):
        """soft_reset() should preserve accumulated output."""
        pid = PIDController(kp=-0.1, ki=-0.05, kd=-0.01,
                            output_min=0.0, output_max=0.7, mode="incremental")
        pid.reset(initial_output=0.35)
        pid.compute(setpoint=16668.0, measurement=16667.9, dt=0.1)

        saved = pid._accumulated_output
        pid.soft_reset()
        assert pid._accumulated_output == saved
        assert pid._prev_error is None
        assert pid._prev_measurement is None

    def test_reset_with_initial_output(self):
        """reset(initial_output=x) should set accumulated output to x."""
        pid = PIDController(mode="incremental")
        pid.reset(initial_output=0.42)
        assert pid._accumulated_output == pytest.approx(0.42)

    def test_reset_without_initial_output_zeros(self):
        """reset() without initial_output should zero everything."""
        pid = PIDController(mode="incremental")
        pid.reset(initial_output=0.5)
        pid.reset()
        assert pid._accumulated_output == 0.0


# ============================================================
# New tests: Counterdrift
# ============================================================

class TestCounterdrift:
    def test_counterdrift_loop_continues_after_stable(self):
        """In counterdrift mode, the control loop should NOT exit after reaching target."""
        ctrl, pi, epics = _make_controller(
            kp=-0.2, ki=-0.1, slope=-5.0, offset=16680.0,
            tolerance=0.05, counterdrift_mode=True, pid_mode="incremental")

        # Target near starting WN so it stabilizes quickly
        starting_wn = 16680.0  # V=0
        target = starting_wn - 0.01
        ctrl.start_counterdrift(target)

        # Wait for stability
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if ctrl.is_stable():
                break
            time.sleep(0.1)

        assert ctrl.is_stable(), "Controller did not reach target"

        # In counterdrift mode, loop should still be running
        time.sleep(0.5)
        assert ctrl.control_thread.is_alive(), "Control loop exited in counterdrift mode"

        ctrl.stop_counterdrift()
        assert not ctrl.control_thread.is_alive()

    def test_non_counterdrift_exits_after_stable(self):
        """Without counterdrift, the loop should exit after reaching stability."""
        ctrl, pi, epics = _make_controller(
            kp=0.2, ki=0.1, tolerance=0.05, counterdrift_mode=False)

        target = 16666.0 + 0.01  # very close
        ctrl.set_wavenumber(target)

        deadline = time.time() + 5.0
        while time.time() < deadline:
            if not ctrl.control_thread.is_alive():
                break
            time.sleep(0.1)

        assert not ctrl.control_thread.is_alive(), "Loop should have exited"
        assert not ctrl.is_moving

    def test_is_stable_counterdrift_ignores_is_moving(self):
        """In counterdrift mode, is_stable() should return True based on WN alone."""
        ctrl, pi, epics = _make_controller(counterdrift_mode=True, tolerance=0.05)
        ctrl.target_wn = 16666.0
        ctrl.is_moving = True  # simulate running loop
        # Mock the position to be exactly at target
        pi.target_position[1] = 0.0
        pi.position[1] = 0.0
        # WN = 16666.0 + 0 * 5.0 = 16666.0, error = 0
        assert ctrl.is_stable()

    def test_setpoint_change_resets_pid_bumpless(self):
        """Changing target while loop is running should reset PID with bumpless transfer."""
        ctrl, pi, epics = _make_controller(
            kp=-0.2, ki=-0.1, slope=-5.0, offset=16680.0,
            tolerance=0.05, counterdrift_mode=True, pid_mode="incremental")

        ctrl.start_counterdrift(16679.5)
        time.sleep(0.3)

        # Change setpoint — PID resets with current voltage as initial output
        current_voltage = pi.qPOS(1)[1]
        ctrl.set_wavenumber(16679.0)
        assert ctrl.pid._prev_error is None, "reset should clear _prev_error"
        assert ctrl.pid._integral == 0.0, "reset should clear integral"
        # accumulated output should be at current voltage (bumpless transfer)
        assert abs(ctrl.pid._accumulated_output - current_voltage) < 0.01

        ctrl.stop_counterdrift()


# ============================================================
# New tests: Auto-Reset
# ============================================================

class TestAutoReset:
    def test_auto_reset_recenters_piezo(self):
        """When piezo hits near max, auto-reset should ramp it back to target."""
        ctrl, pi, epics = _make_controller(
            kp=-0.1, ki=-0.05, slope=-5.0, offset=16680.0,
            tolerance=0.01, auto_reset_enabled=True, pid_mode="incremental")

        # Place piezo near max voltage
        pi.target_position[1] = 0.68
        pi.position[1] = 0.68

        # Perform auto-reset directly
        ctrl._perform_auto_reset()

        voltage = pi.qPOS(1)[1]
        assert abs(voltage - 0.35) < 0.01, f"Piezo should be near 0.35V, got {voltage}"
        # PID should be re-initialized at the reset target
        assert ctrl.pid._accumulated_output == pytest.approx(0.35)

    def test_auto_reset_not_triggered_in_safe_range(self):
        """Auto-reset should not trigger when piezo is in the safe range."""
        ctrl, pi, epics = _make_controller(auto_reset_enabled=True)

        pi.target_position[1] = 0.35
        pi.position[1] = 0.35

        result = ctrl._perform_auto_reset()
        assert result is False

    def test_auto_reset_near_min(self):
        """Auto-reset should trigger when near minimum voltage too."""
        ctrl, pi, epics = _make_controller(
            auto_reset_enabled=True, pid_mode="incremental")

        pi.target_position[1] = 0.02
        pi.position[1] = 0.02

        ctrl._perform_auto_reset()
        voltage = pi.qPOS(1)[1]
        assert abs(voltage - 0.35) < 0.01

    def test_auto_reset_respects_max_voltage_step(self):
        """Auto-reset ramp should not jump more than max_voltage_step per step."""
        ctrl, pi, epics = _make_controller(
            auto_reset_enabled=True, max_voltage_step=0.02, pid_mode="incremental",
            move_speed=10000.0)

        pi.target_position[1] = 0.68
        pi.position[1] = 0.68

        # Track all MOV calls
        original_mov = pi.MOV
        mov_voltages = []
        def tracking_mov(axis, target):
            mov_voltages.append(target)
            original_mov(axis, target)
        pi.MOV = tracking_mov

        ctrl._perform_auto_reset()

        # Each step should be <= max_voltage_step from the previous
        for i in range(1, len(mov_voltages)):
            delta = abs(mov_voltages[i] - mov_voltages[i-1])
            assert delta <= 0.02 + 1e-6, (
                f"Step {i}: delta={delta:.6f} exceeds max_voltage_step=0.02")


# ============================================================
# New tests: Wavemeter Averaging
# ============================================================

class TestWavemeterAveraging:
    def test_averaging_smooths_noise(self):
        """With averaging, noisy readings should produce a smoother result."""
        ctrl, pi, epics = _make_controller(
            noise=0.01, wm_averaging_samples=10)

        # Fill the buffer
        readings = []
        for _ in range(20):
            wn = ctrl._get_averaged_wavenumber()
            readings.append(wn)

        # After buffer is full, variance of averaged readings should be
        # less than variance of raw readings
        raw_readings = [ctrl.get_wavenumber() for _ in range(20)]

        avg_spread = max(readings[10:]) - min(readings[10:])
        raw_spread = max(raw_readings) - min(raw_readings)
        # Averaged spread should be smaller (or at least not bigger)
        assert avg_spread <= raw_spread + 0.005

    def test_averaging_buffer_size(self):
        """Buffer should respect configured size."""
        ctrl, _, _ = _make_controller(wm_averaging_samples=7)
        assert ctrl._wm_buffer.maxlen == 7


# ============================================================
# New tests: Bang-bang init fix
# ============================================================

class TestBangBangInit:
    def test_bangbang_no_crash_on_first_call(self):
        """Bang-bang should not crash due to uninitialized _prev_voltage."""
        ctrl, pi, epics = _make_controller(mode="bangbang", noise=0.0001)
        # _prev_voltage should be initialized
        assert hasattr(ctrl, '_prev_voltage')

        # Should not raise
        ctrl.set_wavenumber(16666.1)
        time.sleep(0.3)
        ctrl.stop()

        voltage = pi.qPOS(1)[1]
        assert ctrl.voltage_min <= voltage <= ctrl.voltage_max + 0.001


# ============================================================
# New tests: Incremental PID with LaserController
# ============================================================

class TestIncrementalPIDIntegration:
    def test_incremental_pid_converges(self):
        """Incremental PID should converge to target wavenumber."""
        ctrl, pi, epics = _make_controller(
            kp=-0.2, ki=-0.5, slope=-5.0, offset=16680.0,
            tolerance=0.01, pid_mode="incremental")

        target = 16677.5  # needs V = 0.5
        ctrl.set_wavenumber(target)

        deadline = time.time() + 5.0
        while time.time() < deadline:
            if ctrl.is_stable(): break
            time.sleep(0.1)

        ctrl.stop()
        final_wn = ctrl.get_wavenumber()
        assert abs(final_wn - target) < 0.1

    def test_incremental_pid_no_initial_jump(self):
        """Incremental PID should start from current voltage, not zero."""
        ctrl, pi, epics = _make_controller(
            kp=-0.1, ki=-0.05, slope=-5.0, offset=16680.0,
            tolerance=0.01, pid_mode="incremental", move_speed=10000.0)

        # Set piezo to 0.4V before starting
        pi.target_position[1] = 0.4
        pi.position[1] = 0.4

        target = 16680.0 + 0.4 * (-5.0) - 0.01  # just slightly off current WN
        ctrl.set_wavenumber(target)

        # Check first MOV isn't a big jump
        time.sleep(0.1)
        voltage = pi.qPOS(1)[1]
        # Should be near 0.4V, not near 0
        assert abs(voltage - 0.4) < 0.1, (
            f"Voltage jumped to {voltage}, expected near 0.4")

        ctrl.stop()


# ============================================================
# New tests: PID Enable/Disable (external laser control)
# ============================================================

class TestPIDDisabled:
    def test_pid_disabled_no_control_thread(self):
        """With pid_enabled=False, set_wavenumber should NOT start a control thread."""
        ctrl, pi, epics = _make_controller(pid_mode="incremental")
        ctrl.pid_enabled = False

        ctrl.set_wavenumber(16668.0)
        time.sleep(0.1)

        assert ctrl.control_thread is None or not ctrl.control_thread.is_alive()
        assert ctrl.target_wn == 16668.0
        assert ctrl.is_moving is False
        ctrl.stop()

    def test_pid_disabled_no_mov_commands(self):
        """With pid_enabled=False, no MOV commands should be sent."""
        ctrl, pi, epics = _make_controller(pid_mode="incremental")
        ctrl.pid_enabled = False

        # Track MOV calls
        mov_calls = []
        original_mov = pi.MOV
        def tracking_mov(axis, target):
            mov_calls.append(target)
            original_mov(axis, target)
        pi.MOV = tracking_mov

        ctrl.set_wavenumber(16670.0)
        time.sleep(0.2)
        ctrl.stop()

        assert len(mov_calls) == 0, f"Expected no MOV calls, got {len(mov_calls)}"

    def test_pid_disabled_is_stable_wavemeter_only(self):
        """With pid_enabled=False, is_stable checks wavemeter only (ignores is_moving)."""
        ctrl, pi, epics = _make_controller(tolerance=0.05)
        ctrl.pid_enabled = False
        ctrl.is_moving = True  # would normally make is_stable return False

        # Position at V=0 → WN = 16666.0
        pi.target_position[1] = 0.0
        pi.position[1] = 0.0
        ctrl.target_wn = 16666.0

        assert ctrl.is_stable(), "is_stable should return True based on wavemeter alone"

    def test_pid_disabled_is_stable_returns_false_when_far(self):
        """With pid_enabled=False, is_stable returns False when wavemeter is far from target."""
        ctrl, pi, epics = _make_controller(tolerance=0.05)
        ctrl.pid_enabled = False

        pi.target_position[1] = 0.0
        pi.position[1] = 0.0
        ctrl.target_wn = 16670.0  # far from 16666.0

        assert not ctrl.is_stable()

    def test_pid_enabled_by_default(self):
        """pid_enabled should default to True."""
        ctrl, pi, epics = _make_controller()
        assert ctrl.pid_enabled is True

    def test_pid_enabled_from_config(self):
        """pid_enabled=False in config should be respected."""
        pi = MockPIGCSDevice(initialization_params={"move_speed": 500.0})
        pi.ConnectRS232(1, 9600)
        pi.SVO(1, True)
        epics = MockEpicsClient(pi, initialization_params={
            "slope": 5.0, "offset": 16666.0, "noise_level": 0.0})
        config = {
            "pid_enabled": False,
            "controller_mode": "pid",
            "tolerance": 0.01,
            "poll_interval": 0.1,
            "required_stable_samples": 3,
            "voltage_min": 0.0,
            "voltage_max": 0.7,
            "pid": {"kp": -0.1, "ki": -0.05, "kd": 0.0}
        }
        ctrl = LaserController(pi, epics, axis=1, config=config)
        assert ctrl.pid_enabled is False

    def test_pid_disabled_update_config(self):
        """update_config should be able to toggle pid_enabled at runtime."""
        ctrl, pi, epics = _make_controller()
        assert ctrl.pid_enabled is True

        ctrl.update_config({"pid_enabled": False})
        assert ctrl.pid_enabled is False

        ctrl.update_config({"pid_enabled": True})
        assert ctrl.pid_enabled is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
