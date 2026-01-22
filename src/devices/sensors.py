import threading
import time

class Multimeter:
    """
    Interface for the real HP34401A Multimeter.
    """
    def __init__(self, port, initialization_params: dict = {}):
        self.port = port
        print(f"[HW] Multimeter initialized on {port}")
        # TODO: Setup serial connection

    def reset(self):
        print("[HW] Multimeter Reset")

    def setRemote(self):
        print("[HW] Multimeter set to REMOTE mode")

    def identity(self):
        return b"HEWLETT-PACKARD,34401A,REAL-HW,VER-1.0"

    def getVoltage(self):
        # TODO: Read from serial
        return 0.0


class SpectrometreReader(threading.Thread):
    """
    Interface for the real Spectrometer Reader.
    """
    def __init__(self, refresh_rate=0.0005):
        super().__init__()
        self.refresh_rate = refresh_rate
        self.spectrum = 0.0
        self.stop_event = threading.Event()
        print("[HW] SpectrometreReader initialized")

    def run(self):
        while not self.stop_event.is_set():
            self.spectrum = self.get_spec()
            time.sleep(self.refresh_rate)

    def stop(self):
        self.stop_event.set()

    def get_spec(self, patience=0.1, max_tries=10):
        # TODO: Get real spectrum peak
        return 0.0


class WavenumberReader(threading.Thread):
    """
    Interface for the real Wavemeter Reader.
    """
    def __init__(self, refresh_rate=0.0005, source=None):
        super().__init__()
        self.refresh_rate = refresh_rate
        self.source = source
        self.wavenumbers = [0.0, 0.0, 0.0, 0.0]
        self.stop_event = threading.Event()
        print("[HW] WavenumberReader initialized")

    def run(self):
        while not self.stop_event.is_set():
            self.wavenumbers = [self.get_wnum(i) for i in range(1, 5)]
            time.sleep(self.refresh_rate)

    def stop(self):
        self.stop_event.set()

    def get_wnum(self, i=1):
        # TODO: Read from Wavemeter IOC/PV
        return 0.0

    def get_wavenumbers(self):
        return self.wavenumbers
