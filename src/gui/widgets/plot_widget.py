from PyQt5.QtWidgets import QWidget, QVBoxLayout
import pyqtgraph as pg
import numpy as np

class PlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.plot_items = {} # Map key -> PlotItem
        self.curves = {}     # Map key -> PlotDataItem (or list of them)
        self.active_options = ['rate', 'scan']
        self.auto_scale = True
        self.is_dark_mode = False

        self.set_theme(False, layout_rebuild=False)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.layout_widget = pg.GraphicsLayoutWidget()
        layout.addWidget(self.layout_widget)

        self.rebuild_plots()

    def set_active_plots(self, options):
        self.active_options = options
        self.rebuild_plots()

    def set_auto_scale(self, enabled):
        self.auto_scale = enabled
        for key, p in self.plot_items.items():
            if self.auto_scale:
                p.enableAutoRange(axis=pg.ViewBox.XYAxes)
            else:
                 p.disableAutoRange()

    def set_theme(self, is_dark, layout_rebuild=True):
        self.is_dark_mode = is_dark
        bg_color = 'k' if is_dark else 'w'
        fg_color = '#d5d5d5' if is_dark else 'k'

        pg.setConfigOption('background', bg_color)
        pg.setConfigOption('foreground', fg_color)
        pg.setConfigOptions(antialias=True)

        if hasattr(self, 'layout_widget'):
            self.layout_widget.setBackground(bg_color)

        if layout_rebuild:
            self.rebuild_plots()

    def rebuild_plots(self):
        self.layout_widget.clear()
        self.plot_items = {}
        self.curves = {}

        if isinstance(self.active_options, dict):
            active_list = []
            if self.active_options.get('rate'): active_list.append('rate')
            if self.active_options.get('scan'): active_list.append('scan')
            if self.active_options.get('laser'): active_list.append('laser')
            if self.active_options.get('volt'): active_list.append('volt')
            if self.active_options.get('tof'): active_list.append('tof')
            self.active_options = active_list

        if not self.active_options:
            return

        pen_color = 'g' if self.is_dark_mode else 'g'

        for i, key in enumerate(self.active_options):
            if key == 'rate':
                p = self.layout_widget.addPlot(row=i, col=0, title="Total Event Rate")
                p.setLabel('left', "Events/Bunch")
                p.setLabel('bottom', "Time", units='s')
                p.getAxis('left').enableAutoSIPrefix(False)
                p.showGrid(x=True, y=True)
                curve = p.plot(pen=pg.mkPen(pen_color, width=2))
                self.plot_items['rate'] = p
                self.curves['rate'] = curve

            elif key == 'scan':
                p = self.layout_widget.addPlot(row=i, col=0, title="Scan Results: Events/Bin")
                p.setLabel('bottom', "Wavenumber", units='cm^-1')
                p.setLabel('left', "Rate", units='Events/Bunch')
                p.getAxis('left').enableAutoSIPrefix(False)
                p.getAxis('bottom').enableAutoSIPrefix(False)
                p.showGrid(x=True, y=True)

                color_scan = 'b' if self.is_dark_mode else 'b'
                curve = p.plot(pen=pg.mkPen(color_scan, width=2), symbol='o', symbolSize=5, symbolBrush=color_scan, symbolPen=None)

                cursor = pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen('r', width=1, style=pg.QtCore.Qt.DashLine), label='Target')
                p.addItem(cursor)

                self.plot_items['scan'] = p
                self.curves['scan'] = curve
                self.curves['scan_cursor'] = cursor

            elif key == 'laser':
                p = self.layout_widget.addPlot(row=i, col=0, title="Wavenumber vs Time")
                p.setLabel('left', "Wavenumber", units='cm^-1')
                p.setLabel('bottom', "Time", units='s')
                p.getAxis('left').enableAutoSIPrefix(False)
                p.showGrid(x=True, y=True)
                p.addLegend()

                curve_curr = p.plot(pen=pg.mkPen('r', width=2), name='Measured')
                tgt_color = 'w' if self.is_dark_mode else 'k'
                curve_target = p.plot(pen=pg.mkPen(tgt_color, width=1, style=pg.QtCore.Qt.DashLine), name='Target')

                self.plot_items['laser'] = p
                self.curves['laser_curr'] = curve_curr
                self.curves['laser_target'] = curve_target

            elif key == 'volt':
                p = self.layout_widget.addPlot(row=i, col=0, title="Voltage vs Time")
                p.setLabel('left', "Voltage", units='V')
                p.setLabel('bottom', "Time", units='s')
                p.showGrid(x=True, y=True)
                curve = p.plot(pen=pg.mkPen('m', width=2))
                self.plot_items['volt'] = p
                self.curves['volt'] = curve

            elif key == 'tof':
                p = self.layout_widget.addPlot(row=i, col=0, title="ToF Histogram")
                p.setLabel('bottom', "ToF")
                p.setLabel('left', "Density")
                p.showGrid(x=True, y=True)
                hist_pen = 'w' if self.is_dark_mode else 'k'
                brush_color = (255, 255, 255, 50) if self.is_dark_mode else (0, 0, 0, 50)
                curve = p.plot(stepMode=True, fillLevel=0, fillOutline=True, brush=brush_color, pen=hist_pen)
                self.plot_items['tof'] = p
                self.curves['tof'] = curve

        self.set_auto_scale(self.auto_scale)

    def update_plots(self, history):
        times = history.get('times', [])
        if len(times) == 0: return

        if 'rate' in self.curves:
            self.curves['rate'].setData(times, history['rate'])

        if 'scan' in self.curves:
            scan_data = history.get('scan_data', [])
            if scan_data:
                wls, rates, _, _ = zip(*scan_data)
                self.curves['scan'].setData(wls, rates)
            else:
                self.curves['scan'].setData([], [])

            target_wn_list = history.get('target_wn', [])
            current_target = target_wn_list[-1] if len(target_wn_list) > 0 else 0

            self.curves['scan_cursor'].setValue(current_target)

        if 'laser_curr' in self.curves:
            self.curves['laser_curr'].setData(times, history['wn'])
            self.curves['laser_target'].setData(times, history['target_wn'])

        if 'volt' in self.curves:
            self.curves['volt'].setData(times, history['volt'])

        if 'tof' in self.curves:
            tof_data = history.get('tof_buffer', [])
            if len(tof_data) > 0:
                counts, bin_edges = np.histogram(tof_data, bins=50, density=True)
                self.curves['tof'].setData(bin_edges, counts)
                self.plot_items['tof'].setTitle(f"ToF Histogram ({len(tof_data)} events)")
