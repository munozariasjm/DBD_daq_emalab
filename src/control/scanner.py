import time
import threading
import numpy as np

class Scanner(threading.Thread):
    def __init__(self, laser, wavemeter=None):
        super().__init__()
        self.laser = laser
        self.wavemeter = wavemeter

        self.running = False
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set() # Set means "Not Paused" (Running)

        # Scan Configuration
        # Scan Configuration
        self.min_wn = 16666.0
        self.max_wn = 16680.0
        self.step_size = 0.5 # cm^-1
        self.stop_mode = 'events' # 'events' or 'time'
        self.stop_value = 100 # count or seconds

        # State
        self.current_wavenumber = 0.0 # Target Wavenumber
        self.current_bin_index = 0
        self.accumulated_events = 0
        self.accumulated_bunches = 0
        self.is_accumulating = False # If True, we are in the "Measurement" phase

        # Results (for plotting)
        # List of (wavelength, rate_cps)
        self.scan_progress = []

        # Timing for ETA
        self.start_timestamp = 0
        self.bins_completed = 0
        self.total_bins = 0

    def set_wavemeter(self, wavemeter):
        self.wavemeter = wavemeter

    def wavenumber_to_wavelength(self, wn):
        """Converts cm^-1 to nm."""
        if wn == 0: return 0.0
        return 1e7 / wn

    def reset(self):
        """Clears scan progress and internal counters."""
        self.scan_progress = []
        self.bins_completed = 0
        self.start_timestamp = 0
        self.accumulated_events = 0
        self.accumulated_bunches = 0
        self.current_bin_index = 0
        print("[Scanner] Scan history reset.")

    def configure(self, min_wn, max_wn, step, stop_mode='events', stop_value=100):
        self.min_wn = min_wn
        self.max_wn = max_wn
        self.step_size = step
        self.stop_mode = stop_mode
        self.stop_value = stop_value

    def run(self):
        self.running = True
        self.start_timestamp = time.time()

        # Create range inclusive of max (approx)
        steps = int(round((self.max_wn - self.min_wn) / self.step_size)) + 1
        wavenumbers = np.linspace(self.min_wn, self.max_wn, steps)
        self.total_bins = len(wavenumbers)
        self.bins_completed = 0

        print(f"[Scanner] Starting scan: {len(wavenumbers)} bins from {self.min_wn} to {self.max_wn} cm^-1")

        try:
            for i, wn in enumerate(wavenumbers):
                if self.stop_event.is_set(): break
                self.wait_for_pause()

                self.current_bin_index = i
                self.current_wavenumber = wn

                # 1. Move Laser (Convert to nm)
                target_nm = self.wavenumber_to_wavelength(wn)
                self.laser.set_wavelength(target_nm)

                # 2. Wait for stable
                # We wait until the laser reports it is stable at the new wavelength
                while not self.laser.is_stable():
                    if self.stop_event.is_set(): return
                    self.wait_for_pause()
                    time.sleep(0.05)

                # 3. Start Accumulating
                self.accumulated_events = 0
                self.accumulated_bunches = 0
                self.bin_measured_wns = [] # Track live wavemeter readings for this bin
                self.is_accumulating = True
                self.bin_paused_duration = 0.0 # Track time spent paused

                start_time = time.time()
                # print(f"[Scanner Debug] Start Accumulating. Mode={self.stop_mode}, Value={self.stop_value}")

                # Wait loop
                while True:
                    if self.stop_event.is_set(): return
                    self.wait_for_pause()

                    # Check Stop Condition
                    current_time = time.time()
                    current_duration = current_time - start_time - self.bin_paused_duration

                    if self.stop_mode == 'events':
                        if self.accumulated_events >= self.stop_value:
                            break
                    elif self.stop_mode == 'bunches':
                        if self.accumulated_bunches >= self.stop_value:
                            break
                    elif self.stop_mode == 'time':
                        if current_duration >= self.stop_value:
                            break

                    # Track Measured Wavenumber
                    if self.wavemeter:
                        wn_status = self.wavemeter.get_wavenumbers()
                        if wn_status and wn_status[0] > 0:
                            self.bin_measured_wns.append(wn_status[0])

                    time.sleep(0.005)

                # 4. Stop Accumulating
                self.is_accumulating = False

                total_elapsed = time.time() - start_time
                effective_duration = total_elapsed - self.bin_paused_duration
                rate = self.accumulated_events / effective_duration if effective_duration > 0 else 0

                # Calculate average measured wavenumber for this bin
                if self.bin_measured_wns:
                    avg_wn = sum(self.bin_measured_wns) / len(self.bin_measured_wns)
                else:
                    avg_wn = wn # Fallback to target

                print(f"[Scanner] Bin {wn:.4f} cm^-1 (Avg Measured: {avg_wn:.4f} cm^-1) done. {self.accumulated_events} events, {self.accumulated_bunches} bunches in {effective_duration:.2f}s (effective) ({rate:.1f} cps)")
                self.scan_progress.append((avg_wn, rate))
                self.bins_completed += 1
            print("[Scanner] Scan complete.")
        except Exception as e:
            print(f"[Scanner] Crashed: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.running = False

    def wait_for_pause(self):
        """Blocks if pause_event is cleared."""
        if not self.pause_event.is_set():
            print("[Scanner] Waiting for resume...")
            t0 = time.time()
            self.pause_event.wait()
            self.bin_paused_duration += (time.time() - t0)

    def pause(self):
        self.pause_event.clear()
        print("[Scanner] Paused.")

    def resume(self):
        self.pause_event.set()
        print("[Scanner] Resumed.")

    def get_status(self):
        """Returns a dict with current status for GUI."""
        elapsed = time.time() - self.start_timestamp if self.start_timestamp > 0 else 0

        # Estimate Remaining
        eta_seconds = 0
        if self.bins_completed > 0:
            avg_per_bin = elapsed / self.bins_completed
            remaining_bins = self.total_bins - self.bins_completed
            eta_seconds = remaining_bins * avg_per_bin

        # Deriving Measured Wavenumber from Wavemeter
        measured_wn = 0.0
        if self.wavemeter:
            wns = self.wavemeter.get_wavenumbers()
            if wns and wns[0] > 0:
                measured_wn = wns[0]

        return {
            "target_wn": self.current_wavenumber,
            "measured_wn": measured_wn,
            "stop_mode": self.stop_mode,
            "stop_value": self.stop_value,
            "accumulated": self.accumulated_events,
            "accumulated_bunches": self.accumulated_bunches,
            "bin_index": self.current_bin_index,
            "total_bins": self.total_bins,
            "bins_completed": self.bins_completed,
            "eta_seconds": eta_seconds,
            "is_paused": not self.pause_event.is_set(),
            "is_stopping": self.stop_event.is_set(),
            "is_running": self.running
        }

    def stop(self, wait=True):
        self.stop_event.set()
        # If paused, enforce resume so the thread can wake up and exit
        if not self.pause_event.is_set():
            self.pause_event.set()

        if wait:
            self.join()

    def report_event(self, is_bunch=False):
        """Called by the data pipeline when an event is processed while accumulating."""
        if self.is_accumulating and self.pause_event.is_set():
            if is_bunch:
                self.accumulated_bunches += 1
            else:
                self.accumulated_events += 1
