import sys
import os
import time
import glob

# Add src path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.control.daq_system import DAQSystem

def test_logging():
    print("Initializing DAQ...")
    daq = DAQSystem()
    daq.start()

    print("Starting Scan (2s)...")
    daq.start_scan(16000, 16001, 0.5, 'time', 2.0)

    while daq.scanner.is_alive() and daq.scanner.running:
        status = daq.scanner.get_status()
        print(f"Scanning... {status['accumulated']} events")
        time.sleep(0.5)

    # Wait a bit for saver to flush and stop
    time.sleep(1.0)
    daq.stop()

    print("Scan finished.")

    # Check for files
    files = glob.glob("data/scan_*.csv")
    files.sort(key=os.path.getmtime)

    if not files:
        print("FAIL: No log file created.")
        sys.exit(1)

    latest_file = files[-1]
    print(f"Found log file: {latest_file}")

    # Check content
    with open(latest_file, 'r') as f:
        lines = f.readlines()
        print(f"Log file has {len(lines)} lines.")
        if len(lines) > 1:
            header = lines[0]
            if "bunch_id" in header:
                print("PASS: Data written to log and 'bunch_id' found.")
            else:
                 print(f"FAIL: 'bunch_id' NOT found in header: {header}")
        else:
            print("FAIL: Log file empty or header only.")

if __name__ == "__main__":
    test_logging()
