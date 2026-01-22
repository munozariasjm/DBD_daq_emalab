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
