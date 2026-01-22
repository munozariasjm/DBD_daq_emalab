from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QGroupBox, QListWidget, QListWidgetItem, QAbstractItemView)
from PyQt5.QtCore import pyqtSignal, Qt

class PlotOptionsWidget(QWidget):
    # Signal now emits ordered list of active plot keys
    options_changed = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.item_map = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        grp_opts = QGroupBox("Plot Options (Drag to Reorder)")
        layout_opts = QVBoxLayout()
        grp_opts.setLayout(layout_opts)

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.InternalMove)
        self.list_widget.model().rowsMoved.connect(self.emit_options)
        self.list_widget.itemChanged.connect(self.emit_options)

        # Add Items
        self.add_item('rate', "Event Rate vs Time", checked=True)
        self.add_item('scan', "Scan Results (Rate vs WN)", checked=True)
        self.add_item('laser', "Measured & Target WN vs Time", checked=False)
        self.add_item('volt', "Voltage vs Time", checked=False)
        self.add_item('tof', "ToF Histogram", checked=False)

        layout_opts.addWidget(self.list_widget)
        layout.addWidget(grp_opts)

    def add_item(self, key, text, checked=False):
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        item.setData(Qt.UserRole, key)
        self.list_widget.addItem(item)

    def emit_options(self):
        active_plots = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                active_plots.append(item.data(Qt.UserRole))
        self.options_changed.emit(active_plots)

    def get_options(self):
        # Used for initial state
        active_plots = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                active_plots.append(item.data(Qt.UserRole))
        return active_plots
