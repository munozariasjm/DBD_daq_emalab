import sys
import os
import time
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque
import threading

# Add src to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.simulation.sim_sensors import MockMultimeter, MockSpectrometreReader, MockWavenumberReader

# Configuration
WINDOW_SIZE = 100
UPDATE_INTERVAL = 100 # ms

class SensorVisualizer:
    def __init__(self):
        # Initialize Sensors
        self.multimeter = MockMultimeter(port="COM1")

        self.spec_reader = MockSpectrometreReader()
        self.spec_reader.start()

        self.wave_reader = MockWavenumberReader()
        self.wave_reader.start()

        self.start_time = time.time()

        # Data storage
        self.times = deque(maxlen=WINDOW_SIZE)
        self.voltages = deque(maxlen=WINDOW_SIZE)
        self.spectrum_peaks = deque(maxlen=WINDOW_SIZE)
        self.wavenumbers = {
            1: deque(maxlen=WINDOW_SIZE),
            2: deque(maxlen=WINDOW_SIZE),
            3: deque(maxlen=WINDOW_SIZE),
            4: deque(maxlen=WINDOW_SIZE)
        }

        # Setup Plot
        self.fig, (self.ax_volt, self.ax_spec, self.ax_wave) = plt.subplots(3, 1, figsize=(8, 10), sharex=True)

        # Voltage Plot
        self.line_volt, = self.ax_volt.plot([], [], 'r-', label='Voltage (V)')
        self.ax_volt.set_ylabel('Voltage (V)')
        self.ax_volt.legend(loc='upper right')
        self.ax_volt.set_ylim(0, 5)
        self.ax_volt.grid(True)

        # Spectrum Plot
        self.line_spec, = self.ax_spec.plot([], [], 'b-', label='Spectrum Peak (nm)')
        self.ax_spec.set_ylabel('Wavelength (nm)')
        self.ax_spec.legend(loc='upper right')
        self.ax_spec.set_ylim(590, 610)
        self.ax_spec.grid(True)

        # Wavenumber Plot
        self.lines_wave = {}
        colors = ['c', 'm', 'y', 'k']
        for i in range(4):
            ch = i + 1
            line, = self.ax_wave.plot([], [], label=f'WN Ch{ch}', color=colors[i])
            self.lines_wave[ch] = line

        self.ax_wave.set_ylabel('Wavenumber (cm-1)')
        self.ax_wave.set_xlabel('Time Step')
        self.ax_wave.legend(loc='upper right')
        self.ax_wave.grid(True)
        # Auto-scale this one as ranges differ (1000, 2000, 3000, 4000)
        self.ax_wave.set_ylim(0, 5000)

    def update(self, frame):
        # Read Data
        voltage = self.multimeter.getVoltage()
        spec_peak = self.spec_reader.spectrum
        wns = self.wave_reader.get_wavenumbers()

        self.times.append(len(self.times)) # Just use simple counter index
        self.voltages.append(voltage)
        self.spectrum_peaks.append(spec_peak)

        for i, val in enumerate(wns):
            self.wavenumbers[i+1].append(val)

        # Update Plots
        x_data = list(range(len(self.times)))

        self.line_volt.set_data(x_data, list(self.voltages))
        self.line_spec.set_data(x_data, list(self.spectrum_peaks))

        for ch in range(1, 5):
            self.lines_wave[ch].set_data(x_data, list(self.wavenumbers[ch]))

        self.ax_wave.set_xlim(0, max(len(self.times), 10))

        return [self.line_volt, self.line_spec] + list(self.lines_wave.values())

    def run(self):
        try:
            ani = animation.FuncAnimation(self.fig, self.update, interval=UPDATE_INTERVAL, blit=False)
            plt.tight_layout()
            plt.show()
        except KeyboardInterrupt:
            pass
        finally:
            print("Stopping sensors...")
            self.spec_reader.stop()
            self.wave_reader.stop()
            self.spec_reader.join()
            self.wave_reader.join()

if __name__ == "__main__":
    viz = SensorVisualizer()
    viz.run()
