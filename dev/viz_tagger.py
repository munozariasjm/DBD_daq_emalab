import sys
import os
import time
import queue
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
from collections import deque

# Add src to python path to allow imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.simulation.sim_tagger import MockTagger

# Configuration
UPDATE_INTERVAL = 200  # ms
HIST_BINS = 100
MAX_TOF = 0.020 # 20ms

class TaggerVisualizer:
    def __init__(self):
        self.tagger = MockTagger()
        self.tagger.start_reading()

        # Cumulative Histogram Data
        self.hist_counts = np.zeros(HIST_BINS)
        self.bin_edges = np.linspace(0, MAX_TOF, HIST_BINS + 1)
        self.bin_centers = (self.bin_edges[:-1] + self.bin_edges[1:]) / 2

        # Initialize plotting
        self.fig, (self.ax_hist, self.ax_rate) = plt.subplots(2, 1, figsize=(8, 10))

        # --- Histogram Plot ---
        # We use 'step' or 'bar' for pre-binned data
        self.bar_container = self.ax_hist.bar(self.bin_centers, self.hist_counts, width=MAX_TOF/HIST_BINS, color='blue', alpha=0.7)
        self.ax_hist.set_title(f"Cumulative Time of Flight Distribution (Channel 1)")
        self.ax_hist.set_xlabel("Time of Flight (s)")
        self.ax_hist.set_ylabel("Total Counts")
        self.ax_hist.set_xlim(0, MAX_TOF)

        # --- Rate Plot ---
        self.start_time = time.time()
        self.times = deque(maxlen=50)
        self.rates = deque(maxlen=50)
        self.line_rate, = self.ax_rate.plot([], [], 'r-', label='CPS (Ch1)')

        self.ax_rate.set_title("Count Rate Stability")
        self.ax_rate.set_xlabel("Time (s)")
        self.ax_rate.set_ylabel("CPS")
        self.ax_rate.set_ylim(0, 350)
        self.ax_rate.grid(True)
        self.ax_rate.legend()

        # Stats
        self.event_count_since_last = 0
        self.last_calc_time = time.time()
        self.total_events = 0

    def update(self, frame):
        # Fetch data
        raw_data = self.tagger.get_data()
        current_time = time.time()

        new_tofs = []

        # Process
        for entry in raw_data:
            # [packet_num, events, channel, relative_time, absolute_time]
            channel = entry[2]
            tof = entry[3]

            if channel == 1:
                new_tofs.append(tof)
                self.event_count_since_last += 1
                self.total_events += 1

        # Update Histogram
        if new_tofs:
            # Bin the new data efficiently using numpy
            new_counts, _ = np.histogram(new_tofs, bins=self.bin_edges)
            self.hist_counts += new_counts

            # Normalize for display (Probability Density or simply Fraction)
            # Let's use simple Fraction (Probability) where sum(heights) = 1
            # If user wants PDF (area=1), we'd divide by (total * bin_width)
            # "Normalized" usually implies making the integral 1, so PDF.
            # But "Probability" per bin is often easier to read.
            # Let's do PDF (Density) to match "Gaussian Distribution" concepts.

            if self.total_events > 0:
                bin_width = self.bin_edges[1] - self.bin_edges[0]
                norm_counts = self.hist_counts / (self.total_events * bin_width)
            else:
                norm_counts = self.hist_counts

            # Update the bars
            max_val = np.max(norm_counts) if len(norm_counts) > 0 else 1.0
            self.ax_hist.set_ylim(0, max_val * 1.1)
            self.ax_hist.set_title(f"Normalized Time of Flight PDF (Total: {self.total_events})")
             # Update Y label to reflect normalization
            self.ax_hist.set_ylabel("Probability Density")

            for rect, height in zip(self.bar_container, norm_counts):
                rect.set_height(height)

        # Update Rate
        dt = current_time - self.last_calc_time
        if dt > 0.5: # Update rate every 0.5s
            rate = self.event_count_since_last / dt
            self.times.append(current_time - self.start_time)
            self.rates.append(rate)

            self.line_rate.set_data(list(self.times), list(self.rates))
            self.ax_rate.set_xlim(max(0, self.times[-1] - 10) if self.times else 0, self.times[-1] + 1 if self.times else 10)

            self.event_count_since_last = 0
            self.last_calc_time = current_time

        return list(self.bar_container) + [self.line_rate]

    def run(self):
        ani = animation.FuncAnimation(self.fig, self.update, interval=UPDATE_INTERVAL, blit=False)
        plt.tight_layout()
        plt.show()
        self.tagger.stop()

if __name__ == "__main__":
    viz = TaggerVisualizer()
    viz.run()
