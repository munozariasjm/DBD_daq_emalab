import sys
import os
import time
import threading
import numpy as np
from collections import deque
import csv
import json

from src.simulation.sim_tagger import MockTagger
from src.simulation.sim_sensors import MockMultimeter, MockSpectrometreReader, MockWavenumberReader

from src.simulation.hardware_mocks import MockMatisseDevice, MockEpicsClient
from src.control.laser_controller import LaserController
from src.control.data_saver import DataSaver
from src.control.scanner import Scanner

# Real Hardware Imports
from src.devices.tagger import Tagger
from src.devices.laser import MatisseDevice, ComClient
from src.devices.sensors import HP_Multimeter, SpectrometreReader, WavenumberReader, VoltageReader

class DAQSystem:
    def __init__(self, config=None):
        self.config = config or {}
        sim_config = self.config.get("simulation_settings", {})

        # Configuration extraction
        laser_sim_settings = sim_config.get("laser", {})
        epics_sim_settings = sim_config.get("epics", {})
        control_config = self.config.get("control_settings", {})
        laser_control_settings = control_config.get("laser", {})
        self.wavechannel = int(laser_control_settings.get("wavechannel", 1))

        # Safe-by-default: a missing `simulation_mode` key means real
        # hardware. The opposite default (True) silently puts the rig into
        # simulation on a fresh install or after a typo, which has caused
        # confusion before. Flag the absence loudly so the operator knows.
        if "simulation_mode" not in self.config:
            print("[DAQ] WARNING: 'simulation_mode' key missing from settings.json — "
                  "defaulting to REAL HARDWARE. Add the key explicitly to silence this.")
        simulation_mode = bool(self.config.get("simulation_mode", False))
        print(f"[DAQ] System Model: {'SIMULATION' if simulation_mode else 'REAL HARDWARE'}")

        if simulation_mode: # Simulation Mode
            self.tagger = MockTagger(initialization_params=sim_config.get("tagger", {}))

            merged_sim_params = dict(laser_sim_settings)
            merged_sim_params.update(epics_sim_settings)
            self.matisse_device = MockMatisseDevice(initialization_params=merged_sim_params)

            self.epics_client = MockEpicsClient(self.matisse_device, initialization_params=epics_sim_settings)

            self.multimeter = MockMultimeter("COM1", initialization_params=sim_config.get("multimeter", {}))
            self.spec_reader = MockSpectrometreReader()
            self.wave_reader = MockWavenumberReader(source=None)

        else: # Real Hardware
            print("Using real hardware")
            self.tagger = Tagger(index=0)

            self.matisse_device = MatisseDevice("Matisse")
            self.epics_client = ComClient(self.matisse_device, initialization_params=epics_sim_settings)

            self.hp_multimeter = HP_Multimeter(port="COM16")
            self.multimeter = VoltageReader(self.hp_multimeter)
            self.spec_reader = SpectrometreReader()
            self.wave_reader = WavenumberReader()

        self.laser = LaserController(self.matisse_device, self.epics_client, config=laser_control_settings)

        if simulation_mode:
            self.wave_reader.source = self.laser

        self.saver = None
        self.scanner = Scanner(self.laser, self.wave_reader, wavechannel=self.wavechannel)

        self.running = False
        self.events_processed = 0
        self.event_timestamps = deque(maxlen=1000)

        self.daq_thread = None

        self.pending_events_count = 0
        self.pending_bunches_count = 0
        self.rate_lock = threading.Lock()
        # First get_instant_rate() call after start() covers the entire
        # window between tagger.start_reading() and the first GUI poll —
        # many seconds of backlog. The events/bunches ratio is real but it's
        # plotted as a single point at t=0, which looks like a spike. Tare
        # the first sample to 0 so the rate plot only shows GUI-refresh-
        # window rates.
        self._rate_primed = False

        self.cached_voltage = 0.0
        self.cached_wavenumbers = [0.0] * 4
        self.cached_spectrum = 0.0
        self.sensor_lock = threading.Lock()

        self.last_scan_filename = None
        self.tof_online_mode = False

    def start(self):
        if self.running: return
        print("[DAQ] Starting system...")
        self.running = True
        self.tof_buffer = deque(maxlen=50000)
        # Reset the tare so a stop/start cycle re-primes the rate plot.
        with self.rate_lock:
            self.pending_events_count = 0
            self.pending_bunches_count = 0
        self._rate_primed = False

        self.spec_reader.start()
        self.multimeter.start()
        self.tagger.start_reading()

        self.daq_thread = threading.Thread(target=self._daq_loop, daemon=True)
        self.daq_thread.start()

    def stop(self):
        self.running = False
        print("[DAQ] Stopping system...")

        if self.scanner.is_alive():
            self.scanner.stop()

        if hasattr(self.laser, 'stop'):
            self.laser.stop()

        if self.saver:
            self.saver.stop()
            self.saver = None

        self.tagger.stop()
        self.spec_reader.stop()
        self.multimeter.stop()

    def start_scan(self, start_wn, end_wn, step, stop_mode, stop_value, loops=1):
        if not self.scanner.is_alive() and self.scanner.running == False:
            self.scanner = Scanner(self.laser, self.wave_reader, wavechannel=self.wavechannel)

        if self.scanner.is_alive():
             print("[DAQ] Scanner already running.")
             return

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename_csv = f"data/scan_{timestamp}.csv"
        self.last_scan_filename = filename_csv
        filename_meta = f"data/scan_{timestamp}_meta.json"
        filename_final = f"data/final_scan_{timestamp}.csv"

        data_settings = self.config.get("data_settings", {})
        save_continuously = data_settings.get("save_continuously", True)

        self.saver = DataSaver(
            filename_csv,
            save_continuously=save_continuously,
            final_filename=filename_final
        )
        self.saver.start()
        print(f"[DAQ] Started logging to {filename_csv} (Continuous: {save_continuously})")

        metadata = {
            "timestamp": timestamp,
            "scan_parameters": {
                "start_wn": start_wn,
                "end_wn": end_wn,
                "step_size": step,
                "stop_mode": stop_mode,
                "stop_value": stop_value,
                "loops": loops,
                "loops_completed": 0
            },
            "laser_settings": self.config.get("control_settings", {}).get("laser", {}),
            "simulation_settings": self.config.get("simulation_settings", {})
        }

        if hasattr(self.laser, 'config'):
             metadata["laser_settings"] = self.laser.config

        try:
            with open(filename_meta, 'w') as f:
                json.dump(metadata, f, indent=4)
            print(f"[DAQ] Saved metadata to {filename_meta}")
        except Exception as e:
            print(f"[DAQ] Failed to save metadata: {e}")

        self.scanner.configure(start_wn, end_wn, step, stop_mode, stop_value, loops, self._on_loop_complete)
        self.scanner.reset()
        self.tof_buffer = deque(maxlen=50000) # Clear buffer on new scan

        self.scanner.start()

    def _daq_loop(self):
        previous_bunch=-1
        previous_bunch2=-1
        while self.running:
            if self.saver and not self.scanner.running:
                print("[DAQ] Scan finished. Stopping saver.")
                self.saver.stop()
                self.saver = None

            data = self.tagger.get_data()
            # print(data)

            with self.sensor_lock:
                self.cached_voltage = self.multimeter.get_voltage()
                self.cached_spectrum = self.spec_reader.spectrum
                self.cached_wavenumbers = self.wave_reader.get_wavenumbers()

                current_voltage = self.cached_voltage
                current_spec = self.cached_spectrum
                current_wns = self.cached_wavenumbers

            for entry in data:
                channel = entry[2]
                timestamp = entry[0]

                if channel == -1: # Empty Bunch
                    with self.rate_lock:
                         self.pending_bunches_count += 1

                    if self.scanner.is_accumulating:
                         self.scanner.report_event(is_bunch=True)

                         if self.saver:
                             record = {
                                'timestamp': timestamp,
                                'channel': channel,
                                'tof': entry[3], # 0.0
                                'voltage': current_voltage,
                                'spectrum_peak': current_spec,
                                'wavemeter_wn': current_wns[int(self.wavechannel-1)],
                                'wavemeter_wn1': current_wns[0],
                                'wavemeter_wn2': current_wns[1],
                                'wavemeter_wn3': current_wns[2],
                                'wavemeter_wn4': current_wns[3],
                                'laser_target_wn': self.scanner.current_wavenumber,
                                'scan_bin_index': self.scanner.current_bin_index,
                                'bunch_id': entry[0] # Global ID from tagger
                            }
                             self.saver.add_event(record)

                if channel == 2:
                    self.events_processed += 1
                    self.event_timestamps.append(timestamp)

                    with self.rate_lock:
                         self.pending_events_count += 1
                         if entry[0] != previous_bunch:
                            self.pending_bunches_count += 1
                            previous_bunch = entry[0]

                    record = {
                        'timestamp': timestamp,
                        'channel': channel,
                        'tof': entry[3],
                        'voltage': current_voltage,
                        'spectrum_peak': current_spec,
                        'wavemeter_wn': current_wns[int(self.wavechannel-1)], # Native cm^-1
                        'wavemeter_wn1': current_wns[0],
                        'wavemeter_wn2': current_wns[1],
                        'wavemeter_wn3': current_wns[2],
                        'wavemeter_wn4': current_wns[3],
                        'laser_target_wn': self.scanner.current_wavenumber,
                        'scan_bin_index': self.scanner.current_bin_index,
                        'bunch_id': entry[0] # Global ID from tagger
                    }

                    if self.scanner.is_accumulating and self.saver:
                        self.saver.add_event(record)
                        self.tof_buffer.append(entry[3]) # entry[3] is ToF
                        self.scanner.report_event(is_bunch=False)
                        if entry[0] != previous_bunch2:
                            self.scanner.report_event(is_bunch=True)
                            previous_bunch2 = entry[0]
                    elif self.tof_online_mode:
                        self.tof_buffer.append(entry[3])

            time.sleep(self.config["gui_settings"]["refresh_rate_ms"]/1000)

    def update_laser_settings(self, new_config: dict):
        """
        Updates the laser control settings at runtime.
        """
        if hasattr(self.laser, 'update_config'):
             self.laser.update_config(new_config)

        if "wavechannel" in new_config:
            self.wavechannel = int(new_config["wavechannel"])
            self.scanner.set_wavechannel(self.wavechannel)
            print(f"[DAQ] Wavemeter Channel updated to {self.wavechannel}")

        print("[DAQ] Laser settings updated.")


    def get_instant_rate(self):
        """
        Returns the event rate in Events Per Bunch, averaged since the last call.

        The first call after start() is discarded (returns 0): it would cover
        the multi-second window between tagger.start_reading() and the first
        GUI poll, which gets plotted as a single point at t=0 and looks like
        a spike (e.g. ~100 epb on a beam with high event multiplicity).
        Subsequent calls cover the GUI refresh interval (~100 ms) and reflect
        the current rate accurately.
        """
        with self.rate_lock:
             events = self.pending_events_count
             bunches = self.pending_bunches_count

             self.pending_events_count = 0
             self.pending_bunches_count = 0

        if not self._rate_primed:
            self._rate_primed = True
            return 0.0

        if bunches > 0:
            return events / bunches
        return 0.0

    def get_latest_voltage(self):
        with self.sensor_lock:
            return self.cached_voltage

    def get_latest_wavenumbers(self):
        with self.sensor_lock:
            return list(self.cached_wavenumbers)

    def get_latest_spectrum(self):
        with self.sensor_lock:
            return self.cached_spectrum

    def _on_loop_complete(self, loop_number):
        """Callback from scanner when a loop finishes."""
        print(f"[DAQ] Loop {loop_number} complete. Saving snapshot.")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"data/scan_snapshot_loop_{loop_number}_{timestamp}.csv"

        try:
            scan_data = self.scanner.scan_progress
            if not scan_data:
                return

            with open(filename, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Wavenumber_cm-1", "Rate_events_per_bunch", "Total_Events", "Total_Bunches"])
                writer.writerows(scan_data)
            print(f"[DAQ] Snapshot saved to {filename}")
        except Exception as e:
            print(f"[DAQ] Failed to save snapshot: {e}")
