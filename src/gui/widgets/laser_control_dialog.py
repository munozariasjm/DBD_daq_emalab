"""Laser control settings dialog for CounterDrift-based stabilization.

All quantities the operator sees here are in wavenumber (cm^-1) or seconds.
The nm-vacuum conversion to the Matisse happens inside the controller; it is
never exposed in the UI.
"""

from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)


PARAM_HELP = {
    "tolerance": "Max |wavemeter − target| (cm⁻¹) that still counts as on-target.",
    "goto_threshold": "If the target is farther than this (cm⁻¹), run a coarse GoTo before locking.",
    "poll_interval": "Seconds between wavemeter reads while waiting for the lock to settle.",
    "required_stable_samples": "Consecutive in-tolerance reads required to declare the laser locked.",
    "wavechannel": "Wavemeter channel index (LaserLab:wavenumber_N) used as the lock reference.",
    "wm_averaging_samples": "Rolling-average window size applied to wavemeter reads.",
    "dialog_open_delay": "Seconds to wait after opening the CounterDrift / GoTo dialogs.",
    "activation_delay": "Seconds to wait after a fresh Activate(true) before judging stability.",
    "setpoint_settle": "Seconds to wait after changing the setpoint while already locked.",
    "continuous": "Keep holding the lock after the first success (continuous CounterDrift).",
}


def _help_button(text: str) -> QToolButton:
    btn = QToolButton()
    btn.setText("?")
    btn.setAutoRaise(True)
    btn.setToolTip(text)
    btn.setStyleSheet(
        "QToolButton { color: #4a6fa5; font-weight: bold; padding: 0 4px; }"
    )

    def show_help():
        QToolTip.showText(QCursor.pos() + QPoint(8, 8), text, btn)

    btn.clicked.connect(show_help)
    return btn


def _labeled(text: str, key: str) -> QWidget:
    """Compose 'Label  ?' for the left column of a QFormLayout row."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(QLabel(text))
    lay.addWidget(_help_button(PARAM_HELP[key]))
    lay.addStretch(1)
    return w


class LaserControlDialog(QDialog):
    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Laser Control (CounterDrift)")
        self.resize(420, 460)
        self.settings = dict(current_settings)

        layout = QVBoxLayout(self)

        # --- Lock parameters ---
        lock_group = QGroupBox("Lock parameters")
        lock_form = QFormLayout()

        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setDecimals(7)
        self.tolerance_spin.setRange(1e-7, 1.0)
        self.tolerance_spin.setSingleStep(1e-6)
        self.tolerance_spin.setValue(float(self.settings.get("tolerance", 1e-5)))
        lock_form.addRow(_labeled("Tolerance (cm⁻¹)", "tolerance"), self.tolerance_spin)

        self.goto_threshold_spin = QDoubleSpinBox()
        self.goto_threshold_spin.setDecimals(7)
        self.goto_threshold_spin.setRange(1e-7, 1.0)
        self.goto_threshold_spin.setSingleStep(1e-5)
        self.goto_threshold_spin.setValue(float(self.settings.get("goto_threshold", 0.01)))
        lock_form.addRow(_labeled("GoTo threshold (cm⁻¹)", "goto_threshold"), self.goto_threshold_spin)

        self.poll_spin = QDoubleSpinBox()
        self.poll_spin.setDecimals(3)
        self.poll_spin.setRange(0.001, 5.0)
        self.poll_spin.setSingleStep(0.01)
        self.poll_spin.setValue(float(self.settings.get("poll_interval", 0.5)))
        lock_form.addRow(_labeled("Poll interval (s)", "poll_interval"), self.poll_spin)

        self.stable_samples_spin = QSpinBox()
        self.stable_samples_spin.setRange(1, 50)
        self.stable_samples_spin.setValue(int(self.settings.get("required_stable_samples", 4)))
        lock_form.addRow(_labeled("Stable samples", "required_stable_samples"), self.stable_samples_spin)

        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(1, 4)
        self.channel_spin.setValue(int(self.settings.get("wavechannel", 1)))
        lock_form.addRow(_labeled("Wavemeter channel", "wavechannel"), self.channel_spin)

        self.wm_avg_spin = QSpinBox()
        self.wm_avg_spin.setRange(1, 200)
        self.wm_avg_spin.setValue(int(self.settings.get("wm_averaging_samples", 5)))
        lock_form.addRow(_labeled("WM averaging samples", "wm_averaging_samples"), self.wm_avg_spin)

        lock_group.setLayout(lock_form)
        layout.addWidget(lock_group)

        # --- Timing / settling ---
        settle_group = QGroupBox("Timing / settling (s)")
        settle_form = QFormLayout()

        self.dialog_open_spin = QDoubleSpinBox()
        self.dialog_open_spin.setDecimals(3)
        self.dialog_open_spin.setRange(0.0, 10.0)
        self.dialog_open_spin.setSingleStep(0.05)
        self.dialog_open_spin.setValue(float(self.settings.get("dialog_open_delay", 0.3)))
        settle_form.addRow(_labeled("Dialog-open delay", "dialog_open_delay"), self.dialog_open_spin)

        self.activation_spin = QDoubleSpinBox()
        self.activation_spin.setDecimals(3)
        self.activation_spin.setRange(0.0, 30.0)
        self.activation_spin.setSingleStep(0.05)
        self.activation_spin.setValue(float(self.settings.get("activation_delay", 1.0)))
        settle_form.addRow(_labeled("Activation delay", "activation_delay"), self.activation_spin)

        self.setpoint_settle_spin = QDoubleSpinBox()
        self.setpoint_settle_spin.setDecimals(3)
        self.setpoint_settle_spin.setRange(0.0, 30.0)
        self.setpoint_settle_spin.setSingleStep(0.05)
        self.setpoint_settle_spin.setValue(float(self.settings.get("setpoint_settle", 0.5)))
        settle_form.addRow(_labeled("Setpoint settle", "setpoint_settle"), self.setpoint_settle_spin)

        settle_group.setLayout(settle_form)
        layout.addWidget(settle_group)

        # --- Mode ---
        self.continuous_check = QCheckBox()
        self.continuous_check.setChecked(bool(self.settings.get("continuous", False)))
        cont_form = QFormLayout()
        cont_form.addRow(_labeled("Continuous hold", "continuous"), self.continuous_check)
        layout.addLayout(cont_form)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_settings(self) -> dict:
        return {
            "tolerance": self.tolerance_spin.value(),
            "goto_threshold": self.goto_threshold_spin.value(),
            "poll_interval": self.poll_spin.value(),
            "required_stable_samples": self.stable_samples_spin.value(),
            "wavechannel": self.channel_spin.value(),
            "wm_averaging_samples": self.wm_avg_spin.value(),
            "dialog_open_delay": self.dialog_open_spin.value(),
            "activation_delay": self.activation_spin.value(),
            "setpoint_settle": self.setpoint_settle_spin.value(),
            "continuous": self.continuous_check.isChecked(),
        }
