from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QGroupBox, QCheckBox)
from PyQt5.QtCore import pyqtSignal

class PlotOptionsWidget(QWidget):
    options_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        grp_opts = QGroupBox("Plot Options")
        layout_opts = QVBoxLayout()
        grp_opts.setLayout(layout_opts)

        self.chk_rate = QCheckBox("Event Rate vs Time")
        self.chk_rate.setChecked(True)
        self.chk_rate.toggled.connect(self.emit_options)
        layout_opts.addWidget(self.chk_rate)

        self.chk_scan = QCheckBox("Scan Results (Rate vs WN)")
        self.chk_scan.setChecked(True)
        self.chk_scan.toggled.connect(self.emit_options)
        layout_opts.addWidget(self.chk_scan)

        self.chk_laser = QCheckBox("Measured & Target WN vs Time")
        self.chk_laser.toggled.connect(self.emit_options)
        layout_opts.addWidget(self.chk_laser)

        self.chk_volt = QCheckBox("Voltage vs Time")
        self.chk_volt.toggled.connect(self.emit_options)
        layout_opts.addWidget(self.chk_volt)

        self.chk_tof = QCheckBox("ToF Histogram")
        self.chk_tof.toggled.connect(self.emit_options)
        layout_opts.addWidget(self.chk_tof)

        layout.addWidget(grp_opts)

    def emit_options(self):
        options = {
            'rate': self.chk_rate.isChecked(),
            'scan': self.chk_scan.isChecked(),
            'laser': self.chk_laser.isChecked(),
            'volt': self.chk_volt.isChecked(),
            'tof': self.chk_tof.isChecked()
        }
        self.options_changed.emit(options)

    def get_options(self):
        return {
            'rate': self.chk_rate.isChecked(),
            'scan': self.chk_scan.isChecked(),
            'laser': self.chk_laser.isChecked(),
            'volt': self.chk_volt.isChecked(),
            'tof': self.chk_tof.isChecked()
        }
