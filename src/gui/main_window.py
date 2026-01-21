import time
from collections import deque
from PyQt5.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter)
from PyQt5.QtCore import QTimer, Qt

from src.utils.settings_manager import SettingsManager
from src.gui.widgets.params_widget import ParamsWidget
from src.gui.widgets.actions_widget import ActionsWidget
from src.gui.widgets.status_widget import StatusWidget
from src.gui.widgets.plot_widget import PlotWidget
from src.gui.widgets.plot_options_widget import PlotOptionsWidget

class MainWindow(QMainWindow):
    def __init__(self, daq_system):
        super().__init__()
        self.daq = daq_system
        # Use settings from DAQ system if available, else load new
        if hasattr(self.daq, 'config') and self.daq.config:
            self.settings_manager = SettingsManager() # We still need the manager to save
            self.settings_manager.settings = self.daq.config
        else:
            self.settings_manager = SettingsManager()

        self.scan_settings = self.settings_manager.get_section("scan_settings")

        self.setWindowTitle("DAQ Scanner Control (PyQt5) - Modular")
        self.resize(1200, 800)

        self._init_ui()
        self._init_logic()

    def _init_ui(self):
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

        # Widgets
        self.params_widget = ParamsWidget(settings_config=self.scan_settings)
        self.actions_widget = ActionsWidget()
        self.plot_options_widget = PlotOptionsWidget()
        self.status_widget = StatusWidget()

        self.controls_layout.addWidget(self.params_widget)
        self.controls_layout.addWidget(self.actions_widget)
        self.controls_layout.addWidget(self.plot_options_widget)
        self.controls_layout.addWidget(self.status_widget)
        self.controls_layout.addStretch()

        splitter.addWidget(self.controls_widget)

        # Plots (Right)
        self.plot_widget = PlotWidget()
        splitter.addWidget(self.plot_widget)
        splitter.setStretchFactor(1, 4) # Plots take more space

    def _init_logic(self):
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

        # Connections
        self.actions_widget.start_requested.connect(self.on_start)
        self.actions_widget.pause_requested.connect(self.on_pause)
        self.actions_widget.stop_requested.connect(self.on_stop)
        self.actions_widget.reset_requested.connect(self.on_reset)
        self.actions_widget.export_requested.connect(self.on_export)

        # Connect settings from ParamsWidget
        self.params_widget.settings_requested.connect(self.on_settings)

        # Plot Options connection
        self.plot_options_widget.options_changed.connect(self.plot_widget.set_active_plots)
        self.plot_options_widget.options_changed.connect(self.plot_widget.set_active_plots)
        # Initialize plot widget with default options
        self.plot_widget.set_active_plots(self.plot_options_widget.get_options())

    def on_start(self):
        params = self.params_widget.get_params()

        try:
            self.daq.start_scan(
                params['min_wn'],
                params['max_wn'],
                params['step_size'],
                params['stop_mode'],
                params['stop_val']
            )
            # Store formatted params for display
            self.active_display_params = params['display']

            # Format text for tooltip
            info_text = "<b>Current Scan Parameters:</b><br>"
            info_text += "<br>".join([f"• {k}: {v}" for k, v in self.active_display_params.items()])
            self.current_info_text = info_text

            # Update settings with last used values
            self.scan_settings.update({
                'min_wn': params['min_wn'],
                'max_wn': params['max_wn'],
                'step_size': params['step_size'],
                'stop_mode': params['stop_mode'],
                'stop_val': params['stop_val']
            })
            self.settings_manager.save_settings()

        except Exception as e:
            # In a real app we might show message box here, but let's just print
            print(f"Error starting scan: {e}")

    def on_stop(self):
        # Non-blocking stop
        self.daq.scanner.stop(wait=False)

    def on_pause(self):
        status = self.daq.scanner.get_status()
        if status['is_paused']:
            self.daq.scanner.resume()
        else:
            self.daq.scanner.pause()

    def on_reset(self):
        # Check if running handled by action widget mostly, but we need logic
        status = self.daq.scanner.get_status()

        # We need to stop first if running
        if status['is_running']:
             # In modular design, we might want to ask confirmation
             # For now, let's assume the user clicked the button which we can add confirmation to if needed
             # or just stop.
             # The original code asked for confirmation.
             self.daq.scanner.stop(wait=True)

        self.daq.scanner.reset()

        # Clear histories
        self.time_history.clear()
        self.rate_history.clear()
        self.wn_history.clear()
        self.target_wn_history.clear()
        self.volt_history.clear()

        # Reset start time
        self.start_time = time.time()
        self.daq.event_timestamps.clear()

        # Update plots immediately to clear
        self.plot_widget.rebuild_plots()

        # Clear active display params
        if hasattr(self, 'current_info_text'):
            del self.current_info_text

    def on_export(self):
        # Logic for export
        # We need to open a file dialog, which requires MainWindow as parent
        # We can implement it here or in actions widget but actions widget has emitted signal
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        import csv

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

    def on_settings(self):
        from src.gui.widgets.laser_control_dialog import LaserControlDialog

        # Get current control settings
        # We can refresh from settings manager or current DAQ state?
        # Safe to get from settings_manager as it should be sync'd or default
        control_section = self.settings_manager.get_section("control_settings")
        current_laser_settings = control_section.get("laser", {})

        dialog = LaserControlDialog(current_laser_settings, self)
        if dialog.exec_():
            new_settings = dialog.get_settings()

            # 1. Update DAQ Runtime
            self.daq.update_laser_settings(new_settings)

            # 2. Update Settings Manager and Save
            # Need to be careful not to overwrite other parts of control_settings if they exist
            # But here we know structure is simple
            control_section['laser'] = new_settings
            # Update the main settings object with modified section
            self.settings_manager.settings['control_settings'] = control_section
            self.settings_manager.save_settings()

            # Optional: Show status
            self.status_widget.update_status(self.daq.scanner.get_status(), "Laser Settings Updated.")

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

        # Determine info text
        if hasattr(self, 'current_info_text') and status['is_running']:
            info_text = self.current_info_text
        else:
            # If not running, show current pending params
            params = self.params_widget.get_params()
            display_params = params['display']
            info_text = "<b>Pending Scan Parameters:</b><br>"
            info_text += "<br>".join([f"• {k}: {v}" for k, v in display_params.items()])

        # Update Status Widget
        self.status_widget.update_status(status, info_text)

        # Update Actions Widget State
        self.actions_widget.update_state(status['is_running'], status['is_paused'])

        # Update Params Widget State
        self.params_widget.set_enabled(not status['is_running'])

        # Update Plots
        history = {
            'times': list(self.time_history),
            'rate': list(self.rate_history),
            'wn': list(self.wn_history),
            'target_wn': list(self.target_wn_history),
            'volt': list(self.volt_history),
            'scan_data': self.daq.scanner.scan_progress
        }
        self.plot_widget.update_plots(history)

    def closeEvent(self, event):
        self.daq.stop()
        event.accept()
