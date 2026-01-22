from threading import Lock

class PIGCSDevice:
    """
    Interface for the real PI GCS Device (Motor Controller).
    Wraps pipython.GCSDevice.
    """
    def __init__(self, controller_name='', initialization_params: dict = {}):
        self.controller_name = controller_name
        self.connected = False
        self.lock = Lock()
        print(f"[HW] PIGCSDevice initialized (Controller: {controller_name})")
        # TODO: self.gcs = GCSDevice(controller_name)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.CloseConnection()

    def ConnectRS232(self, comport, baudrate):
        self.connected = True
        print(f"[HW] PI Connected to COM{comport} @ {baudrate}")
        # TODO: self.gcs.ConnectRS232(comport, baudrate)

    def CloseConnection(self):
        self.connected = False
        print("[HW] PI Connection Closed.")
        # TODO: self.gcs.CloseConnection()

    def qIDN(self):
        # TODO: return self.gcs.qIDN()
        return "Physik Instrumente, REAL-HARDWARE-PLACEHOLDER"

    def SVO(self, axis, state):
        with self.lock:
            print(f"[HW] PI Axis {axis} Servo {'ON' if state else 'OFF'}")
            # TODO: self.gcs.SVO(axis, state)

    def MOV(self, axis, target):
        with self.lock:
            print(f"[HW] PI Move Axis {axis} to {target}")
            # TODO: self.gcs.MOV(axis, target)

    def qPOS(self, axis=None):
        with self.lock:
            # TODO: return self.gcs.qPOS(axis)
            if axis:
                if isinstance(axis, list):
                   return {a: 0.0 for a in axis}
                return {axis: 0.0}
            return {1: 0.0}

    def qVEL(self, axis):
         with self.lock:
             # TODO: return self.gcs.qVEL(axis)
             return {axis: 0.0}


class EpicsClient:
    """
    Interface for the real Epics Client.
    Wraps epics.caget.
    """
    def __init__(self, pi_device, initialization_params: dict = {}):
        self.pi_device = pi_device
        print("[HW] EpicsClient initialized")

    def caget(self, pvname):
        print(f"[HW] Epics caget: {pvname}")
        # TODO: import epics; return epics.caget(pvname)
        return 0.0
