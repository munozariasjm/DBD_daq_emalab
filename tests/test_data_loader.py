import unittest
import os
import json
import csv
import shutil
import tempfile
import sys

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.utils.data_loader import DataLoader

class TestDataLoader(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.loader = DataLoader()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_load_scan(self):
        # Create dummy data
        timestamp = "20250101_120000"
        json_path = os.path.join(self.test_dir, f"scan_{timestamp}_meta.json")
        csv_path = os.path.join(self.test_dir, f"scan_{timestamp}.csv")

        metadata = {
            "timestamp": timestamp,
            "scan_parameters": {"loops": 1}
        }
        with open(json_path, 'w') as f:
            json.dump(metadata, f)

        # Create dummy CSV
        # Headers: timestamp,channel,tof,voltage,spectrum_peak,wavemeter_wn,laser_target_wn,scan_bin_index,bunch_id
        headers = ["timestamp", "channel", "tof", "voltage", "spectrum_peak",
                   "wavemeter_wn", "laser_target_wn", "scan_bin_index", "bunch_id"]

        data_rows = []
        # Bunch 1 (Empty) - Bin 0
        data_rows.append([100.0, -1, 0.0, 1.0, 0.0, 1000.0, 1000.0, 0, 1])

        # Bunch 101 (Empty) - Bin 10
        data_rows.append([100.1, -1, 0.0, 5.0, 0.0, 1500.0, 1500.0, 10, 101])

        # Bunch 102 (1 Event) - Bin 10
        data_rows.append([100.2, 2, 123.4, 5.1, 0.0, 1500.1, 1500.0, 10, 102])

        # Bunch 103 (2 Events) - Bin 10
        data_rows.append([100.3, 2, 200.0, 5.2, 0.0, 1500.2, 1500.0, 10, 103])
        data_rows.append([100.3, 2, 210.0, 5.2, 0.0, 1500.2, 1500.0, 10, 103])

        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(data_rows)

        # Test loading
        loaded_meta, loaded_data = self.loader.load_scan(json_path)

        self.assertEqual(loaded_meta['timestamp'], timestamp)

        # Verify processed data
        rates = loaded_data['rate']
        self.assertEqual(len(rates), 4) # bunches 1, 101, 102, 103
        self.assertEqual(rates[0], 0) # Bunch 1 -> 0 events
        self.assertEqual(rates[1], 0) # Bunch 101 -> 0 events
        self.assertEqual(rates[2], 1) # Bunch 102 -> 1 event
        self.assertEqual(rates[3], 2) # Bunch 103 -> 2 events

        # Verify Scan Data (aggregated by bin)
        # We have Bin 0 (Bunch 1) and Bin 10 (Bunches 101, 102, 103)
        scan_data = loaded_data['scan_data']
        self.assertEqual(len(scan_data), 2)

        # Bin 0
        # scan_data is list of tuples: (wn, rate, events, bunches)
        self.assertEqual(scan_data[0][0], 1000.0) # Wavenumber
        self.assertEqual(scan_data[0][1], 0.0) # Rate
        self.assertEqual(scan_data[0][2], 0) # Events
        self.assertEqual(scan_data[0][3], 1) # Bunches

        # Bin 10
        self.assertEqual(scan_data[1][0], 1500.0) # Wavenumber (approx/target)
        self.assertEqual(scan_data[1][1], 1.0) # Rate
        self.assertEqual(scan_data[1][2], 3) # Events
        self.assertEqual(scan_data[1][3], 3) # Bunches

        print("Test Passed: DataLoader correctly parsed bunches and rates.")

if __name__ == '__main__':
    unittest.main()
