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

import functools
import os
import sys
import socket
import threading
import time
from datetime import datetime
from xmlrpc.server import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler
from socketserver import ThreadingMixIn


def _ts() -> str:
    """Wall-clock timestamp prefix, millisecond resolution."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."


def _format_args(args, kwargs) -> str:
    parts = [repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()]
    return _truncate(", ".join(parts), 80)


def _log_call(method):
    """Wrap a LaserServerInterface method so every XML-RPC invocation prints
    its name, args, result, and wall-clock duration. Re-raises so XML-RPC
    fault semantics survive."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        t0 = time.perf_counter()
        try:
            result = method(self, *args, **kwargs)
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            print(
                f"[{_ts()}] [Server] {method.__name__}({_format_args(args, kwargs)}) "
                f"RAISED {type(e).__name__}: {e} ({ms:.0f} ms)"
            )
            raise
        ms = (time.perf_counter() - t0) * 1000
        print(
            f"[{_ts()}] [Server] {method.__name__}({_format_args(args, kwargs)}) "
            f"-> {_truncate(repr(result), 60)} ({ms:.0f} ms)"
        )
        return result
    return wrapper


class _QuietRequestHandler(SimpleXMLRPCRequestHandler):
    """Silences BaseHTTPRequestHandler's default access log
    (`1.2.3.4 - - [date] "POST /RPC2 HTTP/1.1" 200 -`) so the per-call
    decorator's line is the only thing on stdout for each request."""

    def log_message(self, format, *args):
        pass

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
    """Persistent TCP client for Matisse Commander's network server.

    Wire protocol per the Matisse Programmer's Guide v2.4.8, Ch. 3
    ("Matisse Commander TCP Network Server"):

      - The server is a VISA RELAY -- commands are relayed verbatim to
        the underlying Matisse device. VISA INSTR communication is
        line-oriented ASCII, so the TCP wire format is the same: send
        a command terminated by CR-LF, read the reply terminated by LF.
      - Server-only commands (`MCP_*`, `MC.*`) MUST be prefixed with
        `#SERVER `. Without the prefix the server forwards the bare
        token to the laser DSP, which replies `1,"general syntax error"`.
        The prefix is applied at the LaserServerInterface._ask layer.
      - Errors are returned as `Error: <message>` (page 13).
      - Replies may be prefixed with `Matisse> ` (the Interactive Shell
        prompt); we strip that so callers see just the payload.

    A single socket is held for the lifetime of the laser_server process.
    `ask()` reopens once and retries on a transport-level failure before
    propagating the exception. While waiting for a slow reply we emit a
    periodic heartbeat so the operator can see the wait is active."""

    def __init__(self, host: str, port: int, timeout: float = 120.0):
        # 120 s default: a cold Matisse Commander (first MCP call after
        # launch, or while a plugin is still initialising) can take many
        # seconds to reply. Status/getter commands finish in ms; the
        # high ceiling only matters on the rare slow ops.
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
        # Drain any banner Matisse may emit on connect. We can't know if
        # there is one; loop with a short timeout until recv blocks.
        s.settimeout(0.3)
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
        except socket.timeout:
            pass
        s.settimeout(self.timeout)
        print(f"[Matisse-TCP] Connected to Matisse Commander at {self.host}:{self.port}")

    def ask(self, cmd: str) -> str:
        """Send one command, return the prompt-stripped reply payload.

        Caller is expected to hold any higher-level lock; this method is
        NOT internally synchronised. On any failure (timeout or socket
        error) we reopen the connection and retry once before propagating."""
        wire = (cmd.rstrip("\r\n") + "\r\n").encode("ascii")
        try:
            self.sock.sendall(wire)
            return self._read_reply()
        except (OSError, socket.timeout, ConnectionError, TimeoutError) as e:
            print(f"[Matisse-TCP] {type(e).__name__}: {e}; reconnecting and retrying once")
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
        """Read until the next LF, decode, strip CR / Matisse> prompt.

        Uses 5 s recv slices so a slow reply prints a heartbeat instead
        of going silent for the full 120 s ceiling."""
        deadline = time.time() + self.timeout
        tick = 5.0
        next_tick = time.time() + tick
        start = time.time()
        while b"\n" not in self._buffer:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"no reply (LF) from Matisse Commander at "
                    f"{self.host}:{self.port} within {self.timeout:.0f}s"
                )
            slot = min(remaining, max(0.01, next_tick - time.time()))
            self.sock.settimeout(slot)
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                if time.time() >= next_tick:
                    elapsed = time.time() - start
                    print(
                        f"[{_ts()}] [Matisse-TCP] still waiting for reply "
                        f"({elapsed:.0f} s elapsed of {self.timeout:.0f} s)..."
                    )
                    next_tick = time.time() + tick
                continue
            if not chunk:
                raise ConnectionError("Matisse Commander closed the connection")
            self._buffer += chunk
        self.sock.settimeout(self.timeout)
        idx = self._buffer.find(b"\n")
        line = self._buffer[:idx]
        self._buffer = self._buffer[idx + 1:]
        text = line.decode("ascii", errors="replace").rstrip("\r").strip()
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
        """Send an MCP command and return the prompt-stripped reply.

        Per the Matisse Programmer's Guide v2.4.8, Ch. 3 ("Server-Only
        Commands"): every `MCP_*` / `MC.*` command is "Server-Only" and
        MUST be prefixed with `#SERVER ` when sent over the TCP Network
        Server. Without the prefix Matisse Commander forwards the bare
        token to the laser DSP, which replies `1,"general syntax error"`.

        The prefix is added here, exactly once, so the per-method wrappers
        below pass the unprefixed command names through.

        Logs the wire-level command + reply + duration so the operator can
        see exactly what the Matisse is being asked at any moment."""
        if self.sirah is None:
            raise RuntimeError("Matisse not initialised")
        full = cmd if cmd.lstrip().startswith("#SERVER") else f"#SERVER {cmd}"
        t0 = time.perf_counter()
        with self.lock:
            reply = self.sirah.ask(full)
        ms = (time.perf_counter() - t0) * 1000
        reply = reply if reply is not None else ""
        print(
            f"[{_ts()}] [MCP]    {_truncate(full, 80)} -> "
            f"{_truncate(reply, 80)} ({ms:.0f} ms)"
        )
        return reply

    # ---- Reachability ----

    @_log_call
    def ping(self) -> bool:
        """Cheap probe used by the DAQ on connect. Returns True if the server
        is up AND the Matisse handle was initialised; False if the server is
        up but the laser is dead. Does not touch the Matisse hardware."""
        return self.sirah is not None

    @_log_call
    def is_simulation(self) -> bool:
        """True when the server was launched with SIMULATION=1 and is
        therefore feeding mock data. The DAQ client uses this to refuse to
        run against a sim server when its own simulation_mode is False."""
        return bool(SIMULATION)

    # ---- CounterDrift ----

    @_log_call
    def cd_open(self) -> bool:
        try:
            self._ask("MCP_WM_CounterDrift")
            return True
        except Exception as e:
            print(f"[{_ts()}] [Server] cd_open error: {e}")
            return False

    @_log_call
    def cd_setpoint(self, nm: float) -> bool:
        try:
            self._ask(f"MCP_WM.Counterdrift Setpoint {float(nm)}")
            return True
        except Exception as e:
            print(f"[{_ts()}] [Server] cd_setpoint({nm}) error: {e}")
            return False

    @_log_call
    def cd_activate(self, state: bool) -> bool:
        try:
            self._ask(f"MCP_WM.Counterdrift Activate {'true' if state else 'false'}")
            return True
        except Exception as e:
            print(f"[{_ts()}] [Server] cd_activate({state}) error: {e}")
            return False

    @_log_call
    def cd_get_wavelength(self) -> float:
        try:
            reply = self._ask("MCP_WM_GET_WAVELENGTH")
            return float(reply.split()[0])
        except Exception as e:
            print(f"[{_ts()}] [Server] cd_get_wavelength error: {e}")
            return 0.0

    # ---- GoTo ----

    @_log_call
    def goto_open(self) -> bool:
        try:
            self._ask("MCP_WM_GotoPosition")
            return True
        except Exception as e:
            print(f"[{_ts()}] [Server] goto_open error: {e}")
            return False

    @_log_call
    def goto_set(self, nm: float) -> bool:
        try:
            self._ask(f"MCP_WM.GoTo Goto {float(nm)}")
            return True
        except Exception as e:
            print(f"[{_ts()}] [Server] goto_set({nm}) error: {e}")
            return False

    @_log_call
    def goto_start(self) -> bool:
        try:
            self._ask("MCP_WM.GoTo Start")
            return True
        except Exception as e:
            print(f"[{_ts()}] [Server] goto_start error: {e}")
            return False

    @_log_call
    def goto_status(self) -> str:
        try:
            return self._ask("MCP_WM.GoTo status").strip().upper() or "STOP"
        except Exception as e:
            print(f"[{_ts()}] [Server] goto_status error: {e}")
            return "STOP"

    # ---- Lifecycle ----

    @_log_call
    def close(self) -> bool:
        try:
            if self.sirah is not None:
                with self.lock:
                    self.sirah.close()
            return True
        except Exception as e:
            print(f"[{_ts()}] [Server] close error: {e}")
            return False


if __name__ == "__main__":
    socket.setdefaulttimeout(120)
    server = ThreadedXMLRPCServer(
        (SERVER_IP, SERVER_PORT),
        requestHandler=_QuietRequestHandler,
        allow_none=True,
    )
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
