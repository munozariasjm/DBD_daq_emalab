import time
import threading
from collections import OrderedDict

# Mock pipython.GCSDevice
class MockPIGCSDevice:
    """
    Mocks the behavior of pipython.GCSDevice.
    """
    def __init__(self, controller_name='', initialization_params: dict = {}):
        self.controller_name = controller_name
        self.connected = False
        self.axes = [1] # Simulating 1 axis
        self.servo_state = {axis: False for axis in self.axes}
        self.position = {axis: 0.0 for axis in self.axes} # mm
        self.target_position = {axis: 0.0 for axis in self.axes} # mm
        self.velocity = {axis: 0.0 for axis in self.axes}

        # Physics simulation
        self.last_update = time.time()
        self.sim_speed = initialization_params.get("move_speed", 0.5) # mm/s
        self.lock = threading.Lock()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.CloseConnection()

    def ConnectRS232(self, comport, baudrate):
        self.connected = True
        print(f"[MockPI] Connected to {self.controller_name} on COM{comport} @ {baudrate}")

    def CloseConnection(self):
        self.connected = False
        print("[MockPI] Connection Closed.")

    def qIDN(self):
        return "Physik Instrumente, MOCK-CONTROLLER, 12345, 1.0"

    def SVO(self, axis, state):
        with self.lock:
            self.servo_state[axis] = bool(state)
            print(f"[MockPI] Axis {axis} Servo {'ON' if state else 'OFF'}")

    def MOV(self, axis, target):
        with self.lock:
            if not self.servo_state.get(axis, False):
                print(f"[MockPI] Warning: MOV called on Axis {axis} but Servo is OFF")
                return
            self.target_position[axis] = float(target)
            # Instant update for now, or we can simulate movement time in qPOS
            # The real script loops waitontarget, so we should separate target from actual
            # nicely done in the update method.

    def qPOS(self, axis=None):
        self._update_physics()
        # Add tiny jitter to prevent "exact" position checks in specific controllers from failing
        # (e.g. avoiding 0.0 difference when reversing direction)
        import random
        jitter = random.uniform(-1e-8, 1e-8)

        with self.lock:
            if axis:
                if isinstance(axis, list):
                   return {a: self.position[a] + jitter for a in axis}
                return {axis: self.position[axis] + jitter}

            return {k: v + jitter for k, v in self.position.items()}

    def qVEL(self, axis):
         with self.lock:
             return {axis: self.sim_speed}

    def _update_physics(self):
        with self.lock:
            now = time.time()
            dt = now - self.last_update
            self.last_update = now

            for a in self.axes:
                diff = self.target_position[a] - self.position[a]
                if abs(diff) < 1e-6:
                    self.position[a] = self.target_position[a]
                    continue

                direction = 1.0 if diff > 0 else -1.0
                step = self.sim_speed * dt

                if step >= abs(diff):
                    self.position[a] = self.target_position[a]
                else:
                    self.position[a] += direction * step

# Mock epics
class MockEpicsClient:
    """
    Mocks the epics.caget behavior.
    Coupled with the MockPIGCSDevice to return consistent physical values.
    """
    def __init__(self, pi_device, initialization_params: dict = {}):
        self.pi_device = pi_device
        # Linear relationship: WN = A * Pos + B
        # From script: target=12625.2, Pos approx ?
        # Let's assume a simplified relationship for simulation:
        # 1 mm = 100 cm^-1
        self.slope = initialization_params.get("slope", 100.0)
        self.offset = initialization_params.get("offset", 16600.0)
        self.noise = initialization_params.get("noise_level", 0.0005)

    def caget(self, pvname):
        # We only care about Wavenumber PVs
        if "wavenumber" in pvname:
            # Get current motor position
            # We assume Axis 1 controls this
            pos_dict = self.pi_device.qPOS(1)
            pos = pos_dict[1]

            # Calculate WN
            wn = self.offset + (pos * self.slope)

            # Add some measurement noise
            import random
            noise_val = random.uniform(-self.noise, self.noise)
            return wn + noise_val
        return 0.0
