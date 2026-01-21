
import sys
import os
import unittest
from PyQt5.QtWidgets import QApplication

# Adjust path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.gui.widgets.tof_histogram_widget import ToFHistogramWidget, ToFDialog

class TestToFWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create an app instance for Qt
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_widget_instantiation(self):
        widget = ToFHistogramWidget()
        self.assertIsNotNone(widget)

    def test_dialog_instantiation(self):
        data = [100, 200, 300, 150]
        dialog = ToFDialog(data)
        self.assertIsNotNone(dialog)

        # Test plot update
        dialog.hist_widget.update_plot()
        # No crash means success roughly

if __name__ == '__main__':
    unittest.main()
