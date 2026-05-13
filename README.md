# Discrete Beamline DAQ (DBD)

Discrete Beamline DAQ

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd DAQ2
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Running the Application

To start the GUI:
```bash
python main.py
```

### Simulation vs. Real Hardware
The system defaults to **Simulation Mode** (no hardware needed). To switch:

1. Open `settings.json`.
2. Set `"simulation_mode": false`.
3. Fill in the driver logic in `src/devices/` for your specific hardware.

### Matisse setup (one-time, real hardware only)

Laser stabilisation is delegated to the Matisse's own firmware CounterDrift
loop, driven over MCP commands by `LASERLABCOMPUTER/laser_server.py`. Before
running the DAQ against real hardware:

1. Launch Matisse Commander on the laser-lab computer.
2. **Display Options → Position Display Mode = nm.**
3. Open the **CounterDrift** dialog (Wavemeter → CounterDrift) and set its
   **Unit = nm**.
4. Start `python LASERLABCOMPUTER/laser_server.py` on that machine.

The DAQ opens (and re-uses) both the CounterDrift and GoTo dialogs on connect
and sends wavelengths in **nm vacuum**. If either unit is left at cm⁻¹ the
laser will be commanded to wildly wrong frequencies.

Tuning knobs (all in `settings.json → control_settings.laser`):
`tolerance`, `goto_threshold`, three settle windows
(`dialog_open_delay`, `activation_delay`, `setpoint_settle`), and
`required_stable_samples`. Same values are editable live from the GUI's
*Laser Control* dialog.

## Project Structure

- `main.py`: Main entry point for the GUI.
- `settings.json`: System configuration and mode toggle.
- `src/control/`: Core logic (DAQ loop, Scanner, Laser Control).
- `src/devices/`: **Place your real hardware driver code here.**
- `src/simulation/`: Mock hardware for development and testing.
- `src/gui/`: PyQt5 interface components.
- `data/`: Default directory for scan results (`.csv`) and metadata (`.json`).

## Requirements
- Python 3.8+
- `numpy`, `matplotlib`, `PyQt5`
- (Optional) `pipython`, `pyepics` for real hardware integration.
