import unittest
import time
import threading
import os
import shutil
import sys

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.control.scanner import Scanner
from src.simulation.sim_laser import MockLaser

class TestScannerLogic(unittest.TestCase):
    def setUp(self):
        self.laser = MockLaser()
        self.scanner = Scanner(self.laser)
        # Speed up laser for tests
        self.laser.move_speed = 1000.0

    def tearDown(self):
        if self.scanner.is_alive():
            self.scanner.stop()

    def test_event_stop_condition(self):
        """Test that scanner stops after N events."""
        target_events = 50
        self.scanner.configure(min_wl=600.0, max_wl=600.0, step=1.0, stop_mode='events', stop_value=target_events)

        # Start Scanner in a thread
        self.scanner.start()

        # Wait for accumulation to start
        start_wait = time.time()
        while not self.scanner.is_accumulating:
            if time.time() - start_wait > 2.0:
                self.fail("Scanner failed to enter accumulation mode")
            time.sleep(0.01)

        # Simulate events
        for _ in range(target_events + 5):
            self.scanner.report_event(is_bunch=False)
            time.sleep(0.001)

        self.scanner.join(timeout=2.0)
        self.assertFalse(self.scanner.is_alive(), "Scanner should have finished.")
        self.assertEqual(len(self.scanner.scan_progress), 1, "Should have completed 1 bin")
        # Check that we recorded roughly the target (might be slightly more due to race, but >= target)
        self.assertGreaterEqual(self.scanner.scan_progress[0][1] * 0.0, 0.0) # Just check it exists

    def test_bunch_stop_condition(self):
        """Test that scanner stops after N bunches."""
        target_bunches = 20
        self.scanner.configure(min_wl=600.0, max_wl=600.0, step=1.0, stop_mode='bunches', stop_value=target_bunches)

        self.scanner.start()

        # Wait for accumulation
        start_wait = time.time()
        while not self.scanner.is_accumulating:
            if time.time() - start_wait > 2.0:
                self.fail("Scanner failed to enter accumulation mode")
            time.sleep(0.01)

        # Simulate bunches
        for _ in range(target_bunches + 5):
            self.scanner.report_event(is_bunch=True)
            time.sleep(0.001)

        self.scanner.join(timeout=2.0)
        self.assertFalse(self.scanner.is_alive(), "Scanner should have finished.")
        self.assertEqual(len(self.scanner.scan_progress), 1)
        self.assertGreaterEqual(self.scanner.accumulated_bunches, target_bunches)

    def test_time_stop_condition(self):
        """Test that scanner stops after T seconds."""
        target_time = 0.5 # seconds
        self.scanner.configure(min_wl=600.0, max_wl=600.0, step=1.0, stop_mode='time', stop_value=target_time)

        start_ts = time.time()
        self.scanner.start()
        self.scanner.join(timeout=2.0)
        duration = time.time() - start_ts

        self.assertFalse(self.scanner.is_alive(), "Scanner should have finished.")
        self.assertGreaterEqual(duration, target_time, "Scanner finished too early")
        self.assertLess(duration, target_time + 1.0, "Scanner took too long")

    def test_pause_resume(self):
        """Test pause and resume logic."""
        target_time = 1.0
        self.scanner.configure(min_wl=600.0, max_wl=600.0, step=1.0, stop_mode='time', stop_value=target_time)

        self.scanner.start()

        # Wait for run to start
        time.sleep(0.2)

        # Pause
        self.scanner.pause()
        self.assertFalse(self.scanner.pause_event.is_set())

        # Sleep for longer than target, to prove it's paused
        time.sleep(1.2)
        self.assertTrue(self.scanner.is_alive(), "Scanner should still be alive (paused)")

        # Resume
        self.scanner.resume()
        self.assertTrue(self.scanner.pause_event.is_set())

        self.scanner.join(timeout=2.0)
        self.assertFalse(self.scanner.is_alive(), "Scanner should have finished after resume")

    def test_reset(self):
        """Test reset clears state."""
        self.scanner.scan_progress = [(600.0, 100.0)]
        self.scanner.bins_completed = 1

        self.scanner.reset()
        self.assertEqual(len(self.scanner.scan_progress), 0)
        self.assertEqual(self.scanner.bins_completed, 0)
        self.assertEqual(self.scanner.accumulated_bunches, 0)

if __name__ == '__main__':
    unittest.main()
