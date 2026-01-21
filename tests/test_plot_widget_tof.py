
import sys
import os
import unittest
import numpy as np
from PyQt5.QtWidgets import QApplication

# Adjust path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.gui.widgets.plot_widget import PlotWidget

class TestPlotWidgetToF(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_tof_plot(self):
        widget = PlotWidget()

        # Enable ToF
        widget.set_active_plots({'tof': True})

        # Create fake history with ToF data
        history = {
            'times': [1, 2, 3],
            'rate': [10, 10, 10],
            'tof_buffer': [100, 105, 110, 100, 120, 115] * 10
        }

        # Update plots
        widget.update_plots(history)

        # Check if line exists
        self.assertIn('tof', widget.lines)
        line = widget.lines['tof']
        x, y = line.get_data()

        self.assertTrue(len(x) > 0)
        self.assertTrue(len(y) > 0)
        self.assertEqual(len(x), len(y))

        print("ToF Plot test passed. Histogram generated.")

if __name__ == '__main__':
    unittest.main()
