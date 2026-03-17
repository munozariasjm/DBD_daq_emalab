import os
import sys
import threading
import time
from xmlrpc.server import SimpleXMLRPCServer
from socketserver import ThreadingMixIn
from pylablib.devices import Sirah

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
        self.lock = threading.Lock()
        self.laser = False
        try:
            print(f"[Server] Initializing {CONTROLLERNAME}...")
            if SIMULATION:
                self.pi = get_mock_device()
                self.pi.ConnectRS232(comport=COM_PORT, baudrate=BAUD_RATE)
                self.pi.SVO(1, 1)
                return
            elif self.laser:
                self.pi = GCSDevice(CONTROLLERNAME)
                self.pi.ConnectRS232(comport=COM_PORT, baudrate=BAUD_RATE)
                print(f"[Server] Connected: {self.pi.qIDN().strip()}")

                self.pi.SVO(1, 1)
                print("[Server] Servo enabled (Axis 1).")
                print(self.pi.qPOS(1)[1])
            else:
                self.sirah = Sirah.SirahMatisse("USB0::0x17E7::0x0102::24-50-09::INSTR")
                print(f"[Server] Scan status: {self.sirah.get_scan_status()}")
                print(f"[Server] Scan position: {self.sirah.get_scan_position()}")
                print(f"[Server] Scan device: {self.sirah.get_scan_params().device}")
        except Exception as e:
            print(f"[Server] CRITICAL HARDWARE ERROR: {e}")
            self.pi = None

    def _parse_matisse_float(self, response):
        """Parse Matisse response format ':CMD:SUBCMD:<float>' securely."""
        # Split by the colon and grab the last element to avoid whitespace errors
        return float(response.split(':')[-1].strip())

    def MOV(self, axis, target):
        with self.lock:
            if self.laser:
                current = self.pi.qPOS(axis)[axis]
                print(f"[CMD] MOV Axis {axis}: {current:.5f} -> {float(target):.5f}")
                self.pi.MOV(axis, float(target))
                time.sleep(0.1)
            else:
                # Use REFCELL:NOW? to get the specific reference cell position
                raw = self.sirah.ask('REFCELL:NOW?')
                current = self._parse_matisse_float(raw)
                print(f"[CMD] MOV refcell: {current:.5f} -> {float(target):.5f}")

                # Use REFCELL:NOW to set the reference cell position directly
                self.sirah.ask(f'REFCELL:NOW {float(target)}')
        return True

    def qPOS(self, axis):
        with self.lock:
            if self.laser:
                val = self.pi.qPOS(axis)[axis]
                time.sleep(0.1)
            else:
                # Use REFCELL:NOW? instead of SCAN:NOW?
                raw = self.sirah.ask('REFCELL:NOW?')
                val = self._parse_matisse_float(raw)
            print(f"[CMD] qPOS Axis {axis}: {float(val):.5f}")
        return float(val)

    def close(self):
        if self.laser:
            self.pi.CloseConnection()
        else:
            self.sirah.close()

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