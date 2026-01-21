import unittest
import time
import os
import shutil
import queue
import csv
import sys

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.control.data_saver import DataSaver

class TestDataSaver(unittest.TestCase):
    def setUp(self):
        self.test_file = "tests/data/test_log.csv"
        # Ensure dir
        os.makedirs(os.path.dirname(self.test_file), exist_ok=True)
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

        self.saver = DataSaver(self.test_file, flush_interval=0.1)
        self.saver.start()

    def tearDown(self):
        self.saver.stop()
        if os.path.exists(self.test_file):
            os.remove(self.test_file)
        if os.path.exists("tests/data"):
            os.rmdir("tests/data")

    def test_save_correctness(self):
        """Verify data is written to valid CSV."""
        events = [
            {'time': 1.0, 'val': 10},
            {'time': 2.0, 'val': 20}
        ]

        for e in events:
            self.saver.add_event(e)

        # Wait for flush
        time.sleep(0.5)

        self.assertTrue(os.path.exists(self.test_file))

        with open(self.test_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['val'], '10')
        self.assertEqual(rows[1]['val'], '20')

    def test_high_volume(self):
        """Stress test with many events."""
        count = 5000
        for i in range(count):
            self.saver.add_event({'id': i, 'data': 'x'*10})

        # Give it time to process
        time.sleep(1.0) # Should be enough for modest IO, or wait loop

        # Stop will force flush
        self.saver.stop()

        with open(self.test_file, 'r') as f:
            lines = f.readlines()

        # Header + Count lines
        self.assertEqual(len(lines), count + 1)

if __name__ == '__main__':
    unittest.main()
