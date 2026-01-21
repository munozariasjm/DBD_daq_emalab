from PyQt5.QtWidgets import (QWidget, QVBoxLayout)
import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

class PlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.axes = {}
        self.lines = {}
        self.bars = {}
        self.active_options = {'rate': True, 'scan': True, 'laser': False, 'volt': False, 'tof': False}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Canvas ---
        self.fig = Figure(figsize=(5, 6), dpi=100)
        self.canvas = FigureCanvas(self.fig)
        layout.addWidget(self.canvas)
        layout.setStretchFactor(self.canvas, 1)

        self.rebuild_plots()

    def set_active_plots(self, options):
        self.active_options = options
        self.rebuild_plots()

    def rebuild_plots(self):
        self.fig.clf()
        self.axes = {}
        self.lines = {}
        self.bars = {}

        # Determine active plots from options dict
        active_plots = []
        if self.active_options.get('rate'): active_plots.append('rate')
        if self.active_options.get('scan'): active_plots.append('scan')
        if self.active_options.get('laser'): active_plots.append('laser')
        if self.active_options.get('volt'): active_plots.append('volt')
        if self.active_options.get('tof'): active_plots.append('tof')

        num_plots = len(active_plots)
        if num_plots == 0:
            self.canvas.draw()
            return

        for i, name in enumerate(active_plots):
            ax = self.fig.add_subplot(num_plots, 1, i+1)
            self.axes[name] = ax

            if name == 'rate':
                ax.set_title("Total Event Rate")
                ax.set_ylabel("CPS")
                self.lines['rate'], = ax.plot([], [], 'g-')
                ax.grid(True)
            elif name == 'scan':
                ax.set_title("Scan Results: Events/Bin")
                ax.set_xlabel("Wavenumber (cm^-1)")
                ax.set_ylabel("Rate (cps)")
                self.lines['scan'], = ax.plot([], [], 'b-o')
                self.lines['scan_cursor'], = ax.plot([], [], 'ro')
                ax.grid(True)
            elif name == 'laser':
                ax.set_title("Wavenumber vs Time")
                ax.set_ylabel("Wavenumber (cm^-1)")
                self.lines['laser_curr'], = ax.plot([], [], 'r-', label='Measured (WM)')
                self.lines['laser_target'], = ax.plot([], [], 'k--', label='Target')
                ax.legend(loc='upper right')
                ax.grid(True)
            elif name == 'volt':
                ax.set_title("Voltage vs Time")
                ax.set_ylabel("Voltage (V)")
                self.lines['volt'], = ax.plot([], [], 'm-')
                ax.grid(True)
            elif name == 'tof':
                ax.set_title("ToF Histogram (Accumulated)")
                ax.set_xlabel("ToF")
                ax.set_ylabel("Density")
                # We use a line plot to represent histogram steps for performance
                self.lines['tof'], = ax.plot([], [], 'k-', drawstyle='steps-mid')
                ax.grid(True)

        self.fig.tight_layout()
        self.canvas.draw()

    def update_plots(self, history):
        # history is a dict containing the deque lists
        times = history.get('times', [])
        if not times: return

        # Rate
        if 'rate' in self.lines:
            self.lines['rate'].set_data(times, history['rate'])
            ax = self.axes['rate']
            ax.set_xlim(max(0, times[-1] - 10), times[-1] + 1)
            valid_rates = [r for r in history['rate'] if r is not None]
            if valid_rates:
                ax.set_ylim(0, max(max(valid_rates), 10) * 1.2)

        # Scan
        if 'scan' in self.lines:
            scan_data = history.get('scan_data', [])
            if scan_data:
                wls, rates = zip(*scan_data)
                self.lines['scan'].set_data(wls, rates)
                ax = self.axes['scan']
                ax.set_xlim(min(wls)-0.1, max(wls)+0.1)
                if rates:
                    ax.set_ylim(0, max(rates) * 1.2)

            target_wn = history.get('target_wn', 0)
            self.lines['scan_cursor'].set_data([target_wn], [0])

        # Laser
        if 'laser_curr' in self.lines:
            self.lines['laser_curr'].set_data(times, history['wn'])
            self.lines['laser_target'].set_data(times, history['target_wn'])
            ax = self.axes['laser']
            ax.set_xlim(max(0, times[-1] - 10), times[-1] + 1)

            all_wns = [w for w in (list(history['wn']) + list(history['target_wn'])) if w and w > 0]
            if all_wns:
                min_y, max_y = min(all_wns), max(all_wns)
                span = max_y - min_y
                if span < 0.1: span = 1.0
                ax.set_ylim(min_y - span*0.2, max_y + span*0.2)

        # Volt
        if 'volt' in self.lines:
            self.lines['volt'].set_data(times, history['volt'])
            ax = self.axes['volt']
            ax.set_xlim(max(0, times[-1] - 10), times[-1] + 1)
            all_volts = list(history['volt'])
            if all_volts:
                min_v, max_v = min(all_volts), max(all_volts)
                v_span = max_v - min_v
                if v_span < 0.1: v_span = 0.1
                ax.set_ylim(min_v - v_span*0.2, max_v + v_span*0.2)

        # ToF
        if 'tof' in self.lines:
            tof_data = history.get('tof_buffer', [])
            if tof_data and len(tof_data) > 0:
                # Compute histogram
                counts, bin_edges = np.histogram(tof_data, bins=50, density=True)
                centers = (bin_edges[:-1] + bin_edges[1:]) / 2

                self.lines['tof'].set_data(centers, counts)
                ax = self.axes['tof']
                ax.set_xlim(min(centers), max(centers))
                ax.set_ylim(0, max(counts) * 1.1)
                ax.set_title(f"ToF Histogram ({len(tof_data)} events)")

        self.canvas.draw_idle()
