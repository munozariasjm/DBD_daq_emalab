
import unittest
import os
import json
import time
import glob
from src.control.daq_system import DAQSystem

class TestMetadataSave(unittest.TestCase):
    def setUp(self):
        # Ensure data dir exists
        if not os.path.exists("data"):
            os.makedirs("data")

        # Clean up old jsons to be sure
        for f in glob.glob("data/*_meta.json"):
            os.remove(f)

        self.daq = DAQSystem()
        self.daq.start()

    def test_metadata_creation(self):
        """
        Test that start_scan creates a metadata file with correct fields.
        """
        print("[TEST] Calling start_scan...")
        min_wn = 16000
        max_wn = 16100
        step = 10
        self.daq.start_scan(min_wn, max_wn, step, 'bunches', 100)

        # Give it a moment to write file (should be instant, but file system...)
        time.sleep(0.5)

        # Stop everything
        self.daq.stop()

        # Check files
        files = glob.glob("data/*_meta.json")
        self.assertTrue(len(files) > 0, "No metadata file created")

        latest_file = max(files, key=os.path.getctime)
        print(f"[TEST] Found metadata file: {latest_file}")

        with open(latest_file, 'r') as f:
            meta = json.load(f)

        # Verify content
        self.assertIn("timestamp", meta)
        self.assertIn("scan_parameters", meta)
        self.assertIn("laser_settings", meta)

        params = meta["scan_parameters"]
        self.assertEqual(params["min_wn"], min_wn)
        self.assertEqual(params["max_wn"], max_wn)

        print("[TEST] Metadata content verified.")

    def tearDown(self):
        self.daq.stop()

if __name__ == "__main__":
    unittest.main()
