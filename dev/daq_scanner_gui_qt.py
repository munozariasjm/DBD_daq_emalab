import sys
import os
import time
import threading
import numpy as np
from collections import deque
import csv

# PyQt5
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QLabel, QPushButton,
                             QGroupBox, QDoubleSpinBox, QComboBox, QCheckBox,
                             QProgressBar, QSplitter, QMessageBox, QFileDialog, QFrame)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont

# Matplotlib
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# Add src to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.simulation.sim_tagger import MockTagger
from src.simulation.sim_sensors import MockMultimeter, MockSpectrometreReader, MockWavenumberReader
from src.simulation.sim_laser import MockLaser
from src.control.data_saver import DataSaver
from src.control.scanner import Scanner

class DAQSystem:
    def __init__(self):
        # Hardware
        self.tagger = MockTagger()
        self.laser = MockLaser()
        self.multimeter = MockMultimeter("COM1")
        self.spec_reader = MockSpectrometreReader()
        self.wave_reader = MockWavenumberReader(source=self.laser)

        # Services
        self.saver = DataSaver("data/scan_log.csv")
        self.scanner = Scanner(self.laser, self.wave_reader)

        # State
        self.running = False
        self.events_processed = 0
        self.event_timestamps = deque(maxlen=1000)

        # Thread handles
        self.daq_thread = None

    def start(self):
        if self.running: return
        print("[DAQ] Starting system...")
        self.running = True

        self.spec_reader.start()
        self.wave_reader.start()
        self.tagger.start_reading()
        self.saver.start()

        self.daq_thread = threading.Thread(target=self._daq_loop, daemon=True)
        self.daq_thread.start()

    def stop(self):
        self.running = False
        print("[DAQ] Stopping system...")

        if self.scanner.is_alive():
            self.scanner.stop()
        self.saver.stop()
        self.tagger.stop()
        self.spec_reader.stop()
        self.wave_reader.stop()

    def start_scan(self, min_wn, max_wn, step, stop_mode, stop_value):
        # If scanner is old/dead, recreate it
        if not self.scanner.is_alive() and self.scanner.running == False:
            self.scanner = Scanner(self.laser, self.wave_reader)

        if self.scanner.is_alive():
             print("[DAQ] Scanner already running.")
             return

        self.scanner.configure(min_wn, max_wn, step, stop_mode, stop_value)
        self.scanner.start()

    def _daq_loop(self):
        while self.running:
            data = self.tagger.get_data()

            # Latest sensors
            current_voltage = self.multimeter.getVoltage()
            current_spec = self.spec_reader.spectrum
            current_wns = self.wave_reader.get_wavenumbers()

            for entry in data:
                channel = entry[2]
                timestamp = entry[4]

                if channel == -1: # Trigger / Bunch
                    if self.scanner.is_accumulating:
                         self.scanner.report_event(is_bunch=True)

                if channel == 1:
                    self.events_processed += 1
                    self.event_timestamps.append(timestamp)

                    record = {
                        'timestamp': timestamp,
                        'channel': channel,
                        'tof': entry[3],
                        'voltage': current_voltage,
                        'spectrum_peak': current_spec,
                        'wavemeter_wn': current_wns[0], # Native cm^-1
                        'laser_target_wn': self.scanner.current_wavenumber,
                        'scan_bin_index': self.scanner.current_bin_index
                    }

                    # Only save if accumulating
                    if self.scanner.is_accumulating:
                        self.saver.add_event(record)
                        self.scanner.report_event(is_bunch=False)

            time.sleep(0.005)

    def get_instant_rate(self):
        if len(self.event_timestamps) < 2: return 0.0
        dt = self.event_timestamps[-1] - self.event_timestamps[0]
        if dt <= 0: return 0.0
        return len(self.event_timestamps) / dt

# --- PyQt5 GUI ---

class MainWindow(QMainWindow):
    def __init__(self, daq_system):
        super().__init__()
        self.daq = daq_system
        self.setWindowTitle("DAQ Scanner Control (PyQt5) - Wavenumber Mode")
        self.resize(1200, 800)

        # Central Widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # Controls (Left)
        self.controls_widget = QWidget()
        self.controls_layout = QVBoxLayout(self.controls_widget)
        self.controls_layout.setContentsMargins(10, 10, 10, 10)
        self.controls_layout.setSpacing(15)

        self._init_controls()

        splitter.addWidget(self.controls_widget)

        # Plots (Right)
        self.plots_widget = QWidget()
        self.plots_layout = QVBoxLayout(self.plots_widget)

        self._init_plots()

        splitter.addWidget(self.plots_widget)
        splitter.setStretchFactor(1, 4) # Plots take more space

        # Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_gui)
        self.timer.start(100) # 10Hz

        # Data Histories
        self.start_time = time.time()
        self.time_history = deque(maxlen=200)
        self.rate_history = deque(maxlen=200)
        self.wn_history = deque(maxlen=200)
        self.target_wn_history = deque(maxlen=200)
        self.volt_history = deque(maxlen=200)

    def _init_controls(self):
        # --- Parameters ---
        grp_params = QGroupBox("Scan Parameters")
        layout_params = QGridLayout()
        grp_params.setLayout(layout_params)

        # Min WN
        layout_params.addWidget(QLabel("Min Wavenumber (cm^-1):"), 0, 0)
        self.spin_min_wn = QDoubleSpinBox()
        self.spin_min_wn.setRange(0, 50000)
        self.spin_min_wn.setValue(16666.0)
        self.spin_min_wn.setDecimals(2)
        layout_params.addWidget(self.spin_min_wn, 0, 1)

        # Max WN
        layout_params.addWidget(QLabel("Max Wavenumber (cm^-1):"), 1, 0)
        self.spin_max_wn = QDoubleSpinBox()
        self.spin_max_wn.setRange(0, 50000)
        self.spin_max_wn.setValue(16680.0)
        self.spin_max_wn.setDecimals(2)
        layout_params.addWidget(self.spin_max_wn, 1, 1)

        # Step
        layout_params.addWidget(QLabel("Step Size (cm^-1):"), 2, 0)
        self.spin_step = QDoubleSpinBox()
        self.spin_step.setRange(0.01, 1000)
        self.spin_step.setValue(0.5)
        self.spin_step.setDecimals(2)
        layout_params.addWidget(self.spin_step, 2, 1)

        # Stop Mode
        layout_params.addWidget(QLabel("Stop Condition:"), 3, 0)
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Target Bunches", "Fixed Time (s)"])
        layout_params.addWidget(self.combo_mode, 3, 1)

        # Stop Value
        layout_params.addWidget(QLabel("Target Value:"), 4, 0)
        self.spin_stop_val = QDoubleSpinBox()
        self.spin_stop_val.setRange(0.1, 1000000)
        self.spin_stop_val.setValue(100)
        self.spin_stop_val.setDecimals(1)
        layout_params.addWidget(self.spin_stop_val, 4, 1)

        self.controls_layout.addWidget(grp_params)

        # Track widgets for locking
        self.param_widgets = [
            self.spin_min_wn, self.spin_max_wn, self.spin_step,
            self.combo_mode, self.spin_stop_val
        ]

        # --- Actions ---
        grp_actions = QGroupBox("Actions")
        layout_actions = QVBoxLayout()
        grp_actions.setLayout(layout_actions)

        self.btn_start = QPushButton("Start Scan")
        self.btn_start.clicked.connect(self.on_start_scan)
        self.btn_start.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        layout_actions.addWidget(self.btn_start)

        self.btn_pause = QPushButton("Pause Scan")
        self.btn_pause.clicked.connect(self.on_pause_scan)
        self.btn_pause.setEnabled(False)
        layout_actions.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("Stop Scan")
        self.btn_stop.clicked.connect(self.on_stop_scan)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("background-color: #f44336; color: white;")
        layout_actions.addWidget(self.btn_stop)

        self.btn_reset = QPushButton("Reset Scan")
        self.btn_reset.clicked.connect(self.on_reset_scan)
        self.btn_reset.setToolTip("Reset plots and scan history")
        layout_actions.addWidget(self.btn_reset)

        self.btn_export = QPushButton("Export Histogram CSV")
        self.btn_export.clicked.connect(self.on_export_csv)
        layout_actions.addWidget(self.btn_export)

        self.controls_layout.addWidget(grp_actions)

        # --- Plot Options ---
        grp_opts = QGroupBox("Plot Options")
        layout_opts = QVBoxLayout()
        grp_opts.setLayout(layout_opts)

        self.chk_rate = QCheckBox("Event Rate vs Time")
        self.chk_rate.setChecked(True)
        self.chk_rate.toggled.connect(self.rebuild_plots)
        layout_opts.addWidget(self.chk_rate)

        self.chk_scan = QCheckBox("Scan Results (Rate vs WN)")
        self.chk_scan.setChecked(True)
        self.chk_scan.toggled.connect(self.rebuild_plots)
        layout_opts.addWidget(self.chk_scan)

        self.chk_laser = QCheckBox("Measured & Target WN vs Time")
        self.chk_laser.toggled.connect(self.rebuild_plots)
        layout_opts.addWidget(self.chk_laser)

        self.chk_volt = QCheckBox("Voltage vs Time")
        self.chk_volt.toggled.connect(self.rebuild_plots)
        layout_opts.addWidget(self.chk_volt)

        self.controls_layout.addWidget(grp_opts)

        # --- Status ---
        grp_status = QGroupBox("Status")
        layout_status = QVBoxLayout()
        grp_status.setLayout(layout_status)

        self.lbl_progress = QLabel("Progress: Idle")
        layout_status.addWidget(self.lbl_progress)

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

        self.controls_layout.addWidget(grp_status)
        self.controls_layout.addStretch()

    def _init_plots(self):
        self.fig = Figure(figsize=(5, 6), dpi=100)
        self.canvas = FigureCanvas(self.fig)
        self.plots_layout.addWidget(self.canvas)

        self.axes = {}
        self.lines = {}
        self.rebuild_plots()

    def rebuild_plots(self):
        self.fig.clf()
        self.axes = {}
        self.lines = {}

        active_plots = []
        if self.chk_rate.isChecked(): active_plots.append('rate')
        if self.chk_scan.isChecked(): active_plots.append('scan')
        if self.chk_laser.isChecked(): active_plots.append('laser')
        if self.chk_volt.isChecked(): active_plots.append('volt')

        num_plots = len(active_plots)
        if num_plots == 0:
            self.canvas.draw()
            return

        for i, name in enumerate(active_plots):
            ax = self.fig.add_subplot(num_plots, 1, i+1)
            self.axes[name] = ax

            if name == 'rate':
                ax.set_title("Total Event Rate")
                ax.set_ylabel("CPS")
                self.lines['rate'], = ax.plot([], [], 'g-')
                ax.grid(True)
            elif name == 'scan':
                ax.set_title("Scan Results: Events/Bin")
                ax.set_xlabel("Wavenumber (cm^-1)")
                ax.set_ylabel("Rate (cps)")
                self.lines['scan'], = ax.plot([], [], 'b-o')
                self.lines['scan_cursor'], = ax.plot([], [], 'ro')
                ax.grid(True)
            elif name == 'laser':
                ax.set_title("Wavenumber vs Time")
                ax.set_ylabel("Wavenumber (cm^-1)")
                self.lines['laser_curr'], = ax.plot([], [], 'r-', label='Measured (WM)')
                self.lines['laser_target'], = ax.plot([], [], 'k--', label='Target')
                ax.legend(loc='upper right')
                ax.grid(True)
            elif name == 'volt':
                ax.set_title("Voltage vs Time")
                ax.set_ylabel("Voltage (V)")
                self.lines['volt'], = ax.plot([], [], 'm-')
                ax.grid(True)

        self.fig.tight_layout()
        self.canvas.draw()

    def on_start_scan(self):
        try:
            min_wn = self.spin_min_wn.value()
            max_wn = self.spin_max_wn.value()
            step_size = self.spin_step.value()
            stop_val = self.spin_stop_val.value()

            mode_idx = self.combo_mode.currentIndex()
            stop_mode = 'bunches' if mode_idx == 0 else 'time'

            # Snapshot of parameters
            self.active_scan_params = {
                "Min WN": f"{min_wn:.2f} cm^-1",
                "Max WN": f"{max_wn:.2f} cm^-1",
                "Step": f"{step_size:.2f} cm^-1",
                "Mode": stop_mode,
                "Value": f"{stop_val}"
            }

            self.daq.start_scan(min_wn, max_wn, step_size, stop_mode, stop_val)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def on_stop_scan(self):
        # Non-blocking stop to prevent GUI freeze
        self.daq.scanner.stop(wait=False)
        self.btn_stop.setEnabled(False)
        self.lbl_progress.setText("Status: Stopping...")

    def on_pause_scan(self):
        status = self.daq.scanner.get_status()
        if status['is_paused']:
            self.daq.scanner.resume()
        else:
            self.daq.scanner.pause()

    def on_reset_scan(self):
        # 1. Check if running
        status = self.daq.scanner.get_status()
        if status['is_running']:
             res = QMessageBox.question(self, "Stop and Reset?",
                                        "Scan is currently running.\nDo you want to stop the scan and reset all history?",
                                        QMessageBox.Yes | QMessageBox.No)
             if res != QMessageBox.Yes:
                 return

             # Stop and wait
             self.daq.scanner.stop(wait=True)

        # 2. Check if there is anything to reset (if we just stopped, there is data)
        # ... logic continues or we just force reset

        # If we just stopped, we definitely want to reset.
        # If we were idle, we check if there's data.

        has_data = (bool(self.daq.scanner.scan_progress) or
                    len(self.time_history) > 0 or
                    len(self.wn_history) > 0 or
                    len(self.rate_history) > 0)

        # If we were idling and no data, confirm? Or just return?
        if not status['is_running'] and not has_data:
             return

        # If we didn't already confirm (i.e. we were idle), confirm now
        if not status['is_running']:
            res = QMessageBox.question(self, "Confirm Reset",
                                       "Are you sure you want to reset scan and plot history?",
                                       QMessageBox.Yes | QMessageBox.No)
            if res != QMessageBox.Yes:
                return

        self.daq.scanner.reset()

        # Clear all histories
        self.time_history.clear()
        self.rate_history.clear()
        self.wn_history.clear()
        self.target_wn_history.clear()
        self.volt_history.clear()

        # Reset start time so plots start from t=0
        self.start_time = time.time()
        self.daq.event_timestamps.clear()

        if 'scan' in self.lines:
            self.lines['scan'].set_data([], [])
        self.canvas.draw()

    def on_export_csv(self):
        scan_data = self.daq.scanner.scan_progress
        if not scan_data:
            QMessageBox.warning(self, "Warning", "No scan data.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV Files (*.csv)")
        if path:
            try:
                with open(path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Wavenumber_cm-1", "Rate_cps"])
                    writer.writerows(scan_data)
                QMessageBox.information(self, "Success", f"Exported {len(scan_data)} points.")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def update_gui(self):
        current_time = time.time() - self.start_time
        rate = self.daq.get_instant_rate()

        status = self.daq.scanner.get_status()
        target_wn = status['target_wn']
        measured_wn = status['measured_wn']

        volt_val = self.daq.multimeter.getVoltage()

        self.time_history.append(current_time)
        self.rate_history.append(rate)
        self.wn_history.append(measured_wn)
        self.target_wn_history.append(target_wn)
        self.volt_history.append(volt_val)

        times = list(self.time_history)

        # Plot Updates
        if 'rate' in self.lines:
            self.lines['rate'].set_data(times, list(self.rate_history))
            ax = self.axes['rate']
            ax.set_xlim(max(0, times[-1] - 10), times[-1] + 1)
            valid_rates = [r for r in self.rate_history if r is not None]
            if valid_rates:
                ax.set_ylim(0, max(max(valid_rates), 10) * 1.2)

        if 'scan' in self.lines:
            scan_data = self.daq.scanner.scan_progress
            if scan_data:
                wls, rates = zip(*scan_data)
                self.lines['scan'].set_data(wls, rates)
                ax = self.axes['scan']
                ax.set_xlim(min(wls)-0.1, max(wls)+0.1)
                if rates:
                    ax.set_ylim(0, max(rates) * 1.2)
            self.lines['scan_cursor'].set_data([status['target_wn']], [0])

        if 'laser_curr' in self.lines:
            self.lines['laser_curr'].set_data(times, list(self.wn_history))
            self.lines['laser_target'].set_data(times, list(self.target_wn_history))
            ax = self.axes['laser']
            ax.set_xlim(max(0, times[-1] - 10), times[-1] + 1)
            all_wns = [w for w in (list(self.wn_history) + list(self.target_wn_history)) if w > 0]
            if all_wns:
                min_y, max_y = min(all_wns), max(all_wns)
                span = max_y - min_y
                if span < 0.1: span = 1.0
                ax.set_ylim(min_y - span*0.2, max_y + span*0.2)

        if 'volt' in self.lines:
            self.lines['volt'].set_data(times, list(self.volt_history))
            ax = self.axes['volt']
            ax.set_xlim(max(0, times[-1] - 10), times[-1] + 1)
            all_volts = list(self.volt_history)
            if all_volts:
                min_v, max_v = min(all_volts), max(all_volts)
                v_span = max_v - min_v
                if v_span < 0.1: v_span = 0.1
                ax.set_ylim(min_v - v_span*0.2, max_v + v_span*0.2)

        self.canvas.draw_idle()

        # Status Label Updates
        self.lbl_status_wn.setText(f"Measured: {measured_wn:.4f} cm^-1\nTarget: {target_wn:.4f} cm^-1")

        if status['is_running']:
            self.btn_start.setEnabled(False)
            # self.btn_reset.setEnabled(False) # Now always enabled
            self.btn_stop.setEnabled(True)
            self.btn_pause.setEnabled(True)

            if status['is_paused']:
                self.btn_pause.setText("Resume Scan")
                self.lbl_progress.setText("Status: Paused")
            else:
                self.btn_pause.setText("Pause Scan")
                self.btn_pause.setText("Pause Scan")
                if status.get('is_stopping', False):
                    self.lbl_progress.setText("Status: Stopping...")
                else:
                    self.lbl_progress.setText(f"Status: Scanning Bin {status['bin_index']}/{status['total_bins']}")

            if status['eta_seconds'] > 0:
                mins = int(status['eta_seconds'] // 60)
                secs = int(status['eta_seconds'] % 60)
                self.lbl_eta.setText(f"ETA: {mins}m {secs}s")
            else:
                self.lbl_eta.setText("ETA: Calculating...")

            if status['total_bins'] > 0:
                pct = int((status['bins_completed'] / status['total_bins']) * 100)
                self.progress_bar.setValue(pct)

            # Bin Progress
            if status['stop_value'] > 0:
                if status['stop_mode'] == 'events':
                     bin_pct = (status['accumulated'] / status['stop_value']) * 100
                     self.bin_progress.setValue(int(min(bin_pct, 100)))
                elif status['stop_mode'] == 'bunches':
                     bin_pct = (status['accumulated_bunches'] / status['stop_value']) * 100
                     self.bin_progress.setValue(int(min(bin_pct, 100)))
                else:
                     self.bin_progress.setValue(0)

            # Update Tooltip with active params
            if hasattr(self, 'active_scan_params'):
                info_text = "<b>Current Scan Parameters:</b><br>"
                info_text += "<br>".join([f"• {k}: {v}" for k, v in self.active_scan_params.items()])
                self.lbl_scan_info.setToolTip(info_text)

            # Lockdown params
            for w in self.param_widgets:
                w.setEnabled(False)

        else:
            self.btn_start.setEnabled(True)
            self.btn_reset.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_pause.setEnabled(False)
            self.btn_pause.setText("Pause Scan")
            self.lbl_progress.setText("Status: Idle")
            self.lbl_eta.setText("ETA: --")
            self.progress_bar.setValue(0)
            self.bin_progress.setValue(0)

            # Reset Tooltip & Params
            self.lbl_scan_info.setToolTip("No active scan")
            for w in self.param_widgets:
                w.setEnabled(True)

    def closeEvent(self, event):
        self.daq.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # DAQ
    daq = DAQSystem()
    daq.start()

    window = MainWindow(daq)
    window.show()

    sys.exit(app.exec_())
