"""
Laser Lab Server — XML-RPC interface to Sirah Matisse via PyVISA.

Runs on the computer physically connected to the Matisse via USB.
The DAQ computer connects to this server over the network.

Usage:
    python laser_server.py                  # real hardware
    SIMULATION=1 python laser_server.py     # mock mode for testing
"""
import os
import sys
import threading
import time
import traceback
import socket
from xmlrpc.server import SimpleXMLRPCServer
from socketserver import ThreadingMixIn

# ---------------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------------
SERVER_IP = '0.0.0.0'
SERVER_PORT = 8000
SIMULATION = os.environ.get('SIMULATION', '0') == '1'

# Matisse VISA resource — adjust serial number to match your unit
# Device IDs from Programmer's Guide p.10:
#   TR=0x0101, TS=0x0102, TX=0x0103, DR=0x0104, DS=0x0105, DX=0x0106
MATISSE_VISA_RESOURCE = "USB0::0x17E7::0x0102::24-50-09::INSTR"
VISA_TIMEOUT_MS = 5000


class ThreadedXMLRPCServer(ThreadingMixIn, SimpleXMLRPCServer):
    """Handle concurrent XML-RPC requests without blocking."""
    daemon_threads = True


# ---------------------------------------------------------------------------
#  Matisse VISA wrapper
# ---------------------------------------------------------------------------
class MatisseVISA:
    """
    Thin wrapper around a PyVISA session to the Matisse.
    Sends raw device commands per the Programmer's Guide Chapter 6.
    """

    def __init__(self, resource_name: str, timeout_ms: int = VISA_TIMEOUT_MS):
        import pyvisa
        self.rm = pyvisa.ResourceManager()
        print(f"[Matisse] Opening VISA resource: {resource_name}")
        print(f"[Matisse] Available resources: {self.rm.list_resources()}")
        self.instr = self.rm.open_resource(resource_name)
        self.instr.timeout = timeout_ms
        # USBTMC doesn't need baud/parity, but set a read termination
        self.instr.read_termination = '\n'
        self.instr.write_termination = '\n'

    def ask(self, command: str) -> str:
        """Send a command and return the raw response string."""
        resp = self.instr.query(command)
        return resp.strip()

    def write(self, command: str) -> None:
        """Send a command with no response expected (or read and discard)."""
        self.instr.write(command)

    def write_and_check(self, command: str) -> str:
        """Send a command and read the OK / !ERROR response."""
        resp = self.instr.query(command)
        return resp.strip()

    def close(self):
        self.instr.close()
        self.rm.close()


# ---------------------------------------------------------------------------
#  Server interface exposed via XML-RPC
# ---------------------------------------------------------------------------
class LaserServerInterface:
    def __init__(self):
        self.lock = threading.Lock()
        self.matisse = None
        self._request_count = 0

        try:
            if SIMULATION:
                print("[Server] SIMULATION MODE — no hardware")
                self._sim_position = 0.35
                return

            self.matisse = MatisseVISA(MATISSE_VISA_RESOURCE)
            self._startup_diagnostics()

        except Exception as e:
            print(f"[Server] CRITICAL INIT ERROR: {e}")
            traceback.print_exc()
            self.matisse = None

    # ------------------------------------------------------------------
    #  Startup diagnostics — verify everything works before serving
    # ------------------------------------------------------------------
    def _startup_diagnostics(self):
        print("\n[Server] ========== STARTUP DIAGNOSTICS ==========")

        # 1. Identification
        try:
            idn = self.matisse.ask("IDN?")
            print(f"[Server] IDN: {idn}")
        except Exception as e:
            print(f"[Server] IDN? FAILED: {e}")

        # 2. Reference cell position (this is what MOV/qPOS control)
        try:
            raw = self.matisse.ask("REFCELL:NOW?")
            print(f"[Server] REFCELL:NOW? raw = '{raw}'")
            val = self._parse_float(raw)
            print(f"[Server] REFCELL:NOW? parsed = {val:.6f}")
        except Exception as e:
            print(f"[Server] REFCELL:NOW? FAILED: {e}")

        # 3. Scan status
        try:
            raw = self.matisse.ask("SCAN:STA?")
            print(f"[Server] SCAN:STA? = '{raw}'")
        except Exception as e:
            print(f"[Server] SCAN:STA? FAILED: {e}")

        # 4. Scan device
        try:
            raw = self.matisse.ask("SCAN:DEV?")
            print(f"[Server] SCAN:DEV? = '{raw}'")
        except Exception as e:
            print(f"[Server] SCAN:DEV? FAILED: {e}")

        # 5. Fast piezo lock status
        try:
            raw = self.matisse.ask("FPZT:LOCK?")
            print(f"[Server] FPZT:LOCK? = '{raw}'")
        except Exception as e:
            print(f"[Server] FPZT:LOCK? FAILED: {e}")

        # 6. Piezo etalon control status
        try:
            raw = self.matisse.ask("PZETL:CNTRSTA?")
            print(f"[Server] PZETL:CNTRSTA? = '{raw}'")
        except Exception as e:
            print(f"[Server] PZETL:CNTRSTA? FAILED: {e}")

        # 7. Thin etalon control status
        try:
            raw = self.matisse.ask("TE:CNTRSTA?")
            print(f"[Server] TE:CNTRSTA? = '{raw}'")
        except Exception as e:
            print(f"[Server] TE:CNTRSTA? FAILED: {e}")

        print("[Server] ========== END DIAGNOSTICS ===========\n")

    # ------------------------------------------------------------------
    #  Parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_float(response: str) -> float:
        """
        Parse Matisse response format ':CMD:SUBCMD: <float>'
        e.g. ':REFCELL:NOW: 3.500000e-01' -> 0.35

        Handles both ':'-delimited and plain float responses.
        """
        # Grab everything after the last colon
        token = response.split(':')[-1].strip()
        return float(token)

    @staticmethod
    def _check_response(response: str, context: str = "") -> bool:
        """Check if a Matisse response is OK or an error."""
        if response.startswith("OK"):
            return True
        if "ERROR" in response:
            print(f"[Server] MATISSE ERROR ({context}): {response}")
            return False
        # Some responses are just data — that's fine
        return True

    # ------------------------------------------------------------------
    #  XML-RPC exposed methods
    # ------------------------------------------------------------------
    def ping(self) -> str:
        """
        Connectivity test — call this from the DAQ to verify the link.
        Returns 'pong' if alive, includes matisse status if connected.
        """
        self._request_count += 1
        if SIMULATION:
            return "pong:simulation"
        if self.matisse is None:
            return "pong:no_hardware"
        try:
            with self.lock:
                idn = self.matisse.ask("IDN?")
            return f"pong:{idn}"
        except Exception as e:
            return f"pong:error:{e}"

    def MOV(self, axis, target):
        """
        Set the reference cell position.

        Matisse command: REFCELL:NOW <float>
        Valid range: [0, 0.7]
        """
        self._request_count += 1
        target = float(target)
        print(f"[CMD #{self._request_count}] MOV axis={axis} target={target:.6f}")

        if SIMULATION:
            self._sim_position = target
            print(f"[CMD] SIM MOV -> {target:.6f}")
            return True

        if self.matisse is None:
            print("[CMD] MOV FAILED — no hardware connection")
            return False

        try:
            with self.lock:
                # Read current position first for logging
                raw_before = self.matisse.ask("REFCELL:NOW?")
                pos_before = self._parse_float(raw_before)

                # Send the move command
                resp = self.matisse.write_and_check(f"REFCELL:NOW {target}")
                ok = self._check_response(resp, context=f"MOV {target}")

                print(f"[CMD] MOV: {pos_before:.6f} -> {target:.6f}  "
                      f"response='{resp}' ok={ok}")
                return ok

        except Exception as e:
            print(f"[CMD] MOV EXCEPTION: {e}")
            traceback.print_exc()
            return False

    def qPOS(self, axis):
        """
        Read the reference cell position.

        Matisse command: REFCELL:NOW?
        Returns: float in [0, 0.7]
        """
        self._request_count += 1

        if SIMULATION:
            print(f"[CMD #{self._request_count}] qPOS SIM -> {self._sim_position:.6f}")
            return self._sim_position

        if self.matisse is None:
            print("[CMD] qPOS FAILED — no hardware connection")
            # IMPORTANT: raise, don't return 0.0 silently!
            raise Exception("No hardware connection")

        try:
            with self.lock:
                raw = self.matisse.ask("REFCELL:NOW?")
                val = self._parse_float(raw)

            # Log every 10th request to avoid spam, but always log first few
            if self._request_count <= 5 or self._request_count % 10 == 0:
                print(f"[CMD #{self._request_count}] qPOS raw='{raw}' -> {val:.6f}")
            return val

        except Exception as e:
            print(f"[CMD] qPOS EXCEPTION: {e}")
            traceback.print_exc()
            raise  # Let XML-RPC propagate the fault to the client

    def raw_command(self, command):
        """
        Send an arbitrary Matisse command and return the response.
        Useful for debugging from the DAQ side.

        Example: server.raw_command("FPZT:LOCK?")
        """
        self._request_count += 1
        print(f"[CMD #{self._request_count}] RAW: '{command}'")

        if SIMULATION:
            return "SIMULATION: no hardware"
        if self.matisse is None:
            return "ERROR: no hardware connection"

        try:
            with self.lock:
                resp = self.matisse.ask(command)
            print(f"[CMD] RAW response: '{resp}'")
            return resp
        except Exception as e:
            err = f"ERROR: {e}"
            print(f"[CMD] RAW EXCEPTION: {err}")
            return err

    def get_status(self):
        """
        Return a dict of current Matisse state for dashboard display.
        """
        self._request_count += 1
        status = {
            "request_count": self._request_count,
            "simulation": SIMULATION,
            "hardware_connected": self.matisse is not None,
        }

        if SIMULATION:
            status["refcell_position"] = self._sim_position
            return status

        if self.matisse is None:
            return status

        try:
            with self.lock:
                raw = self.matisse.ask("REFCELL:NOW?")
                status["refcell_position"] = self._parse_float(raw)

                raw = self.matisse.ask("SCAN:STA?")
                status["scan_status"] = raw

                raw = self.matisse.ask("FPZT:LOCK?")
                status["fast_piezo_lock"] = raw

                raw = self.matisse.ask("PZETL:CNTRSTA?")
                status["piezo_etalon_control"] = raw

                raw = self.matisse.ask("TE:CNTRSTA?")
                status["thin_etalon_control"] = raw
        except Exception as e:
            status["error"] = str(e)

        return status

    def close(self):
        if self.matisse:
            self.matisse.close()


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    socket.setdefaulttimeout(120)

    # Show network info for debugging
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "unknown"
    print(f"[Server] Host: {hostname}, IP: {local_ip}")
    print(f"[Server] Binding to {SERVER_IP}:{SERVER_PORT}")
    print(f"[Server] SIMULATION={SIMULATION}")

    server = ThreadedXMLRPCServer(
        (SERVER_IP, SERVER_PORT),
        allow_none=True,
        logRequests=True,   # Log every XML-RPC request to stdout
    )
    interface = LaserServerInterface()
    server.register_instance(interface)

    print(f"\n==========================================")
    print(f" LASER SERVER RUNNING ON PORT {SERVER_PORT}")
    print(f" Connect from DAQ with:")
    print(f"   http://{local_ip}:{SERVER_PORT}")
    print(f"==========================================\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Server] Shutting down (Ctrl+C)...")
    except Exception as e:
        with open("server_crash_log.txt", "a") as f:
            f.write(f"Crash at {time.ctime()}: {str(e)}\n{traceback.format_exc()}\n")
        print(f"[Server] CRITICAL ERROR: {e}")
        traceback.print_exc()
    finally:
        interface.close()
        server.server_close()
        print("[Server] Shut down complete.")