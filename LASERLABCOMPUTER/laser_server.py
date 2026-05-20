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
import struct
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

    Wire protocol: LabVIEW's TCP "Standard" framing — every message
    (in both directions) is preceded by a 4-byte big-endian unsigned
    length field; the payload is exactly that many bytes of ASCII text.
    Matisse Commander is built on LabVIEW and uses this framing on its
    Network Server. Sending raw line-terminated commands causes
    `API Network Server Receive.vi` to read the first 4 bytes as the
    declared payload length and block waiting for the rest until it
    times out (LabVIEW Error 56).

    Replies are typically prefixed with `Matisse> ` inside the payload;
    we strip that so callers see just the meaningful text.

    A single socket is held for the lifetime of the laser_server process.
    `ask()` will reconnect once and retry on a transport-level failure
    before propagating the exception."""

    _HEADER_FMT = ">I"
    _HEADER_LEN = 4
    _MAX_PAYLOAD = 1_000_000  # sanity cap; real replies are tens of bytes

    def __init__(self, host: str, port: int, timeout: float = 120.0):
        # 120 s default: opening MCP dialogs (CounterDrift / GoTo) on a
        # cold Matisse Commander -- first MCP call after launch, or while
        # the Wavemeter Plugin is still initialising its widgets -- can
        # take 30-90 s before the reply lands. Status/getter commands
        # finish in milliseconds, so the high ceiling only matters on the
        # rare slow ops; it's not a per-op latency, just a worst-case
        # ceiling before we declare the connection broken.
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
        # Drain any bytes Matisse Commander may emit on connect. Loop with
        # a short read timeout until recv blocks (no more pending bytes).
        # Any data here would mis-correlate subsequent replies if left in
        # the buffer.
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
        NOT internally synchronised.

        On any failure (timeout or socket error) we reopen the connection
        and retry once. The reconnect guarantees that a *late* reply from
        a timed-out previous command can't pollute the next request's
        reply buffer. Matisse Commander may log Error 62 ('TCP Write
        ... connection aborted') when this happens — that's a transient,
        not a fault. The timeout is set generously (30 s) so this is
        rare in practice."""
        payload = cmd.encode("ascii")
        wire = struct.pack(self._HEADER_FMT, len(payload)) + payload
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
        header = self._recv_exactly(self._HEADER_LEN)
        (length,) = struct.unpack(self._HEADER_FMT, header)
        if length > self._MAX_PAYLOAD:
            raise ValueError(
                f"Implausible reply length {length} bytes from Matisse Commander; "
                "framing protocol mismatch?"
            )
        payload = self._recv_exactly(length) if length else b""
        text = payload.decode("ascii", errors="replace").rstrip("\r\n").strip()
        # Strip the `Matisse> ` (or `Matisse>`) prompt prefix.
        for prefix in ("Matisse> ", "Matisse>"):
            if text.startswith(prefix):
                text = text[len(prefix):].lstrip()
                break
        return text

    def _recv_exactly(self, n: int) -> bytes:
        # Use a short per-recv timeout so we can emit a heartbeat during
        # long waits (cold dialog opens can take 30-90 s) instead of going
        # silent. The total wait is still bounded by self.timeout.
        deadline = time.time() + self.timeout
        tick = 5.0
        next_tick = time.time() + tick
        start = time.time()
        while len(self._buffer) < n:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"timed out waiting for {n} bytes from Matisse Commander "
                    f"after {self.timeout:.0f}s"
                )
            slot = min(remaining, max(0.01, next_tick - time.time()))
            self.sock.settimeout(slot)
            try:
                chunk = self.sock.recv(max(4096, n - len(self._buffer)))
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
        # Restore full timeout for subsequent operations.
        self.sock.settimeout(self.timeout)
        data = bytes(self._buffer[:n])
        self._buffer = self._buffer[n:]
        return data

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

        Logs the wire-level command + reply + duration so the operator can
        see exactly what the Matisse is being asked at any moment. We do
        NOT prepend `#SERVER `: that prefix is the Matisse Commander
        Command Console routing token, useful when typing into the
        Commander UI to forward a command to its server subsystem. When
        we are already connected to the network server over TCP, the
        routing is implicit and adding `#SERVER ` would itself produce
        `1,"general syntax error"`."""
        if self.sirah is None:
            raise RuntimeError("Matisse not initialised")
        t0 = time.perf_counter()
        with self.lock:
            reply = self.sirah.ask(cmd)
        ms = (time.perf_counter() - t0) * 1000
        reply = reply if reply is not None else ""
        print(
            f"[{_ts()}] [MCP]    {_truncate(cmd, 80)} -> "
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
