import sys
import os
import time
import threading

# Add src to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import from the QT GUI file (which contains the updated DAQSystem)
from dev.daq_scanner_gui_qt import DAQSystem

def test_stop_while_paused():
    print("[TEST] Initializing DAQSystem...")
    daq = DAQSystem()
    daq.start()

    # Configure Scan
    daq.scanner.configure(min_wn=16666.0, max_wn=16667.0, step=0.1, stop_mode='time', stop_value=10)

    print("[TEST] Starting Scan...")
    daq.scanner.start() # Start directly

    # Wait for a bit to let it run
    time.sleep(1.0)

    if not daq.scanner.is_alive():
        print("[TEST] ERROR: Scanner died prematurely.")
        return

    print("[TEST] Pausing Scan...")
    daq.scanner.pause()
    time.sleep(0.5)

    status = daq.scanner.get_status()
    if not status['is_paused']:
        print("[TEST] ERROR: Scanner did not pause.")
        return
    print("[TEST] Scanner is paused.")

    print("[TEST] Stopping Scan (expecting immediate return due to deadlock fix)...")
    t0 = time.time()
    daq.scanner.stop(wait=True) # Testing blocking stop first to ensure it unblocks
    dt = time.time() - t0

    if daq.scanner.is_alive():
        print(f"[TEST] ERROR: Scanner still alive after stop() took {dt:.2f}s")
    else:
        print(f"[TEST] SUCCESS: Scanner stopped in {dt:.2f}s")

    daq.stop()

if __name__ == "__main__":
    test_stop_while_paused()
