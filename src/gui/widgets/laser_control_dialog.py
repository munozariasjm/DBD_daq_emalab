from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QDoubleSpinBox,
                             QDialogButtonBox, QLabel)
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QSpinBox

class LaserControlDialog(QDialog):
    def __init__(self, current_settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Laser Control Settings")
        self.resize(300, 200)
        self.settings = current_settings.copy()

        self.layout = QVBoxLayout(self)
        self.form_layout = QFormLayout()

        # Tolerance
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(0.0001, 1.0)
        self.tolerance_spin.setDecimals(4)
        self.tolerance_spin.setValue(self.settings.get("tolerance", 0.01))
        self.form_layout.addRow("Tolerance (cm⁻¹):", self.tolerance_spin)

        # Fine Step
        self.fine_step_spin = QDoubleSpinBox()
        self.fine_step_spin.setRange(0.00001, 1.0)
        self.fine_step_spin.setDecimals(5)
        self.fine_step_spin.setValue(self.settings.get("step_fine", 0.0001))
        self.form_layout.addRow("Fine Step (mm):", self.fine_step_spin)

        # Coarse Step
        self.coarse_step_spin = QDoubleSpinBox()
        self.coarse_step_spin.setRange(0.001, 10.0)
        self.coarse_step_spin.setDecimals(3)
        self.coarse_step_spin.setValue(self.settings.get("step_coarse", 0.05))
        self.form_layout.addRow("Coarse Step (mm):", self.coarse_step_spin)

        # Poll Interval
        self.poll_spin = QDoubleSpinBox()
        self.poll_spin.setRange(0.01, 5.0)
        self.poll_spin.setDecimals(2)
        self.poll_spin.setSingleStep(0.1)
        self.poll_spin.setValue(self.settings.get("poll_interval", 0.5))
        self.form_layout.addRow("Poll Interval (s):", self.poll_spin)

        # Stable Samples
        self.stable_samples_spin = QSpinBox()
        self.stable_samples_spin.setRange(1, 20)
        self.stable_samples_spin.setValue(int(self.settings.get("required_stable_samples", 4)))
        self.form_layout.addRow("Stable Samples:", self.stable_samples_spin)

        self.channel_spin = QDoubleSpinBox()
        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(1, 4)
        self.channel_spin.setValue(int(self.settings.get("wavechannel", 3)))
        self.form_layout.addRow("Wavemeter Channel:", self.channel_spin)

        self.layout.addLayout(self.form_layout)

        # Buttons
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_settings(self):
        return {
            "tolerance": self.tolerance_spin.value(),
            "step_fine": self.fine_step_spin.value(),
            "step_coarse": self.coarse_step_spin.value(),
            "poll_interval": self.poll_spin.value(),
            "required_stable_samples": self.stable_samples_spin.value(),
            "wavechannel": self.channel_spin.value()
        }
