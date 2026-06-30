"""Unit tests for the GratingController (coarse/fine position-stepping "go_to").

These run against the same simulation mocks the DAQ uses in grating mode
(MockGratingDevice as the PI stage, MockEpicsClient as the wavemeter), so the
search is exercised end to end with no network or hardware. The mock's
wavenumber tracks its stage position through a negative slope (moving the stage
up lowers the wavenumber), matching the real grating; the controller walks the
position until the wavemeter sits on target.
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from src.control.grating_controller import GratingController
from src.simulation.hardware_mocks import MockGratingDevice, MockEpicsClient


# Operating point: wn = 12625.2 + (pos - 0.35) * (-1.0).
def make_rig(**overrides):
    device = MockGratingDevice(initialization_params={
        "initial_wn": 12625.2,
        "initial_pos": 0.35,
        "wn_per_unit": -1.0,     # negative slope: +position -> -wavenumber
        "slew_rate": 100000.0,   # effectively instant settle
        "noise_level": 0.0,
    })
    epics = MockEpicsClient(device, initialization_params={"noise_level": 0.0})
    config = {
        # Faster/coarser than the real defaults so the sim search converges quickly.
        "tolerance": 0.003,
        "step_fine": 0.002,
        "step_coarse": 0.02,
        "poll_interval": 0.002,
        "required_stable_samples": 2,
        "wavechannel": 1,
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


def test_servo_locks_on_target():
    ctrl, device, _ = make_rig()
    target = 12625.25
    try:
        ctrl.set_wavenumber(target)
        assert wait_until(lambda: ctrl.is_stable()), "controller never reported stable"
        assert abs(ctrl.get_wavenumber() - target) < ctrl.tolerance
    finally:
        ctrl.stop()


def test_servo_reaims_on_new_target():
    ctrl, device, _ = make_rig()
    try:
        ctrl.set_wavenumber(12625.25)
        assert wait_until(lambda: ctrl.is_stable())
        ctrl.set_wavenumber(12625.15)
        assert wait_until(lambda: ctrl.is_stable() and abs(ctrl.get_wavenumber() - 12625.15) < ctrl.tolerance)
    finally:
        ctrl.stop()


def test_steps_in_correct_direction_for_negative_slope():
    # Target below the current wavenumber -> wavemeter is above target -> the
    # controller must step the stage UP (negative slope brings wn down).
    ctrl, device, _ = make_rig()
    start_pos = device.qPOS()
    try:
        ctrl.set_wavenumber(12625.10)  # below initial 12625.2
        assert wait_until(lambda: device.qPOS() > start_pos + 0.005, timeout=4.0), \
            "stage did not step up to lower the wavenumber"
    finally:
        ctrl.stop()


def test_interface_parity_with_laser_controller():
    # Scanner / DAQSystem rely on these existing on either laser.
    ctrl, _, _ = make_rig()
    for name in ("set_wavenumber", "is_stable", "get_wavenumber", "stop",
                 "update_config", "start_counterdrift", "stop_counterdrift"):
        assert callable(getattr(ctrl, name)), f"missing {name}"
    assert hasattr(ctrl, "tolerance")
    assert hasattr(ctrl, "config")


def test_update_config_retunes_steps():
    ctrl, _, _ = make_rig()
    ctrl.update_config({"step_fine": 0.005, "tolerance": 0.01, "required_stable_samples": 5})
    assert ctrl.step_fine == 0.005
    assert ctrl.tolerance == 0.01
    assert ctrl.required_stable_samples == 5
