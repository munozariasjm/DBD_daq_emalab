import xmlrpc.client
from threading import Lock

import os

LAB_COMPUTER_IP = os.environ.get('LASER_SERVER_HOST', '192.168.1.XXX')
LAB_COMPUTER_PORT = int(os.environ.get('LASER_SERVER_PORT', 8000))

if os.environ.get('SIMULATION', '0') == '1':
    LAB_COMPUTER_IP = 'localhost'

class PIGCSDevice:
    """
    Robust Remote Client. Connects to laser_server.py.
    """
    def __init__(self, controller_name='', initialization_params: dict = {}):
        self.lock = Lock()
        self.url = f"http://{LAB_COMPUTER_IP}:{LAB_COMPUTER_PORT}"

        transport = xmlrpc.client.Transport()
        self.proxy = xmlrpc.client.ServerProxy(self.url, transport=transport, allow_none=True)

        print(f"[RemoteHW] Connected to Server at {self.url}")
        self.connected = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def ConnectRS232(self, comport, baudrate):
        print(f"[RemoteHW] (Server is handling RS232 connection on COM{comport})")

    def qIDN(self):
        with self.lock: return self.proxy.qIDN()

    def SVO(self, axis, state):
        pass

    def MOV(self, axis, target):
        with self.lock:
            self.proxy.MOV(axis, float(target))

    def qPOS(self, axis=None):
        """
        Returns dictionary {axis: value} to match pipython behavior.
        """
        with self.lock:
            val = self.proxy.qPOS(axis)
            return {axis: val} if axis else {1: val}

    def qVEL(self, axis):
        return {axis: 0.0}

    def waitontarget(self, axis):
        """
        Blocks until the Server reports the axis has stopped moving.
        Replaces 'pitools.waitontarget'.
        """
        with self.lock:
            self.proxy.ServerWaitOnTarget(axis)


class EpicsClient:
    def __init__(self, pi_device, initialization_params={}):
        self.pi = pi_device

    def caget(self, pvname):
        try:
            return self.pi.proxy.get_epics_wn(pvname)
        except:
            return 0.0