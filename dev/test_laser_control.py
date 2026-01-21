import time
import sys
import unittest

# Ensure src is in path
sys.path.append('.')

from src.simulation.hardware_mocks import MockPIGCSDevice, MockEpicsClient
from src.control.laser_controller import LaserController

class TestLaserController(unittest.TestCase):
    def setUp(self):
        self.device = MockPIGCSDevice("TEST_PI")
        self.device.SVO(1, 1) # Enable Servo
        self.epics = MockEpicsClient(self.device)
        self.controller = LaserController(self.device, self.epics)

    def test_wavenumber_conversion(self):
        """Test the mock physics: WN = 12000 + 100 * Pos"""
        self.device.position[1] = 10.0
        wn = self.epics.caget("wavenumber")
        correction = 12000 + 100 * 10
        self.assertAlmostEqual(wn, correction, delta=0.5) # Noise allowed

    def test_control_loop(self):
        """Test that the controller drives the motor to the target WN."""
        target = 13000.0

        print(f"\n[Test] Setting Target to {target} cm^-1")
        self.controller.set_wavenumber(target)

        # Wait for stability (max 30s)
        start = time.time()
        while time.time() - start < 30:
            if self.controller.is_stable():
                print("[Test] Stable!")
                break
            time.sleep(0.5)
            wn = self.controller.get_wavenumber()
            pos = self.device.qPOS(1)[1]
            print(f"[Monitor] WN: {wn:.2f}, Pos: {pos:.2f}")

        self.assertTrue(self.controller.is_stable(), "Controller did not reach stable target in time.")
        final_wn = self.controller.get_wavenumber()
        self.assertAlmostEqual(final_wn, target, delta=0.02)
        print(f"[Test] Final WN: {final_wn}")
        self.controller.stop()

if __name__ == '__main__':
    unittest.main()
