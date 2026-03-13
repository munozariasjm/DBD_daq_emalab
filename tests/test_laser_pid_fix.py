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
                     poll_interval=0.01, move_speed=500.0):
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
        "pid": {"kp": kp, "ki": ki, "kd": kd, "d_filter_coeff": 0.1}
    }
    return LaserController(pi, epics, axis=1, config=config), pi, epics

class TestLaserControllerPIDFix:
    def test_pid_reaches_target_absolute(self):
        # We need a KP that results in a voltage within 0.7
        # WN = 16666 + 5 * V.
        # To get 16668.5, V = (16668.5 - 16666) / 5 = 0.5V
        # Initial error = 16668.5 - 16666 = 2.5
        # With KP = 0.2, V = 0.2 * 2.5 = 0.5. Perfect.
        ctrl, pi, epics = _make_controller(kp=0.2, ki=0.5, tolerance=0.01)
        target = 16668.5
        ctrl.set_wavenumber(target)

        deadline = time.time() + 5.0
        while time.time() < deadline:
            if ctrl.is_stable(): break
            time.sleep(0.1)

        ctrl.stop()
        final_wn = ctrl.get_wavenumber()
        assert abs(final_wn - target) < 0.1 # loosen a bit due to step limits

    def test_voltage_clamping_to_07(self):
        # Even with huge gain, voltage must not exceed 0.7
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
        # Small step limit + huge target = definitely limited
        assert ctrl.voltage_limited is True
        ctrl.stop()

        # Now manageable target with large step limit
        ctrl.update_config({"pid": {"kp": 0.001}, "max_voltage_step": 1.0})
        # error 0.05 * kp 0.001 = 0.00005. Unlimited.
        ctrl.set_wavenumber(16666.05)
        time.sleep(0.2)
        assert ctrl.voltage_limited is False
        ctrl.stop()

    def test_max_voltage_step_limit(self):
        # Set move speed high so we catch the first iteration MOV value
        ctrl, pi, _ = _make_controller(kp=10.0, max_voltage_step=0.05, move_speed=10000.0)
        # Target needs 0.5V. First MOV should be 0.05.
        ctrl.set_wavenumber(16668.5)

        deadline = time.time() + 1.0
        first_step = None
        while time.time() < deadline:
            v = pi.qPOS(1)[1]
            if v > 0:
                first_step = v
                break
            time.sleep(0.01)

        ctrl.stop()
        assert first_step is not None
        # Should be exactly max_step because gain is huge
        assert abs(first_step - 0.05) < 1e-4, f"First step was {first_step}, expected 0.05"

    def test_negative_gains_with_negative_slope(self):
        # System: WN = 16680 - 5 * V.
        # Target: 16677.5. Needs V = (16680 - 16677.5) / 5 = 0.5V.
        # Current (V=0): 16680. Error = 16677.5 - 16680 = -2.5.
        # With negative gains: V = -0.2 * -2.5 = 0.5. Should converge.
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
