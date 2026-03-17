import xmlrpc.client
from threading import Lock
try:
    import epics
except ImportError:
    print("[HW] Warning: epics module not found.")
    epics = None

import os

LAB_COMPUTER_IP = "10.54.6.1"#os.environ.get('LASER_SERVER_HOST', '10.54.6.139:0.0.0.0')
LAB_COMPUTER_PORT = "8000"#int(os.environ.get('LASER_SERVER_PORT', 8000))

if os.environ.get('SIMULATION', '0') == '1':
    LAB_COMPUTER_IP = 'localhost'
import threading
import xmlrpc.client

class LaserCommError(Exception):
    """Raised when communication with the laser server fails."""
    pass


class PIGCSDevice:
    def __init__(self, controller_name='', initialization_params: dict = {}):
        self.url = f"http://{LAB_COMPUTER_IP}:{LAB_COMPUTER_PORT}"
        self.lock = Lock()

        self.proxy = xmlrpc.client.ServerProxy(
            self.url,
            allow_none=True,
            use_builtin_types=True
        )
        print(f"[RemoteHW] Connected to persistent server proxy at {self.url}")

    def MOV(self, axis, target):
        try:
            with self.lock:
                return self.proxy.MOV(axis, float(target))
        except xmlrpc.client.Fault as e:
            raise LaserCommError(f"[RemoteHW] Server error in MOV({axis}, {target}): {e.faultString}") from e
        except Exception as e:
            raise LaserCommError(f"[RemoteHW] Connection error in MOV({axis}, {target}): {e}") from e

    def qPOS(self, axis=None):
        try:
            with self.lock:
                val = self.proxy.qPOS(axis)
            return {axis: val} if axis else {1: val}
        except xmlrpc.client.Fault as e:
            raise LaserCommError(f"[RemoteHW] Server error in qPOS({axis}): {e.faultString}") from e
        except Exception as e:
            raise LaserCommError(f"[RemoteHW] Connection error in qPOS({axis}): {e}") from e

    def waitontarget(self, axis):
        with self.lock:
            return self.proxy.ServerWaitOnTarget(axis)

    def SVO(self, axis, state):
        pass

# class PIGCSDevice:
#     """
#     Robust Remote Client. Connects to laser_server.py.
#     """
#     def __init__(self, controller_name='', initialization_params: dict = {}):
#         self.lock = Lock()
#         self.url = f"http://{LAB_COMPUTER_IP}:{LAB_COMPUTER_PORT}"

#         transport = xmlrpc.client.Transport()
#         self.proxy = xmlrpc.client.ServerProxy(self.url, transport=transport, allow_none=False)

#         print(f"[RemoteHW] Connected to Server at {self.url}")
#         self.connected = True

#     def __enter__(self):
#         return self

#     def __exit__(self, exc_type, exc_val, exc_tb):
#         pass

#     def ConnectRS232(self, comport, baudrate):
#         print(f"[RemoteHW] (Server is handling RS232 connection on COM{comport})")

#     def call_proxy(self, func_name, *args):
#             with self.lock:
#                 func = getattr(self.proxy, func_name)
#                 return func(*args)

#     def MOV(self, axis, target):
#         with self.lock:
#             self.proxy.MOV(axis, float(target))

#     def qPOS(self, axis=None):
#         """
#         Returns dictionary {axis: value} to match pipython behavior.
#         """
#         with self.lock:
#             val = self.proxy.qPOS(axis)
#             return {axis: val} if axis else {1: val}

#     def qVEL(self, axis):
#         return {axis: 0.0}

#     def waitontarget(self, axis):
#         """
#         Blocks until the Server reports the axis has stopped moving.
#         Replaces 'pitools.waitontarget'.
#         """
#         with self.lock:
#             self.proxy.ServerWaitOnTarget(axis)


class ComClient:
    def __init__(self, pi_device, **kwargs):
        self.pi = pi_device # This is the PIGCSDevice instance

    def caget(self, pvname):
        try:
            val = epics.caget(pvname)
        except Exception as e:
            raise LaserCommError(f"[EPICS] Failed to read '{pvname}': {e}") from e
        if val is None:
            raise LaserCommError(f"[EPICS] No response for '{pvname}' (PV disconnected?)")
        return val