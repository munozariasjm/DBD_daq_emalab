import time
import threading
from src.simulation.hardware_mocks import MockPIGCSDevice, MockEpicsClient

# # Helper to mimic pitools.waitontarget equivalent
# def wait_on_target(device, axis, poll_interval=1):
#     """
#     Simulates pitools.waitontarget.
#     In the mock, we just check if position == target.
#     """
#     while True:
#         try:
#             # Check if moving
#             # For our simplified mock, we can check position vs target
#             pos = device.qPOS(axis)[axis]
#             # device.MOV updates target immediately, but physics updates pos over time
#             # We don't have direct access to target_pos in this helper easily unless we expose it
#             # But the mock updates instantly if we don't call update_physics manually loop

#             # Actually, standard waitontarget checks the "IsMoving" status bit usually.
#             # Our mock doesn't implement IsMoving fully, but let's assume if pos is close to last set target.
#             # Better: let's trust the device physics simulation time.

#             # In real script: pitools.waitontarget(pidevice, axes=1)
#             time.sleep(poll_interval)

#             # For the mock, we can check velocity or just wait a bit.
#             # Let's rely on the mock's physics being "reasonably fast" relative to this loop
#             # or check if it matches target.
#             # Since we can't easily access target without private access, let's just sleep.
#             # The real script waits for servo settling.
#             break
#         except Exception:
#              break

class LaserController:
    """
    Encapsulates the logic from the 'go_to' script to control the Laser
    via a PI Stage and a Wavemeter (EPICS).
    """
    def __init__(self, pi_device, epics_client, axis=1, config: dict = {}):
        self.device = pi_device
        self.epics = epics_client
        self.axis = axis
        self.config = config

        # Control Loop Parameters
        self.tolerance = self.config.get("tolerance", 0.01)
        self.step_fine = self.config.get("step_fine", 0.0001)
        self.step_coarse = self.config.get("step_coarse", 0.05)
        self.poll_interval = self.config.get("poll_interval", 1)
        self.coarse_approach_thresh = self.config.get("coarse_approach_threshold", 1.0)

        self.target_wn = 0.0
        self.current_wn = 0.0
        self.is_moving = False

        # Threading for the control loop
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.control_thread = None

        # Calibration / Initial Guess (from script or manual)
        # Script uses relative moves mainly, but we need an initial guess for the first move?
        # The script does:
        # while wn <= target - 0.01 or wn >= target + 0.01: ...

    def update_config(self, config: dict):
        """
        Updates the control loop parameters at runtime.
        """
        with self.lock:
            self.config.update(config)
            self.tolerance = self.config.get("tolerance", 0.01)
            self.step_fine = self.config.get("step_fine", 0.0001)
            self.step_coarse = self.config.get("step_coarse", 0.05)
            self.poll_interval = self.config.get("poll_interval", 0.5)
            self.coarse_approach_thresh = self.config.get("coarse_approach_threshold", 1.0)
            print(f"[LaserController] Config updated: tol={self.tolerance}, poll={self.poll_interval}")

    def set_wavenumber(self, target_wn):
        """
        Starts the background control loop to reach target_wn.
        """
        with self.lock:
            self.target_wn = target_wn
            self.stop_event.clear()

            if self.control_thread and self.control_thread.is_alive():
                 # Already running, just updated target
                 pass
            else:
                 self.is_moving = True
                 self.control_thread = threading.Thread(target=self._control_loop, daemon=True)
                 self.control_thread.start()

    def get_wavenumber(self):
        """
        Returns the current wavenumber from EPICS.
        """
        return float(self.epics.caget('LaserLab:wavenumber_3'))

    def is_stable(self, tolerance=None):
        """
        Returns True if current WN is within tolerance of Target WN.
        """
        if tolerance is None:
             tolerance = self.tolerance

        wn = self.get_wavenumber()
        return abs(wn - self.target_wn) < tolerance and not self.is_moving

    def stop(self):
        self.stop_event.set()
        if self.control_thread:
            self.control_thread.join()

    def _control_loop(self):
        """
        The logic from 'go_to' script.
        """
        print(f"[LaserController] Starting control loop for Target {self.target_wn}")
        # try:
        # 1. Read initial state
        wn = self.get_wavenumber()
        position = self.device.qPOS(self.axis)[self.axis]
        time.sleep(1)
        print(position)
        prevpos = position

        # 2. Loop until tolerance met
        while (wn <= self.target_wn - self.tolerance or wn >= self.target_wn + self.tolerance) and not self.stop_event.is_set():

            # Logic from script:
            # if wn <= target - 0.01:
            #     if position+0.0001!=prevpos:
            #         pidevice.MOV(1, position + 0.0001)
            #     else:
            #         pidevice.MOV(1, position - 0.05)
            # else:
            #     if position-0.0001!=prevpos:
            #         pidevice.MOV(1, position - 0.0001)
            #     else:
            #         pidevice.MOV(1, position + 0.05)

            # ADAPTATION: The script uses hardcoded 0.05 and 0.0001 steps.
            # It seems to try small steps, but if stuck (pos == prevpos), it does a large jump?
            # Or maybe it's just coarse/fine logic.

            # NOTE: The script logic `if position+0.0001!=prevpos` is weird.
            # Ideally `position` is current, `prevpos` is from last loop.
            # If we moved, they should be different.
            # If they are same, maybe we are stuck or step was too small?

            step_fine = self.step_fine
            step_coarse = self.step_coarse

            move_cmd = 0.0

            if wn <= self.target_wn - self.tolerance:
                # Nead to increase WN -> Increase Position (assuming positive slope)
                # Script logic:
                if abs((position + step_fine) - prevpos) > 1e-9: # effectively !=
                        move_cmd = position + step_fine
                else:
                        move_cmd = position - step_coarse # Back off?
            else:
                # Need to decrease WN
                if abs((position - step_fine) - prevpos) > 1e-9:
                    move_cmd = position - step_fine
                else:
                    move_cmd = position + step_coarse

            # Optimization: If we are FAR away, the script's linear +/- 0.0001 is very slow.
            # The script provided seems to be a "fine tuning" script ("go_to").
            # Real usage might involve a coarse move first?
            # For this task, I should STICK TO THE SCRIPT LOGIC as requested ("get closer to actual data format").
            # BUT, if I start 1000 nm away,0.0001 steps take forever.
            # Let's add a "Course Approach" if diff is large, or assume we are close.
            # Since the simulation can start anywhere, let's add a proportional term if very far.

            # diff_wn = self.target_wn - wn
            # if abs(diff_wn) > self.coarse_approach_thresh:
            #     # Use a rough estimate to get closer faster
            #     # Guess slope approx 100 wn / mm
            #     correction = diff_wn / 100.0
            #     move_cmd = position + correction
            #     print(f"[LaserController] Coarse move: {correction:.4f}")

            # Execute Move
            self.device.MOV(self.axis, move_cmd)
            # print(move_cmd)
            # Wait
            # pitools.waitontarget(pidevice,axes=1) -> mimicked by sleep
            # self.device.proxy.ServerWaitOnTarget(1)
            # print("imoved")
            # self.device.waitontarget(self.axis)
            time.sleep(1)

            # Update Loop State
            prevpos = position
            position = self.device.qPOS(self.axis)[self.axis]
            wn = self.get_wavenumber()

            print(f"[LaserController] Pos: {position:.5f}, WN: {wn:.4f} (Target: {self.target_wn})")

        print(f"[LaserController] Target reached or stopped. Final WN: {wn:.4f}")
        self.is_moving = False

        # except Exception as e:
        #     print(f"[LaserController] Error: {e}")
        #     self.is_moving = False

if __name__ == "__main__":
    pass