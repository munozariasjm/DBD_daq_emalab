import threading
import time
import random
import math

class MockMultimeter:
    """
    Simulates an HP Multimeter communicating via Serial.
    Returns a noisy sine wave voltage.
    """
    def __init__(self, port, initialization_params: dict = {}):
        self.port = port
        self.noise_level = initialization_params.get("noise_level", 0.05)
        print(f"[SIM] MockMultimeter connected on {port}")
        self.start_time = time.time()

    def reset(self):
        print("[SIM] Multimeter Reset")

    def setRemote(self):
        print("[SIM] Multimeter set to REMOTE mode")

    def identity(self):
        return b"HEWLETT-PACKARD,34401A,SIMULATED,VER-2.0"

    def getVoltage(self):
        # Generate a sine wave oscillating between 0.5V and 4.5V with noise
        elapsed = time.time() - self.start_time
        base_signal = 2.5 + 2.0 * math.sin(elapsed * 0.5)
        noise = random.uniform(-self.noise_level, self.noise_level)
        return round(base_signal + noise, 5)


class MockSpectrometreReader(threading.Thread):
    """
    Simulates the EPICS Spectrometer Reader.
    Updates the 'spectrum' attribute in a background thread.
    """
    def __init__(self, refresh_rate=0.0005):
        super().__init__()
        self.refresh_rate = refresh_rate
        self.spectrum = 0.0
        self.pv_name = "SIM:LaserLab:spectrum_peak"
        self.stop_event = threading.Event()
        print("[SIM] MockSpectrometreReader initialized")

    def run(self):
        while not self.stop_event.is_set():
            self.spectrum = self.get_spec()
            time.sleep(self.refresh_rate)

    def stop(self):
        self.stop_event.set()

    def get_spec(self, patience=0.1, max_tries=10):
        # Simulate a peak drifting slowly around 600.0 nm
        drift = math.sin(time.time() / 10.0) * 2.0
        jitter = random.uniform(-0.1, 0.1)
        return round(600.0 + drift + jitter, 4)


# --- Mock Wavemeter Reader ---
class MockWavenumberReader(threading.Thread):
    """
    Simulates the EPICS Wavemeter Reader.
    Updates 4 channels of wavenumbers in a background thread.
    """
    def __init__(self, refresh_rate=0.0005, source=None):
        super().__init__()
        self.refresh_rate = refresh_rate
        self.source = source
        self.wavenumbers = [0.0, 0.0, 0.0, 0.0]
        self.stop_event = threading.Event()
        print("[SIM] MockWavenumberReader initialized")

    def run(self):
        while not self.stop_event.is_set():
            # Update all 4 channels
            self.wavenumbers = [self.get_wnum(i) for i in range(1, 5)]
            time.sleep(self.refresh_rate)

    def stop(self):
        self.stop_event.set()

    def get_wnum(self, i=1):
        # Simulate realistic wavenumbers for visible range (~600 nm)
        # 600 nm -> 16666.6 cm^-1
        if i == 1 and self.source:
            # Measure the source!
            if hasattr(self.source, 'get_wavenumber'):
                base = self.source.get_wavenumber()
            elif hasattr(self.source, 'get_wavelength'):
                wl = self.source.get_wavelength()
                if wl > 0:
                    base = 1e7 / wl
                else:
                    base = 16666.6
            else:
                 base = 16666.6
        else:
            base = 16666.6 + (i-1) * 1000.0

        noise = random.uniform(-0.05, 0.05)
        return round(base + noise, 4)

    def get_wavenumbers(self):
        return self.wavenumbers