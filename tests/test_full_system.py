import unittest
import time
import os
import sys
import threading

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dev.daq_scanner_gui_tk import DAQSystem

class TestFullSystem(unittest.TestCase):
    def setUp(self):
        # Use a separate test log
        self.original_saver_path = "data/scan_log.csv"
        # Since DAQSystem hardcodes path in init, we might need to patch it or just let it write and clean up
        # We'll just let it write to data/scan_log.csv but back it up if needed.

        self.daq = DAQSystem()
        self.daq.saver.filename = "tests/data/integration_test.csv"
        os.makedirs("tests/data", exist_ok=True)
        if os.path.exists(self.daq.saver.filename):
            os.remove(self.daq.saver.filename)

        self.daq.start()

    def tearDown(self):
        self.daq.stop()
        # Give threads time to die
        if self.daq.daq_thread.is_alive():
            self.daq.daq_thread.join(timeout=1.0)

    def test_full_scan_execution(self):
        """Run a 3-bin scan and verify everything ties together."""

        # Configure short scan
        self.daq.start_scan(min_wl=600.0, max_wl=600.2, step=0.1, stop_mode='time', stop_value=0.5)

        # Wait for Scanner to finish
        start = time.time()
        while self.daq.scanner.is_alive():
            time.sleep(0.5)
            if time.time() - start > 10:
                self.fail("Scan timed out")

        # Verify Results
        scan_data = self.daq.scanner.scan_progress
        self.assertEqual(len(scan_data), 3, "Should have 3 bins (600.0, 600.1, 600.2)")

        # Verify CSV
        self.assertTrue(os.path.exists(self.daq.saver.filename))
        with open(self.daq.saver.filename, 'r') as f:
            lines = f.readlines()

        self.assertGreater(len(lines), 1, "Should have header + data")
        print(f"\n[Integration] Collected {len(lines)-1} events.")

if __name__ == '__main__':
    unittest.main()
