"""Unit tests for the closed-loop GratingController.

These run against the same simulation mocks the DAQ uses in grating mode
(MockGratingDevice as the PI stage, MockEpicsClient as the wavemeter), so the
servo is exercised end to end with no network or hardware. The mock's
wavenumber tracks its stage position through a `wn_per_unit` calibration; the
controller closes the loop on the (noisy) wavemeter read.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from src.control.grating_controller import GratingController, GratingPID
from src.simulation.hardware_mocks import MockGratingDevice, MockEpicsClient


# Fast so tests don't crawl: instant stage slew, short polls, tiny lock count.
def make_rig(controller_wn_per_unit=-1.0, mock_wn_per_unit=-1.0, **overrides):
    device = MockGratingDevice(initialization_params={
        "initial_wn": 12625.0,
        "initial_pos": 0.0,
        "wn_per_unit": mock_wn_per_unit,
        "slew_rate": 100000.0,   # effectively instant settle
        "noise_level": 0.0,
    })
    epics = MockEpicsClient(device, initialization_params={"noise_level": 0.0})
    config = {
        "axis": 1,
        "wn_per_unit": controller_wn_per_unit,
        "kp": 0.6,
        "ki": 0.0,
        "tolerance": 0.001,
        "poll_interval": 0.005,
        "required_stable_samples": 3,
        "step_limit": 50.0,
        "runaway_samples": 5,
        "runaway_margin": 0.0001,
        "wm_averaging_samples": 1,
        "continuous": True,
    }
    config.update(overrides)
    ctrl = GratingController(device, epics, config=config)
    return ctrl, device, epics


def wait_until(predicate, timeout=8.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# --------------------------------------------------------------------------
# GratingPID math
# --------------------------------------------------------------------------

def test_pid_proportional_step_uses_calibration_sign():
    # kp=0.5, wn_per_unit=-2 => step = 0.5 * error / (-2) = -0.25 * error
    pid = GratingPID(kp=0.5, ki=0.0, wn_per_unit=-2.0, step_limit=1e9)
    step = pid.compute(error=4.0, dt=0.1)
    assert step == pytest.approx(0.5 * 4.0 / -2.0)


def test_pid_step_limit_clamps():
    pid = GratingPID(kp=1.0, ki=0.0, wn_per_unit=1.0, step_limit=2.0)
    assert pid.compute(error=100.0, dt=0.1) == pytest.approx(2.0)
    assert pid.compute(error=-100.0, dt=0.1) == pytest.approx(-2.0)


def test_pid_zero_calibration_is_safe():
    pid = GratingPID(kp=1.0, ki=0.0, wn_per_unit=0.0, step_limit=5.0)
    assert pid.compute(error=4.0, dt=0.1) == 0.0


# --------------------------------------------------------------------------
# Closed-loop servo
# --------------------------------------------------------------------------

def test_servo_locks_on_target():
    ctrl, device, _ = make_rig()
    target = 12628.0
    try:
        ctrl.set_wavenumber(target)
        assert wait_until(lambda: ctrl.is_locked), "controller never reported a lock"
        assert ctrl.is_stable(), "is_stable() false after lock"
        assert abs(ctrl.get_wavenumber() - target) < ctrl.tolerance
    finally:
        ctrl.stop()


def test_servo_reaims_on_new_target():
    ctrl, device, _ = make_rig()
    try:
        ctrl.set_wavenumber(12628.0)
        assert wait_until(lambda: ctrl.is_locked)
        # Re-aim without restarting the loop.
        ctrl.set_wavenumber(12622.5)
        assert wait_until(lambda: ctrl.is_locked and abs(ctrl.get_wavenumber() - 12622.5) < ctrl.tolerance)
    finally:
        ctrl.stop()


def test_wrong_sign_calibration_triggers_runaway_and_latches():
    # Controller thinks +position raises wn, but the stage does the opposite:
    # every correction makes the error worse -> runaway abort, latched.
    ctrl, device, _ = make_rig(controller_wn_per_unit=+1.0, mock_wn_per_unit=-1.0)
    try:
        ctrl.set_wavenumber(12630.0)
        assert wait_until(lambda: ctrl._aborted), "runaway guard never latched on wrong-sign calibration"
        assert not ctrl.is_locked
        # Latched: a fresh target must NOT re-engage the servo.
        ctrl.set_wavenumber(12626.0)
        time.sleep(0.2)
        assert not ctrl.is_locked
    finally:
        ctrl.stop()


def test_out_of_travel_triggers_runaway():
    # Target is reachable in wn, but the travel clamp pins the stage before it
    # can get there -> out-of-range runaway abort.
    ctrl, device, _ = make_rig(pos_min=-1.0, pos_max=1.0, step_limit=50.0)
    try:
        ctrl.set_wavenumber(12700.0)  # ~75 cm^-1 away; needs ~75 units of travel
        assert wait_until(lambda: ctrl._aborted), "out-of-travel runaway never latched"
        assert not ctrl.is_locked
    finally:
        ctrl.stop()


def test_interface_parity_with_laser_controller():
    # Scanner / DAQSystem rely on these attributes/methods existing on either laser.
    ctrl, _, _ = make_rig()
    for name in ("set_wavenumber", "is_stable", "get_wavenumber", "stop",
                 "update_config", "start_counterdrift", "stop_counterdrift"):
        assert callable(getattr(ctrl, name)), f"missing {name}"
    assert hasattr(ctrl, "tolerance")
    assert hasattr(ctrl, "config")
