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
COM_PORT = 5
BAUD_RATE = 19200
SERVER_IP = '0.0.0.0'
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

    def close(self):
        self.pi.CloseConnection()

if __name__ == "__main__":
    import time
    import socket
    socket.setdefaulttimeout(120)

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