capi-daq-v2/
│
├── config/                     # Configuration & Environment
│   ├── settings.json           # User preferences (paths, TOF windows)
│   └── env_config.py           # Global flags (OFFLINE_MODE=True/False)
│
├── src/                        # Application Source Code
│   ├── core/                   # The "Brain" - Interfaces & Factories
│   │   ├── __init__.py
│   │   ├── interfaces.py       # Abstract Base Classes (The Contract)
│   │   └── factory.py          # The Switch (Returns Real or Sim)
│   │
│   ├── drivers/                # REAL Hardware Implementations
│   │   ├── __init__.py
│   │   ├── epics/              # Spectrometer, Wavemeter
│   │   ├── serial/             # HP Multimeter
│   │   └── cronologic/         # Time Tagger wrapper
│   │
│   ├── simulation/             # OFFLINE/MOCK Implementations
│   │   ├── __init__.py
│   │   ├── sim_tagger.py       # 50Hz Poisson Generator
│   │   └── sim_sensors.py      # Mock Multimeter/Spectrometer
│   │
│   ├── services/               # High-level Business Logic
│   │   ├── scan_manager.py     # Logic for stepping and recording
│   │   └── data_writer.py      # CSV/Parquet saving logic
│   │
│   └── utils/                  # Helpers
│       ├── physics.py          # TOF to time, units conversions
│       └── system.py           # Process handling
│
├── gui/                        # Frontend (PyQt / Streamlit)
│   ├── main_window.py          # Main GUI Entry
│   ├── assets/                 # Images, logos
│   └── dashboards/             # Streamlit plotting scripts
│
├── tests/                      # Unit Tests
│   ├── test_tagger.py          # Verify 50Hz logic
│   └── test_factory.py         # Ensure factory returns correct class
│
├── main.py                     # Entry Point
└── requirements.txt            # Python dependencies