import json
import csv
import os
import numpy as np

class DataLoader:
    def __init__(self):
        pass

    def load_scan(self, json_path):
        """
        Loads scan metadata from a JSON file and attempts to load the corresponding CSV data.
        Returns a tuple (metadata, processed_data).
        """
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"Metadata file not found: {json_path}")

        with open(json_path, 'r') as f:
            metadata = json.load(f)

        # Infer CSV path from JSON path pattern
        # Pattern: scan_TIMESTAMP_meta.json -> scan_TIMESTAMP.csv
        base_dir = os.path.dirname(json_path)
        filename = os.path.basename(json_path)

        if filename.endswith("_meta.json"):
            csv_filename = filename.replace("_meta.json", ".csv")
        else:
             # Fallback or strict requirement? Let's try to guess or just fail
             # For now, let's assume standard naming.
             raise ValueError("Invalid metadata filename format. Expected *_meta.json")

        csv_path = os.path.join(base_dir, csv_filename)

        if not os.path.exists(csv_path):
             # Try checking for final_scan_... too if needed, but per requirements, start with standard
             raise FileNotFoundError(f"Associated data file not found: {csv_path}")

        data = self.process_data(csv_path)
        return metadata, data

    def process_data(self, csv_path):
        """
        Parses the CSV file and reconstructs history arrays for plotting.
        """
        times = []
        wn_history = []
        target_wn_history = []
        volt_history = []
        rate_history = [] # This needs to be calculated from bunches

        tof_buffer = []

        # for scan results (Events/Bin vs Wavenumber)
        # We need to re-aggregate this.
        # The CSV has: timestamp, channel, tof, voltage, spectrum_peak, wavemeter_wn, laser_target_wn, scan_bin_index, bunch_id

        # We need to detect bunches to calculate rate.
        # Ideally, we can just replay the events.

        # Optimization: storing all events might be heavy for huge scans,
        # but for typical usage described, it should be fine.

        events_in_bunch = 0
        current_bunch_id = -1

        # We also need to map bin_index -> total events to reconstruct the scan plot
        bin_counts = {} # bin_index -> event count
        bin_wn_map = {} # bin_index -> wavenumber (approx)

        # To avoid reading whole file into memory at once if it's huge, we row-by-row.

        rows = []
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            # We might need to handle the header if it differs.
            # Looking at DataSaver, keys are consistent.

            start_time = None

            for row in reader:
                # Convert types
                ts = row['timestamp'] # String format logic?
                # Wait, DataSaver writes what?
                # It writes timestamp as... looking at daq_system.py line 213: timestamp is from tagger.
                # Tagger usually gives float seconds or similar. Let's assume float.

                try:
                    ts = float(ts)
                except ValueError:
                    # Maybe it's a string date?
                    # The simulator tagger uses time.time().
                    pass

                if start_time is None:
                    start_time = ts

                rel_time = ts - start_time

                channel = int(row['channel'])
                bunch_id = int(row['bunch_id'])

                # Rate Calculation logic:
                if bunch_id != current_bunch_id:
                    # End of previous bunch
                    if current_bunch_id != -1:
                         # Append rate for previous bunch
                         # Rate is events/bunch. For a single bunch, it's just count.
                         # But realistically, the plot shows average rate.
                         # For now, let's just log "1" for the bunch if we want per-bunch resolution,
                         # or we can smooth it later.
                         # Actually, the live plot calculates "instant rate" over a buffer.
                         # Here we can just store the count per bunch.
                         rate_history.append(events_in_bunch)
                         # We need a time point for this rate. Use the last event's time?
                         # Or just append to a list and align with time?
                         # Let's simplify: Rate plot usually shows Rate vs Time.
                         # We can sample every N bunches or just plot every bunch.
                         pass

                    current_bunch_id = bunch_id
                    events_in_bunch = 0

                    # Also Add time/volt/wn snapshots per bunch (or per event?)
                    # The sensor data is duplicated for every event in the bunch.
                    # We can just take it from the first entry of the bunch.

                    times.append(rel_time)
                    wn_history.append(float(row['wavemeter_wn']))
                    target_wn_history.append(float(row['laser_target_wn']))
                    volt_history.append(float(row['voltage']))


                if channel == 2: # Event
                    events_in_bunch += 1
                    tof = float(row['tof'])
                    tof_buffer.append(tof)

                    bin_idx = int(row['scan_bin_index'])
                    if bin_idx not in bin_counts:
                        bin_counts[bin_idx] = 0
                        bin_wn_map[bin_idx] = float(row['laser_target_wn']) # Use target for x-axis bin center
                    bin_counts[bin_idx] += 1

        # Reconstruct Scan Data (Wn, Rate)
        # Scan plot expects: list of (wavenumber, rate_events_per_bunch, ...)
        # Wait, the scan plot in plot_widget.py expects:
        # scan_data list of tuples.
        # In daq_system.py, scan_data is self.scanner.scan_progress.
        # Scanner calculates rate as: total_events / total_bunches for that bin.
        # We don't have total_bunches per bin easily unless we count empty bunches too.
        # The CSV *does* log empty bunches (channel -1) in DataSaver?

        # Let's check DataSaver usage in daq_system.py ...
        # Line 204: if channel == -1 (Empty Bunch): saver.add_event(...)
        # So yes, empty bunches are in the CSV!

        scan_data_map = {} # bin_index -> {'events': 0, 'bunches': 0, 'wn': 0.0}

        # Let's re-read carefully or do it in the first pass
        # Re-doing the pass logic above to be more precise for scan_data

        # Reset and do it properly in one pass
        times = []
        wn_history = []
        target_wn_history = []
        volt_history = []
        rate_history = []
        tof_buffer = []

        scan_bins = {} # idx -> {events, bunches, wn}

        current_bunch_id = -1
        events_in_current_bunch = 0
        is_empty_bunch = False

        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            start_time = None

            for row in reader:
                try:
                    ts = float(row['timestamp'])
                except:
                     continue

                if start_time is None: start_time = ts
                rel_time = ts - start_time

                bunch_id = int(row['bunch_id'])
                channel = int(row['channel'])
                bin_idx = int(row['scan_bin_index'])
                wn_target = float(row['laser_target_wn'])

                # Initialize bin tracking
                if bin_idx not in scan_bins:
                    scan_bins[bin_idx] = {'events': 0, 'bunches': 0, 'wn': wn_target}

                # Bunch transition logic
                if bunch_id != current_bunch_id:
                    # Finish previous bunch
                    if current_bunch_id != -1:
                        # Record 'rate' for the previous bunch (events per bunch = count)
                        rate_history.append(events_in_current_bunch)
                        # The time for this rate point was the previous row's time
                        times.append(last_rel_time)
                        wn_history.append(last_wn)
                        target_wn_history.append(last_target_wn)
                        volt_history.append(last_volt)

                        # Add to scan stats
                        if last_bin_idx in scan_bins:
                             scan_bins[last_bin_idx]['bunches'] += 1
                             scan_bins[last_bin_idx]['events'] += events_in_current_bunch

                    # Start new bunch
                    current_bunch_id = bunch_id
                    events_in_current_bunch = 0


                # Update current bunch data
                last_rel_time = rel_time
                last_wn = float(row['wavemeter_wn'])
                last_target_wn = wn_target
                last_volt = float(row['voltage'])
                last_bin_idx = bin_idx

                if channel == 2: # Event
                    events_in_current_bunch += 1
                    tof_buffer.append(float(row['tof']))
                elif channel == -1: # Empty
                    pass

            # Flush last bunch
            if current_bunch_id != -1:
                rate_history.append(events_in_current_bunch)
                times.append(last_rel_time)
                wn_history.append(last_wn)
                target_wn_history.append(last_target_wn)
                volt_history.append(last_volt)
                if last_bin_idx in scan_bins:
                        scan_bins[last_bin_idx]['bunches'] += 1
                        scan_bins[last_bin_idx]['events'] += events_in_current_bunch

        # Format scan_data for plot_widget
        # PlotWidget expects: [(wavenumber, rate, total_events, total_bunches), ...]
        # Rate = events / bunches

        final_scan_data = []
        # Sort by bin index to ensure order
        sorted_bins = sorted(scan_bins.keys())
        for idx in sorted_bins:
            b = scan_bins[idx]
            if b['bunches'] > 0:
                rate = b['events'] / b['bunches']
            else:
                rate = 0
            final_scan_data.append( (b['wn'], rate, b['events'], b['bunches']) )

        return {
            'times': times,
            'rate': rate_history,
            'wn': wn_history,
            'target_wn': target_wn_history,
            'volt': volt_history,
            'scan_data': final_scan_data,
            'tof_buffer': tof_buffer
        }
