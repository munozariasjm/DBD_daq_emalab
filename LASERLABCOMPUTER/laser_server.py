"""XML-RPC bridge to the Sirah Matisse, exposing the MCP CounterDrift / GoTo
commands documented in update_docs.pdf (pp. 14-20).

The DAQ runs on a different machine and reaches this server over XML-RPC. All
hardware access is serialised by a single lock so concurrent XML-RPC threads
can't interleave Matisse commands.

Operator-side requirement: in Matisse Commander, set Display Options >
Position Display Mode = nm AND the CounterDrift dialog Unit = nm. The DAQ
sends nm-vacuum values; if the Matisse is set to cm^-1 the laser will be
commanded to wildly wrong frequencies.
"""

import os
import sys
import socket
import threading
import time
from xmlrpc.server import SimpleXMLRPCServer
from socketserver import ThreadingMixIn

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

SIMULATION = os.environ.get("SIMULATION", "0") == "1"

if SIMULATION:
    print("[Server] SIMULATION MODE ENABLED")
    from src.simulation.hardware_mocks import MockMatisseDevice
else:
    try:
        from pylablib.devices import Sirah
    except ImportError as e:
        print(f"[Server] Hardware libraries missing: {e}. Use SIMULATION=1 for testing.")
        sys.exit(1)

SIRAH_USB_RESOURCE = "USB0::0x17E7::0x0102::24-50-09::INSTR"
SERVER_IP = "0.0.0.0"
SERVER_PORT = 8000


class ThreadedXMLRPCServer(ThreadingMixIn, SimpleXMLRPCServer):
    """Handles concurrent XML-RPC clients (the GUI and Scanner can both poll)."""
    pass


class LaserServerInterface:
    """Public XML-RPC methods are the eight MCP wrappers below plus close()."""

    def __init__(self):
        self.lock = threading.Lock()
        try:
            print("[Server] Initialising Matisse...")
            if SIMULATION:
                self.sirah = MockMatisseDevice()
            else:
                self.sirah = Sirah.SirahMatisse(SIRAH_USB_RESOURCE)
            print("[Server] Matisse ready.")
        except Exception as e:
            print(f"[Server] CRITICAL HARDWARE ERROR: {e}")
            self.sirah = None

    def _ask(self, cmd: str) -> str:
        """Send a single MCP command and return the raw reply string.

        All MCP commands must be routed through Matisse Commander's server
        processor, signalled by the `#SERVER ` prefix (see docs pp. 14-20).
        Without that prefix the command interpreter sees the bare
        `MCP_WM_*` token, doesn't recognise it as a top-level command, and
        replies `1,"general syntax error"`."""
        if self.sirah is None:
            raise RuntimeError("Matisse not initialised")
        full_cmd = cmd if cmd.lstrip().startswith("#SERVER") else f"#SERVER {cmd}"
        with self.lock:
            reply = self.sirah.ask(full_cmd)
        return reply if reply is not None else ""

    # ---- Reachability ----

    def ping(self) -> bool:
        """Cheap probe used by the DAQ on connect. Returns True if the server
        is up AND the Matisse handle was initialised; False if the server is
        up but the laser is dead. Does not touch the Matisse hardware."""
        return self.sirah is not None

    # ---- CounterDrift ----

    def cd_open(self) -> bool:
        try:
            self._ask("MCP_WM_CounterDrift")
            return True
        except Exception as e:
            print(f"[Server] cd_open error: {e}")
            return False

    def cd_setpoint(self, nm: float) -> bool:
        try:
            self._ask(f"MCP_WM.Counterdrift Setpoint {float(nm)}")
            return True
        except Exception as e:
            print(f"[Server] cd_setpoint({nm}) error: {e}")
            return False

    def cd_activate(self, state: bool) -> bool:
        try:
            self._ask(f"MCP_WM.Counterdrift Activate {'true' if state else 'false'}")
            return True
        except Exception as e:
            print(f"[Server] cd_activate({state}) error: {e}")
            return False

    def cd_get_wavelength(self) -> float:
        try:
            reply = self._ask("MCP_WM_GET_WAVELENGTH")
            return float(reply.split()[0])
        except Exception as e:
            print(f"[Server] cd_get_wavelength error: {e}")
            return 0.0

    # ---- GoTo ----

    def goto_open(self) -> bool:
        try:
            self._ask("MCP_WM_GotoPosition")
            return True
        except Exception as e:
            print(f"[Server] goto_open error: {e}")
            return False

    def goto_set(self, nm: float) -> bool:
        try:
            self._ask(f"MCP_WM.GoTo Goto {float(nm)}")
            return True
        except Exception as e:
            print(f"[Server] goto_set({nm}) error: {e}")
            return False

    def goto_start(self) -> bool:
        try:
            self._ask("MCP_WM.GoTo Start")
            return True
        except Exception as e:
            print(f"[Server] goto_start error: {e}")
            return False

    def goto_status(self) -> str:
        try:
            return self._ask("MCP_WM.GoTo status").strip().upper() or "STOP"
        except Exception as e:
            print(f"[Server] goto_status error: {e}")
            return "STOP"

    # ---- Lifecycle ----

    def close(self) -> bool:
        try:
            if self.sirah is not None:
                with self.lock:
                    self.sirah.close()
            return True
        except Exception as e:
            print(f"[Server] close error: {e}")
            return False


if __name__ == "__main__":
    socket.setdefaulttimeout(120)
    server = ThreadedXMLRPCServer((SERVER_IP, SERVER_PORT), allow_none=True)
    server.register_instance(LaserServerInterface())

    print("==========================================")
    print(f" LASER SERVER RUNNING ON PORT {SERVER_PORT}")
    print("==========================================")
    try:
        print("Server active. Press Ctrl+C to stop.")
        server.serve_forever()
    except Exception as e:
        with open("server_crash_log.txt", "a") as f:
            f.write(f"Crash at {time.ctime()}: {e}\n")
        print(f"CRITICAL SERVER ERROR: {e}")
    finally:
        print("Shutting down...")
