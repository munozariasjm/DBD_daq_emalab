"""Laser control settings dialog for CounterDrift-based stabilization.

The Matisse runs its own firmware CounterDrift loop; this dialog only exposes
the wavemeter-side parameters (tolerance, polling, averaging) and the
sequencing knobs (GoTo threshold, three settle windows).
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)


SETUP_BANNER = (
    "Matisse Commander setup (one-time):\n"
    "  • Display Options → Position Display Mode = nm\n"
    "  • CounterDrift dialog Unit = nm\n"
    "The DAQ sends nm-vacuum values; cm⁻¹ mode will command wildly wrong\n"
    "frequencies."
)


class LaserControlDialog(QDialog):
    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Laser Control (CounterDrift)")
        self.resize(420, 480)
        self.settings = dict(current_settings)

        layout = QVBoxLayout(self)

        banner = QLabel(SETUP_BANNER)
        banner.setWordWrap(True)
        banner.setStyleSheet(
            "QLabel { background-color: #fff7d6; color: #5a4a00;"
            " padding: 8px; border: 1px solid #d0c060; }"
        )
        layout.addWidget(banner)

        # --- Lock parameters ---
        lock_group = QGroupBox("Lock parameters")
        lock_form = QFormLayout()

        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setDecimals(7)
        self.tolerance_spin.setRange(1e-7, 1.0)
        self.tolerance_spin.setSingleStep(1e-6)
        self.tolerance_spin.setValue(float(self.settings.get("tolerance", 1e-5)))
        self.tolerance_spin.setToolTip(
            "Maximum |wavemeter − target| in cm⁻¹ for a sample to count toward lock.\n"
            "Hardware resolves below 1e-5; tighten as far as your wavemeter noise allows."
        )
        lock_form.addRow("Tolerance (cm⁻¹):", self.tolerance_spin)

        self.goto_threshold_spin = QDoubleSpinBox()
        self.goto_threshold_spin.setDecimals(7)
        self.goto_threshold_spin.setRange(1e-7, 1.0)
        self.goto_threshold_spin.setSingleStep(1e-5)
        self.goto_threshold_spin.setValue(float(self.settings.get("goto_threshold", 0.01)))
        self.goto_threshold_spin.setToolTip(
            "If |current − target| exceeds this, the controller runs MCP_WM.GoTo\n"
            "for coarse positioning before activating CounterDrift."
        )
        lock_form.addRow("GoTo threshold (cm⁻¹):", self.goto_threshold_spin)

        self.poll_spin = QDoubleSpinBox()
        self.poll_spin.setDecimals(3)
        self.poll_spin.setRange(0.001, 5.0)
        self.poll_spin.setSingleStep(0.01)
        self.poll_spin.setValue(float(self.settings.get("poll_interval", 0.5)))
        lock_form.addRow("Poll interval (s):", self.poll_spin)

        self.stable_samples_spin = QSpinBox()
        self.stable_samples_spin.setRange(1, 50)
        self.stable_samples_spin.setValue(int(self.settings.get("required_stable_samples", 4)))
        lock_form.addRow("Stable samples:", self.stable_samples_spin)

        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(1, 4)
        self.channel_spin.setValue(int(self.settings.get("wavechannel", 1)))
        lock_form.addRow("Wavemeter channel:", self.channel_spin)

        self.wm_avg_spin = QSpinBox()
        self.wm_avg_spin.setRange(1, 200)
        self.wm_avg_spin.setValue(int(self.settings.get("wm_averaging_samples", 5)))
        lock_form.addRow("WM averaging samples:", self.wm_avg_spin)

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
        self.dialog_open_spin.setToolTip(
            "Pause after MCP_WM_CounterDrift / MCP_WM_GotoPosition so the\n"
            "Matisse UI has time to actually open the dialog."
        )
        settle_form.addRow("Dialog-open delay:", self.dialog_open_spin)

        self.activation_spin = QDoubleSpinBox()
        self.activation_spin.setDecimals(3)
        self.activation_spin.setRange(0.0, 30.0)
        self.activation_spin.setSingleStep(0.05)
        self.activation_spin.setValue(float(self.settings.get("activation_delay", 1.0)))
        self.activation_spin.setToolTip(
            "Buffer after a fresh CounterDrift Activate(true) before we start\n"
            "judging stability against the wavemeter."
        )
        settle_form.addRow("Activation delay:", self.activation_spin)

        self.setpoint_settle_spin = QDoubleSpinBox()
        self.setpoint_settle_spin.setDecimals(3)
        self.setpoint_settle_spin.setRange(0.0, 30.0)
        self.setpoint_settle_spin.setSingleStep(0.05)
        self.setpoint_settle_spin.setValue(float(self.settings.get("setpoint_settle", 0.5)))
        self.setpoint_settle_spin.setToolTip(
            "Buffer after a Setpoint change while CounterDrift is already\n"
            "active (small slew within capture range)."
        )
        settle_form.addRow("Setpoint settle:", self.setpoint_settle_spin)

        settle_group.setLayout(settle_form)
        layout.addWidget(settle_group)

        # --- Mode ---
        self.continuous_check = QCheckBox()
        self.continuous_check.setChecked(bool(self.settings.get("continuous", False)))
        self.continuous_check.setToolTip(
            "Keep the control loop alive after the first lock so the laser\n"
            "stays held against long-term drift (CounterDrift continuous mode)."
        )
        cont_form = QFormLayout()
        cont_form.addRow("Continuous hold:", self.continuous_check)
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
