from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QGroupBox, QLabel,
                             QHBoxLayout, QProgressBar)
from PyQt5.QtGui import QPainter, QColor, QBrush
from PyQt5.QtCore import Qt, QSize

class LEDIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.color = QColor("red")

    def set_color(self, color_str):
        self.color = QColor(color_str)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(self.color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(2, 2, 20, 20)


class StatusWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        grp_status = QGroupBox("Status")
        layout_status = QVBoxLayout()
        grp_status.setLayout(layout_status)

        self.lbl_progress = QLabel("Progress: Idle")
        layout_status.addWidget(self.lbl_progress)

        # LED Row
        row_led = QHBoxLayout()
        row_led.addWidget(QLabel("State:"))
        self.led = LEDIndicator()
        row_led.addWidget(self.led)
        row_led.addStretch()
        layout_status.addLayout(row_led)

        self.lbl_eta = QLabel("ETA: --")
        layout_status.addWidget(self.lbl_eta)

        # Info Icon Row
        row_info = QHBoxLayout()
        self.lbl_status_wn = QLabel("Measured: -- cm^-1\nTarget: -- cm^-1")
        font = self.lbl_status_wn.font()
        font.setBold(True)
        self.lbl_status_wn.setFont(font)
        row_info.addWidget(self.lbl_status_wn)

        row_info.addStretch()
        self.lbl_scan_info = QLabel("ⓘ")
        self.lbl_scan_info.setFixedSize(20, 20)
        self.lbl_scan_info.setAlignment(Qt.AlignCenter)
        self.lbl_scan_info.setStyleSheet("border: 1px solid gray; border-radius: 10px; color: #2196F3; font-weight: bold;")
        self.lbl_scan_info.setToolTip("No active scan")
        row_info.addWidget(self.lbl_scan_info)
        layout_status.addLayout(row_info)

        layout_status.addWidget(QLabel("Scan Progress:"))
        self.progress_bar = QProgressBar()
        layout_status.addWidget(self.progress_bar)

        layout_status.addWidget(QLabel("Bin Accumulation:"))
        self.bin_progress = QProgressBar()
        layout_status.addWidget(self.bin_progress)

        layout.addWidget(grp_status)

    def update_status(self, daq_status, active_params_text=None):
        target_wn = daq_status['target_wn']
        measured_wn = daq_status['measured_wn']

        self.lbl_status_wn.setText(f"Measured: {measured_wn:.4f} cm^-1\nTarget: {target_wn:.4f} cm^-1")

        if active_params_text:
             self.lbl_scan_info.setToolTip(active_params_text)

        if daq_status['is_running']:
            if daq_status['is_paused']:
                self.lbl_progress.setText("Status: Paused")
            elif daq_status.get('is_stopping', False):
                self.lbl_progress.setText("Status: Stopping...")
            else:
                self.lbl_progress.setText(f"Status: Scanning Bin {daq_status['bin_index']}/{daq_status['total_bins']}")

            # 3 States:
            # 1. Off/Idle -> Red (handled in else block below)
            # 2. Accumulating (Ingesting) -> Green
            # 3. Moving/Converging -> Yellow

            # We need to distinguish between Accumulating and Moving.
            # DAQ Status doesn't explicitly say "Moving", but if running and NOT accumulating, we are moving/stabilizing.
            # Or we can check if bin_progress is moving?

            # Check 'is_accumulating' from scanner state?
            # The update_status method receives a dict 'daq_status' which comes from get_status() in Scanner.
            # We need to ensure 'accumulating' flag is in there. Assuming it is or we add it to scanner.

            # Let's check scanner.py get_status
            is_accumulating = daq_status.get('is_accumulating', False)
            if is_accumulating:
                 self.led.set_color("green") # Ingesting
                 self.lbl_progress.setText(f"Status: Ingesting (Bin {daq_status['bin_index']})")
            else:
                 self.led.set_color("yellow") # Converging / Moving
                 self.lbl_progress.setText(f"Status: Converging (Bin {daq_status['bin_index']})")

            if daq_status['eta_seconds'] > 0:
                mins = int(daq_status['eta_seconds'] // 60)
                secs = int(daq_status['eta_seconds'] % 60)
                self.lbl_eta.setText(f"ETA: {mins}m {secs}s")
            else:
                self.lbl_eta.setText("ETA: Calculating...")

            if daq_status['total_bins'] > 0:
                pct = int((daq_status['bins_completed'] / daq_status['total_bins']) * 100)
                self.progress_bar.setValue(pct)

            # Bin Progress
            if daq_status['stop_value'] > 0:
                if daq_status['stop_mode'] == 'events':
                     bin_pct = (daq_status['accumulated'] / daq_status['stop_value']) * 100
                     self.bin_progress.setValue(int(min(bin_pct, 100)))
                elif daq_status['stop_mode'] == 'bunches':
                     bin_pct = (daq_status['accumulated_bunches'] / daq_status['stop_value']) * 100
                     self.bin_progress.setValue(int(min(bin_pct, 100)))
                else:
                     self.bin_progress.setValue(0)
        else:
            self.lbl_progress.setText("Status: Idle")
            self.led.set_color("red") # Off/Idle
            self.lbl_eta.setText("ETA: --")
            self.progress_bar.setValue(0)
            self.bin_progress.setValue(0)
            self.lbl_scan_info.setToolTip("No active scan")
