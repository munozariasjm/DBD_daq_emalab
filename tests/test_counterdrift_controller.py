"""Unit tests for the CounterDrift-based LaserController.

These tests run against a FakeMatisse that records every call into an ordered
log and lets each test seed the goto_status return values. The wavemeter
("EPICS") side is also mocked so we can drive in/out-of-tolerance reads at
will.
"""

import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from src.control.laser_controller import LaserController
from src.utils.units import wn_to_nm_vacuum


# Fast settle windows so the tests don't crawl.
FAST_CONFIG = {
    "tolerance": 0.0005,
    "poll_interval": 0.01,
    "required_stable_samples": 3,
    "goto_threshold": 0.05,
    "dialog_open_delay": 0.0,
    "activation_delay": 0.05,
    "setpoint_settle": 0.02,
    "continuous": False,
    "wavechannel": 1,
    "wm_averaging_samples": 1,
}


class FakeMatisse:
    """Records every method call in self.calls; goto_status returns drained
    from self.goto_status_queue (or 'STOP' once exhausted)."""

    def __init__(self):
        self.calls = []
        self.goto_status_queue = []
        # Default ~ matches a wavemeter at 12625 cm^-1 (1e7/12625 ≈ 791.96).
        # Tests can override to drive the unit-mismatch detection branches.
        self.matisse_nm = 792.0
        self._lock = threading.Lock()

    def _record(self, name, *args):
        with self._lock:
            self.calls.append((name, args))

    def cd_open(self):
        self._record("cd_open")
        return True

    def cd_setpoint(self, nm):
        self._record("cd_setpoint", float(nm))
        return True

    def cd_activate(self, state):
        self._record("cd_activate", bool(state))
        return True

    def cd_get_wavelength(self):
        self._record("cd_get_wavelength")
        return self.matisse_nm

    def goto_open(self):
        self._record("goto_open")
        return True

    def goto_set(self, nm):
        self._record("goto_set", float(nm))
        return True

    def goto_start(self):
        self._record("goto_start")
        return True

    def goto_status(self):
        self._record("goto_status")
        with self._lock:
            if self.goto_status_queue:
                return self.goto_status_queue.pop(0)
        return "STOP"

    def names(self):
        return [c[0] for c in self.calls]


class FakeEpics:
    """Mock wavemeter readback. Either a fixed value or a function of call count."""

    def __init__(self, reader):
        self.reader = reader
        self.reads = 0

    def caget(self, pv):
        self.reads += 1
        if callable(self.reader):
            return float(self.reader(self.reads))
        return float(self.reader)


def _wait_for(predicate, timeout=2.0, interval=0.005):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _make_controller(matisse, epics, **overrides):
    cfg = dict(FAST_CONFIG)
    cfg.update(overrides)
    return LaserController(matisse, epics, config=cfg)


# ---- Tests ----


def test_dialog_opens_once_across_calls():
    matisse = FakeMatisse()
    epics = FakeEpics(12625.0)
    ctrl = _make_controller(matisse, epics)

    ctrl.set_wavenumber(12625.0)
    assert _wait_for(lambda: ctrl.is_locked), "first lock did not engage"
    ctrl.set_wavenumber(12625.0001)  # same target, sub-threshold
    assert _wait_for(lambda: ctrl.is_locked)

    ctrl.stop()
    names = matisse.names()
    assert names.count("cd_open") == 1
    assert names.count("goto_open") == 1


def test_small_step_skips_goto():
    matisse = FakeMatisse()
    epics = FakeEpics(12625.0)  # already at target
    ctrl = _make_controller(matisse, epics, goto_threshold=0.05)

    ctrl.set_wavenumber(12625.0)
    assert _wait_for(lambda: ctrl.is_locked)
    ctrl.stop()

    names = matisse.names()
    assert "goto_set" not in names
    assert "goto_start" not in names
    assert "cd_setpoint" in names
    assert ("cd_activate", (True,)) in matisse.calls


def test_large_step_uses_goto():
    matisse = FakeMatisse()
    # Pretend the wavemeter reads far from target until GoTo "moves" us close.
    state = {"close": False}

    def reader(_n):
        return 12625.0 if state["close"] else 12624.0

    epics = FakeEpics(reader)
    ctrl = _make_controller(matisse, epics, goto_threshold=0.05)

    # Drain GoTo as one RUNNING then STOP; flip the reader after we see one
    # goto_status call so the post-goto wavemeter read is in range.
    matisse.goto_status_queue = ["RUNNING", "STOP"]

    def watcher():
        # Wait for the first goto_status call before flipping state.
        _wait_for(lambda: "goto_status" in matisse.names(), timeout=1.0)
        state["close"] = True

    threading.Thread(target=watcher, daemon=True).start()

    ctrl.set_wavenumber(12625.0)
    assert _wait_for(lambda: ctrl.is_locked, timeout=3.0)
    ctrl.stop()

    names = matisse.names()
    assert names.index("goto_set") < names.index("goto_start")
    assert names.index("goto_start") < names.index("cd_setpoint")
    assert ("cd_activate", (True,)) in matisse.calls


def test_setpoint_change_while_locked_skips_reactivate():
    matisse = FakeMatisse()
    epics = FakeEpics(12625.0)
    ctrl = _make_controller(matisse, epics)

    ctrl.set_wavenumber(12625.0)
    assert _wait_for(lambda: ctrl.is_locked)

    # Re-aim within capture range; sub-threshold so no GoTo.
    ctrl.set_wavenumber(12625.0001)
    assert _wait_for(lambda: ctrl.is_locked)

    ctrl.stop()
    activate_true_count = sum(
        1 for name, args in matisse.calls if name == "cd_activate" and args == (True,)
    )
    assert activate_true_count == 1, matisse.calls


def test_stop_deactivates_counterdrift():
    matisse = FakeMatisse()
    epics = FakeEpics(12625.0)
    ctrl = _make_controller(matisse, epics)

    ctrl.set_wavenumber(12625.0)
    assert _wait_for(lambda: ctrl.is_locked)
    ctrl.stop()

    assert ("cd_activate", (False,)) in matisse.calls


def test_stable_samples_enforced():
    matisse = FakeMatisse()
    # In-tolerance reads on every call; required_stable_samples=3 means we
    # should observe at least three averaged-wavemeter reads before is_locked.
    epics = FakeEpics(12625.0)
    ctrl = _make_controller(matisse, epics, required_stable_samples=3)

    ctrl.set_wavenumber(12625.0)
    assert _wait_for(lambda: ctrl.is_locked, timeout=2.0)
    # caget called once by the outer pre-check and >=3 times inside the verify loop.
    assert epics.reads >= 4
    ctrl.stop()


def test_activation_delay_honored():
    matisse = FakeMatisse()
    epics = FakeEpics(12625.0)
    ctrl = _make_controller(
        matisse,
        epics,
        activation_delay=0.4,
        required_stable_samples=1,
        poll_interval=0.01,
    )

    t0 = time.time()
    ctrl.set_wavenumber(12625.0)
    assert _wait_for(lambda: ctrl.is_locked, timeout=2.0)
    elapsed = time.time() - t0
    assert elapsed >= 0.4, f"activation_delay not waited: elapsed={elapsed}"
    ctrl.stop()


def test_unit_check_refuses_when_matisse_in_cm_inverse():
    """Matisse Display Unit = cm^-1: cd_get_wavelength returns the wavenumber
    instead of nm. The pre-flight check must catch this and the loop must
    NOT activate CounterDrift (which would drive the laser catastrophically
    off target)."""
    matisse = FakeMatisse()
    matisse.matisse_nm = 12625.0  # Matisse reports the wavenumber, not nm
    epics = FakeEpics(12625.0)
    ctrl = _make_controller(matisse, epics)

    ctrl.set_wavenumber(12625.0)
    # Give the loop time to fail the check and exit cleanly.
    assert _wait_for(lambda: not (ctrl.control_thread and ctrl.control_thread.is_alive()),
                     timeout=2.0), "control thread did not exit after unit-check failure"

    names = matisse.names()
    assert "cd_get_wavelength" in names
    # The critical assertion: we must NOT have engaged CounterDrift.
    assert ("cd_activate", (True,)) not in matisse.calls, \
        "controller activated CounterDrift despite unit mismatch — DANGEROUS"
    assert "cd_setpoint" not in names, \
        "controller sent a setpoint despite unit mismatch"
    assert not ctrl.is_locked


def test_unit_check_refuses_on_wavemeter_disagreement():
    """Matisse says 850 nm, wavemeter says 12625 cm^-1 (which is 791.96 nm).
    Neither interpretation matches — wavemeter channel or PV is wrong.
    Controller must refuse to engage."""
    matisse = FakeMatisse()
    matisse.matisse_nm = 850.0
    epics = FakeEpics(12625.0)
    ctrl = _make_controller(matisse, epics)

    ctrl.set_wavenumber(12625.0)
    assert _wait_for(lambda: not (ctrl.control_thread and ctrl.control_thread.is_alive()),
                     timeout=2.0)

    assert ("cd_activate", (True,)) not in matisse.calls
    assert "cd_setpoint" not in matisse.names()
    assert not ctrl.is_locked


def test_unit_check_proceeds_when_wm_plugin_unavailable():
    """Matisse Commander without the WM Selector Plugin replies `!ERROR` to
    MCP_WM_GET_WAVELENGTH; the server returns 0.0. We must NOT refuse to
    engage in that case — we just can't cross-check the unit setting, so
    we log and trust the operator's configuration."""
    matisse = FakeMatisse()
    matisse.matisse_nm = 0.0  # WM plugin not loaded
    epics = FakeEpics(12625.0)
    ctrl = _make_controller(matisse, epics)

    ctrl.set_wavenumber(12625.0)
    assert _wait_for(lambda: ctrl.is_locked, timeout=2.0), \
        "controller refused to engage when Matisse WM plugin unavailable"
    ctrl.stop()

    # We did engage — cd_activate(True) and cd_setpoint were sent.
    assert ("cd_activate", (True,)) in matisse.calls
    assert "cd_setpoint" in matisse.names()


def test_unit_check_runs_once_per_lifetime():
    """After a successful check, subsequent set_wavenumber calls should not
    re-issue cd_get_wavelength — the check is one-shot per controller."""
    matisse = FakeMatisse()
    epics = FakeEpics(12625.0)
    ctrl = _make_controller(matisse, epics)

    ctrl.set_wavenumber(12625.0)
    assert _wait_for(lambda: ctrl.is_locked)
    ctrl.set_wavenumber(12625.0001)
    assert _wait_for(lambda: ctrl.is_locked)
    ctrl.stop()

    assert matisse.names().count("cd_get_wavelength") == 1


def test_unit_conversion_to_nm():
    matisse = FakeMatisse()
    epics = FakeEpics(12625.0)
    ctrl = _make_controller(matisse, epics)

    target_wn = 12625.0
    expected_nm = wn_to_nm_vacuum(target_wn)
    ctrl.set_wavenumber(target_wn)
    assert _wait_for(lambda: ctrl.is_locked)
    ctrl.stop()

    setpoint_calls = [args for name, args in matisse.calls if name == "cd_setpoint"]
    assert setpoint_calls, "cd_setpoint never called"
    assert setpoint_calls[0][0] == pytest.approx(expected_nm, rel=1e-12)
