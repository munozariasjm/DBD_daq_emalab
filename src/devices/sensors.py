import threading
import time
try:
    import serial
except ImportError:
    print("[HW] Warning: serial module not found.")
    serial = None

try:
    import epics
    from epics import PV
except ImportError:
    print("[HW] Warning: epics module not found.")
    epics = None
    PV = None
global wavenumbers_pvs

wavenumbers_pv_names = ["LaserLab:wavenumber_1", "LaserLab:wavenumber_2", "LaserLab:wavenumber_3", "LaserLab:wavenumber_4"]

wavenumbers_pvs = []
if PV is not None:
    wavenumbers_pvs = [PV(name) for name in wavenumbers_pv_names]


class HP_Multimeter:
    def __init__(self, port):
        self.device = serial.Serial(port, baudrate=9600, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_TWO, timeout=1)
        self.reset()
        time.sleep(0.25)
        self.setRemote()
        time.sleep(0.25)

    def reset(self):
        self.device.write(b'*RST\n')
        self.device.readline()

    def setRemote(self):
        self.device.write(b'SYSTEM:REMOTE\n')
        self.device.readline()

    def identity(self):
        self.device.write(b'*IDN?\n')
        response = self.device.readline()
        return response

    def getVoltage(self):
        self.device.write(b"MEAS:VOLT:DC?\n")
        try:
            response = self.device.readline().decode('utf-8').strip('\r\n')
            response = float(response)
        except Exception as expn:
            print('uh oh, exception occurred reading the voltage', expn)
            response = 0.0
        return response

class VoltageReader(threading.Thread):
    def __init__(self, multimeter, refresh_rate=0.5):
        super().__init__()
        self.multimeter = multimeter
        self.refresh_rate = refresh_rate
        self.voltage = 0.0
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.voltage = self.multimeter.getVoltage()
                time.sleep(self.refresh_rate)
            except Exception as expn:
                self.voltage = -69419.999999999999
                time.sleep(self.refresh_rate)


    def stop(self):
        self.stop_event.set()

    def get_voltage(self):
        return self.voltage

class SpectrometreReader(threading.Thread):
    """
    Interface for the real Spectrometer Reader.
    """
    def __init__(self, refresh_rate=0.2):
        super().__init__()
        self.refresh_rate = refresh_rate
        self.spectrum = None
        self.pv_name = "LaserLab:spectrum_peak"
        self.stop_event = threading.Event()

    def run(self):
        while not self.stop_event.is_set():
            self.spectrum = self.get_spec()
            time.sleep(self.refresh_rate)

    def stop(self):
        self.stop_event.set()

    def get_spec(self):
        try:
            spec = epics.caget(self.pv_name)
            spec = float(spec) if spec is not None else 0.00
            return spec
        except Exception as e:
            print(f"Error getting spectrum: {e}")
            print("Spectrum Disconnected!:", spec)

            return 0.00

class WavenumberReader:
    """
    Interface for the real Wavemeter Reader.
    """
    def __init__(self):
        super().__init__()
        self.wavenumbers = [0.0, 0.0, 0.0, 0.0]

    def get_wnum(self, i=1):
        try:
            return round(float(wavenumbers_pvs[i - 1].get()), 5)
        except Exception as e:
            # print(f"Error getting wavenumber: {e}")
            return 0.00000

    def get_wavenumbers(self):
        return [self.get_wnum(k) for k in range(1,5)]