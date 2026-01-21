
import unittest
import time
import threading
from src.control.daq_system import DAQSystem
from src.simulation.hardware_mocks import MockPIGCSDevice, MockEpicsClient

class TestLaserSettingsUpdate(unittest.TestCase):
    def setUp(self):
        # Default config
        self.config = {
            "simulation_settings": {
                "laser": {"move_speed": 100.0},
                "epics": {"slope": 100.0, "offset": 12000.0}
            },
            "control_settings": {
                "laser": {
                    "tolerance": 0.01,
                    "step_fine": 0.0001,
                    "step_coarse": 0.05,
                    "poll_interval": 0.1
                }
            }
        }
        self.daq = DAQSystem(config=self.config)

    def test_runtime_update(self):
        """
        Test that updating settings at runtime changes the controller behavior.
        """
        # Start laser moving to a target
        # We need to run this in a thread or just check parameter values
        # checking parameter values is sufficient to verify the update mechanism

        # Initial check
        self.assertEqual(self.daq.laser.tolerance, 0.01)
        self.assertEqual(self.daq.laser.poll_interval, 0.1)

        # Update
        new_settings = {
            "tolerance": 0.05,
            "step_fine": 0.001,
            "step_coarse": 0.1,
            "poll_interval": 0.2
        }

        print("[TEST] Updating settings...")
        self.daq.update_laser_settings(new_settings)

        # Verify
        self.assertEqual(self.daq.laser.tolerance, 0.05)
        self.assertEqual(self.daq.laser.step_fine, 0.001)
        self.assertEqual(self.daq.laser.step_coarse, 0.1)
        self.assertEqual(self.daq.laser.poll_interval, 0.2)
        print("[TEST] Settings updated successfully verified on controller instance.")

    def tearDown(self):
        self.daq.stop()

if __name__ == "__main__":
    unittest.main()
