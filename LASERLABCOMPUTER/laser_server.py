import os
import sys
from xmlrpc.server import SimpleXMLRPCServer
from socketserver import ThreadingMixIn
import pylablib as pll
pll.list_backend_resources("visa")
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

SIMULATION = os.environ.get('SIMULATION', '0') == '1'

if SIMULATION:
    print("[Server] SIMULATION MODE ENABLED")
    from simulation import get_mock_device, mock_caget
    GCSDevice = None
    epics = None
else:
    try:
        from pipython import GCSDevice,pitools
        import epics
    except ImportError as e:
        print(f"[Server] Hardware libraries missing: {e}. Use SIMULATION=1 for testing.")
        sys.exit(1)

CONTROLLERNAME = 'HydraPollux'
COM_PORT = 5           # Adjust to your Lab Computer's actual COM port
BAUD_RATE = 19200
SERVER_IP = '0.0.0.0'  # Listen on all available network interfaces
SERVER_PORT = 8000

class ThreadedXMLRPCServer(ThreadingMixIn, SimpleXMLRPCServer):
    """Allows the server to handle multiple requests (like non-blocking queries) simultaneously."""
    pass

class LaserServerInterface:
    def __init__(self):
        print(f"[Server] Initializing {CONTROLLERNAME}...")
        if SIMULATION:
            self.pi = get_mock_device()
            self.pi.ConnectRS232(comport=COM_PORT, baudrate=BAUD_RATE)
            self.pi.SVO(1, 1)
            return

        try:
            self.pi = GCSDevice(CONTROLLERNAME)
            self.pi.ConnectRS232(comport=COM_PORT, baudrate=BAUD_RATE)
            print(f"[Server] Connected: {self.pi.qIDN().strip()}")

            self.pi.SVO(1, 1)
            print("[Server] Servo enabled (Axis 1).")
            print(self.pi.qPOS(1)[1])
        except Exception as e:
            print(f"[Server] CRITICAL HARDWARE ERROR: {e}")
            self.pi = None

    # def qIDN(self):
    #     return self.pi.qIDN() if self.pi else "Hardware Offline"

    def MOV(self, axis, target):
        print(f"[CMD] MOV Axis {axis} -> {target}")
        try:
            self.pi.MOV(axis, float(target))
            time.sleep(0.1) # Critical: Small pause
            return True
        except Exception as e:
            print(f"Hardware Error in MOV: {e}")
            return False

    def qPOS(self, axis):
        try:
            val = self.pi.qPOS(axis)[axis]
            time.sleep(0.1) # Critical: Small pause after serial talk
            return float(val)
        except Exception as e:
            print(f"Hardware Error in qPOS: {e}")
            return 0.0
    
    # def updateParams(self, params=[0.01,0.0001,0.05]):
    #     self.uncertainty,self.step_size,self.backlash = params
    

    # def ServerWaitOnTarget(self, axis=1, timeout=5.0):
    #     """
    #     BLOCKING WAIT: Performed locally on the server.
    #     Polls 'IsMoving' rapidly with zero network latency.
    #     Returns True when target is reached.
    #     """
    #     if not self.pi: return True

    #     print(f"[Wait] Blocking for Axis {axis} stability...")
    #     # if SIMULATION:
    #     start_time = time.time()

    #     while True:
    #         if time.time() - start_time > timeout:
    #             print(f"[Wait] TIMEOUT on Axis {axis}")
    #             return False

    #         try:
    #             # IsMoving returns dict {axis: bool}
    #             is_moving = self.pi.IsMoving(axis)[axis]
    #             if not is_moving:
    #                 print(f"[Wait] Movement Complete.")
    #                 return True
    #         except Exception as e:
    #             print(f"[Wait] Error reading status: {e}")
    #             return False

    #         time.sleep(0.5)    
    #     # else:
    #     #     pitools.waitontarget(self.pi,axes=axis)

    # def get_epics_wn(self, pv_name):
    #     """Fetches Wavenumber from local EPICS environment."""
    #     if SIMULATION:
    #         return float(mock_caget(pv_name))
    #     try:
    #         val = epics.caget(pv_name)
    #         return float(val) if val is not None else 0.0
    #     except Exception as e:
    #         print(f"[EPICS] Error: {e}")
    #         return 0.0

    def close(self):
        # if self.pi:
        self.pi.CloseConnection()

if __name__ == "__main__":
    import time
    import socket
    # Prevent the server from hanging on dead connections
    socket.setdefaulttimeout(120)

    # 'allow_none=True' is required to handle void return types
    server = ThreadedXMLRPCServer((SERVER_IP, SERVER_PORT), allow_none=True)
    server.register_instance(LaserServerInterface())

    print(f"==========================================")
    print(f" LASER SERVER RUNNING ON PORT {SERVER_PORT}")
    print(f"==========================================")
    try:
        print("Server active. Press Ctrl+C to stop.")
        server.serve_forever()
    except Exception as e:
        with open("server_crash_log.txt", "a") as f:
            f.write(f"Crash at {time.ctime()}: {str(e)}\n")
        print(f"CRITICAL SERVER ERROR: {e}")
    finally:
        print("Shutting down...")