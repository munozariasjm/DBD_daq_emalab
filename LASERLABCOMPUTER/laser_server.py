"""XML-RPC bridge to the Sirah Matisse via Matisse Commander's network
server.

Architecture: Matisse Commander (the desktop application that owns the
laser) runs its own TCP server, configured under
  Matisse > Communication Options > Network Server Settings
Default address: 127.0.0.1:30000. That server understands the MCP commands
documented in update_docs.pdf (pp. 14-20). The laser's DSP firmware over
USB-VISA does NOT — it speaks low-level DSP commands and rejects every
`MCP_WM_*` token with `1,"general syntax error"`. It also races Matisse
Commander for the USB resource (`VI_ERROR_RSRC_LOCKED`).

This server therefore opens a plain TCP socket to Matisse Commander and
forwards MCP commands as ASCII lines. No `#SERVER ` prefix is sent: that
prefix is the routing token for Matisse Commander's interactive Command
Console, where it tells the console "send this to the server" — but when
you're already connected to the server over TCP there is nothing to
route.

Operator-side requirement (in Matisse Commander):
  - Display Options > Position Display Mode = nm
  - CounterDrift dialog > Unit = nm
  - Communication Options > Enable Server checked, port matches MATISSE_PORT
The DAQ sends every setpoint in nm vacuum; if Commander's units are cm^-1
the laser will be driven catastrophically off target.

Config via env vars:
  MATISSE_HOST   Matisse Commander network server host (default 127.0.0.1)
  MATISSE_PORT   Matisse Commander network server port (default 30000)
  SIMULATION     "1" to use the MockMatisseDevice in place of TCP
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

MATISSE_HOST = os.environ.get("MATISSE_HOST", "127.0.0.1")
MATISSE_PORT = int(os.environ.get("MATISSE_PORT", "30000"))
SERVER_IP = "0.0.0.0"
SERVER_PORT = 8000

# Replies from Matisse Commander are prefixed with this prompt; we strip it.
_MATISSE_PROMPT = "Matisse>"


class MatisseTCPClient:
    """Persistent line-oriented TCP client for Matisse Commander.

    The protocol is plain ASCII: send `<command>\\n`, read until newline.
    Replies are typically prefixed with `Matisse> ` (the prompt token);
    we strip it so callers see just the payload (`Ok`, `RUNNING`, a float,
    or an error like `1,"general syntax error"`).

    A single socket is held for the lifetime of the laser_server process.
    `ask()` will reconnect once and retry on a transport-level failure
    before propagating the exception."""

    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self._buffer = b""
        self._connect()

    def _connect(self):
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        s.settimeout(self.timeout)
        self.sock = s
        self._buffer = b""
        # Drain any banner / initial prompt Matisse Commander emits on
        # connect. We can't know in advance whether there is one, so we
        # use a very short timeout and discard whatever shows up.
        s.settimeout(0.3)
        try:
            chunk = s.recv(4096)
            if chunk:
                # Banner discarded; only command replies matter.
                pass
        except socket.timeout:
            pass
        s.settimeout(self.timeout)
        print(f"[Matisse-TCP] Connected to Matisse Commander at {self.host}:{self.port}")

    def ask(self, cmd: str) -> str:
        """Send one command, return the single-line reply with the
        `Matisse> ` prompt stripped. Caller is expected to hold any
        higher-level lock; this method is NOT internally synchronised."""
        wire = (cmd.rstrip("\r\n") + "\n").encode("ascii")
        try:
            self.sock.sendall(wire)
            return self._read_reply()
        except (OSError, socket.timeout, ConnectionError) as e:
            print(f"[Matisse-TCP] connection lost ({e}); reconnecting and retrying")
            self._reconnect()
            self.sock.sendall(wire)
            return self._read_reply()

    def _reconnect(self):
        try:
            if self.sock is not None:
                self.sock.close()
        except Exception:
            pass
        self.sock = None
        self._buffer = b""
        self._connect()

    def _read_reply(self) -> str:
        deadline = time.time() + self.timeout
        while b"\n" not in self._buffer:
            if time.time() > deadline:
                raise TimeoutError(
                    f"no reply from Matisse Commander at {self.host}:{self.port} "
                    f"within {self.timeout}s"
                )
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Matisse Commander closed the connection")
            self._buffer += chunk
        line, _, rest = self._buffer.partition(b"\n")
        self._buffer = rest
        text = line.decode("ascii", errors="replace").rstrip("\r").strip()
        # Strip the `Matisse> ` (or `Matisse>`) prompt prefix.
        for prefix in ("Matisse> ", "Matisse>"):
            if text.startswith(prefix):
                text = text[len(prefix):].lstrip()
                break
        return text

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


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
                self.sirah = MatisseTCPClient(MATISSE_HOST, MATISSE_PORT)
            print("[Server] Matisse ready.")
        except Exception as e:
            print(f"[Server] CRITICAL HARDWARE ERROR: {e}")
            print(f"[Server] Could not reach Matisse Commander at "
                  f"{MATISSE_HOST}:{MATISSE_PORT}.")
            print("[Server] Confirm Matisse Commander is running and that")
            print("[Server] Communication Options -> Enable Server is checked.")
            self.sirah = None

    def _ask(self, cmd: str) -> str:
        """Send a raw MCP command and return the prompt-stripped reply.

        We do NOT prepend `#SERVER `: that prefix is the Matisse Commander
        Command Console routing token, useful when typing into the
        Commander UI to forward a command to its server subsystem. When
        we are already connected to the network server over TCP, the
        routing is implicit and adding `#SERVER ` would itself produce
        `1,"general syntax error"`."""
        if self.sirah is None:
            raise RuntimeError("Matisse not initialised")
        with self.lock:
            reply = self.sirah.ask(cmd)
        return reply if reply is not None else ""

    # ---- Reachability ----

    def ping(self) -> bool:
        """Cheap probe used by the DAQ on connect. Returns True if the server
        is up AND the Matisse handle was initialised; False if the server is
        up but the laser is dead. Does not touch the Matisse hardware."""
        return self.sirah is not None

    def is_simulation(self) -> bool:
        """True when the server was launched with SIMULATION=1 and is
        therefore feeding mock data. The DAQ client uses this to refuse to
        run against a sim server when its own simulation_mode is False."""
        return bool(SIMULATION)

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
    print(f" Matisse Commander -> {MATISSE_HOST}:{MATISSE_PORT}")
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
