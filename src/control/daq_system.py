import sys
import os
import time
import threading
import numpy as np
from collections import deque
import csv
import json

# Add src to python path if needed, though usually handled by entry point
# But internal imports should work if run as module or with correct path

from src.simulation.sim_tagger import MockTagger
from src.simulation.sim_sensors import MockMultimeter, MockSpectrometreReader, MockWavenumberReader
from src.simulation.sim_laser import MockLaser
from src.simulation.hardware_mocks import MockPIGCSDevice, MockEpicsClient
from src.control.laser_controller import LaserController
from src.control.data_saver import DataSaver
from src.control.scanner import Scanner

class DAQSystem:
    def __init__(self, config=None):
        self.config = config or {}
        sim_config = self.config.get("simulation_settings", {})

        # Hardware
        self.tagger = MockTagger(initialization_params=sim_config.get("tagger", {}))

        laser_sim_settings = sim_config.get("laser", {})
        epics_sim_settings = sim_config.get("epics", {})

        control_config = self.config.get("control_settings", {})
        laser_control_settings = control_config.get("laser", {})

        self.pi_device = MockPIGCSDevice("Simulated_PI", initialization_params=laser_sim_settings)
        self.pi_device.SVO(1, 1) # Enable Servo for simulation

        self.epics_client = MockEpicsClient(self.pi_device, initialization_params=epics_sim_settings)

        # Initialize Controller
        self.laser = LaserController(self.pi_device, self.epics_client, config=laser_control_settings)

        self.multimeter = MockMultimeter("COM1", initialization_params=sim_config.get("multimeter", {}))
        self.spec_reader = MockSpectrometreReader()
        self.wave_reader = MockWavenumberReader(source=self.laser)

        # Services
        self.saver = None
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
        self.tof_buffer = []

        self.spec_reader.start()
        self.wave_reader.start()
        self.tagger.start_reading()
        # Saver is now started per scan

        self.daq_thread = threading.Thread(target=self._daq_loop, daemon=True)
        self.daq_thread.start()

    def stop(self):
        self.running = False
        print("[DAQ] Stopping system...")

        if self.scanner.is_alive():
            self.scanner.stop()

        # Stop Laser Controller
        if hasattr(self.laser, 'stop'):
            self.laser.stop()

        # Ensure saver is stopped if system stops
        if self.saver:
            self.saver.stop()
            self.saver = None

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

        # Start Saver with timestamp
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename_csv = f"data/scan_{timestamp}.csv"
        filename_meta = f"data/scan_{timestamp}_meta.json"

        self.saver = DataSaver(filename_csv)
        self.saver.start()
        print(f"[DAQ] Started logging to {filename_csv}")

        # Save Metadata
        metadata = {
            "timestamp": timestamp,
            "scan_parameters": {
                "min_wn": min_wn,
                "max_wn": max_wn,
                "step_size": step,
                "stop_mode": stop_mode,
                "stop_value": stop_value
            },
            "laser_settings": self.config.get("control_settings", {}).get("laser", {}),
            "simulation_settings": self.config.get("simulation_settings", {})
        }

        # We need to grab actual current laser settings if they were updated runtime
        if hasattr(self.laser, 'config'):
             metadata["laser_settings"] = self.laser.config

        try:
            with open(filename_meta, 'w') as f:
                json.dump(metadata, f, indent=4)
            print(f"[DAQ] Saved metadata to {filename_meta}")
        except Exception as e:
            print(f"[DAQ] Failed to save metadata: {e}")

        self.scanner.configure(min_wn, max_wn, step, stop_mode, stop_value)
        self.scanner.reset()
        self.tof_buffer = [] # Clear buffer on new scan

        self.scanner.start()

    def _daq_loop(self):
        while self.running:
            # Check if scanner finished naturally to stop saver
            if self.saver and not self.scanner.running:
                print("[DAQ] Scan finished. Stopping saver.")
                self.saver.stop()
                self.saver = None

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
                        'scan_bin_index': self.scanner.current_bin_index,
                        'bunch_id': self.scanner.accumulated_bunches
                    }

                    # Only save if accumulating AND saver is active
                    if self.scanner.is_accumulating and self.saver:
                        self.saver.add_event(record)
                        self.tof_buffer.append(entry[3]) # entry[3] is ToF
                        self.scanner.report_event(is_bunch=False)

            time.sleep(0.005)

    def update_laser_settings(self, new_config: dict):
        """
        Updates the laser control settings at runtime.
        """
        if hasattr(self.laser, 'update_config'):
             self.laser.update_config(new_config)
             print("[DAQ] Laser settings updated.")

    def get_instant_rate(self):
        if len(self.event_timestamps) < 2: return 0.0
        dt = self.event_timestamps[-1] - self.event_timestamps[0]
        if dt <= 0: return 0.0
        return len(self.event_timestamps) / dt
