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
        elapsed = time.time() - self.start_time
        base_signal = 2.5 + 2.0 * math.sin(elapsed * 0.5)
        noise = random.uniform(-self.noise_level, self.noise_level)
        return round(base_signal + noise, 5)

    def start(self):
        pass

    def stop(self):
        pass

    def get_voltage(self):
        return self.getVoltage()

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
        drift = math.sin(time.time() / 10.0) * 2.0
        jitter = random.uniform(-0.1, 0.1)
        return round(16666.6 + drift + jitter, 6)


class MockWavenumberReader:
    """
    Simulates the EPICS Wavemeter Reader.
    Generates wavenumbers on demand matching the interface of WavenumberReader.
    """
    def __init__(self, refresh_rate=0.0005, source=None):
        self.source = source
        print("[SIM] MockWavenumberReader initialized (On-Demand)")

    def start(self):
        pass

    def stop(self):
        pass

    def get_wnum(self, i=1):
        base = 16666.6
        if self.source:
             # Check channel if relevant, but for now we just map channel 1 to the source
             if i == 1:
                if hasattr(self.source, 'get_wavenumber'):
                    base = self.source.get_wavenumber()
                elif hasattr(self.source, 'get_wavelength'):
                    wl = self.source.get_wavelength()
                    if wl > 0:
                        base = 1e7 / wl

        if not self.source and i != 1:
             # Fallback for other channels or if no source
             base = 16666.6 + (i-1) * 1000.0

        noise = random.uniform(-0.05, 0.05)
        # return round(base + noise, 6)
        return base

    def get_wavenumbers(self):
        return [self.get_wnum(i) for i in range(1, 5)]