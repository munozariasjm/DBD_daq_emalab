import time
import random
import threading
import math

class MockLaser:
    """
    Simulates a Tunable Laser.
    Movements are not immediate and have noise.
    """
    def __init__(self):
        self.current_wavelength = 600.000 # nm
        self.target_wavelength = 600.000
        self.is_moving = False
        self.last_update = time.time()
        self.move_speed = 10.0 # nm/sec
        self.noise_level = 0.001 # nm

        # Thread safety
        self.lock = threading.Lock()

    def set_wavelength(self, wavelength):
        with self.lock:
            self.target_wavelength = wavelength
            self.is_moving = True
            print(f"[SIM] Laser ordered to move to {wavelength} nm")

    def get_wavelength(self):
        with self.lock:
            self._update_state()
            # Add noise
            noise = random.gauss(0, self.noise_level)
            return self.current_wavelength + noise

    def is_stable(self, tolerance=0.005):
        with self.lock:
            self._update_state()
            diff = abs(self.current_wavelength - self.target_wavelength)
            # We consider it stable if close enough and logically "done" moving
            # For this simple sim, if diff is small, it's stable.
            stable = diff < tolerance
            return stable

    def _update_state(self):
        now = time.time()
        dt = now - self.last_update
        self.last_update = now

        if self.current_wavelength != self.target_wavelength:
            direction = 1 if self.target_wavelength > self.current_wavelength else -1
            distance = abs(self.target_wavelength - self.current_wavelength)
            step = self.move_speed * dt

            if step >= distance:
                self.current_wavelength = self.target_wavelength
            else:
                self.current_wavelength += direction * step
