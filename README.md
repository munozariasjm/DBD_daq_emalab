# Discrete Beamline DAQ (DBD)


## Quick start

```bash
pip install -r requirements.txt
python main.py
```

`settings.json → simulation_mode: true` runs without hardware. For real
scans, configure Matisse Commander as described below first.

### 1. Set both unit controls to nm — non-negotiable

The DAQ sends every setpoint in **nm vacuum**.
The DAQ runs a pre-flight unit check on first scan and refuses to engage
when it detects the mismatch, but that check is a safety net.

In Matisse Commander:

- **Display Options → Position Display Mode = nm**
- **CounterDrift dialog → Unit = nm**

### 2. Required plugins

- **WM Selector Plugin** — supplies `MCP_WM_GET_WAVELENGTH`, used by the
  pre-flight unit check.
- **Wavemeter Plugin** — required for the CounterDrift and GotoPosition
  dialogs to accept MCP commands.

### 3. Start the laser server

On the laser-lab machine, with Commander running and the Matisse USB
device available:

```bash
(or make sure its running already).
python LASERLABCOMPUTER/laser_server.py
```

This is the XML-RPC bridge the DAQ connects to. On DAQ startup the
terminal prints one of:

- `[Matisse] Server ping OK at http://…:8000` — server up, Matisse handle
  alive. Safe to scan.
- `[Matisse] Server reachable at … (older API: no ping)` — server up but
  running an older build; hardware-side health will only surface on the
  first real command.
- `=== LASER SERVER ERROR ===` block with a network exception — server
  down or unreachable. **Fix this before scanning.**

### 4. Expected terminal output during a scan

A healthy first scan logs roughly this on the DAQ terminal:

```
[Matisse] Server ping OK at http://10.54.6.1:8000
[Laser] control loop starting (target=12625.000000)
[Laser] Pre-flight unit check OK: Matisse=791.9609 nm, EPICS=12625.000000 cm^-1 (=791.9604 nm)
[Laser] activate CounterDrift at 791.960400 nm (12625.000000 cm^-1)
```

If the pre-flight banner shows `MATISSE UNIT MISMATCH` or
`MATISSE/WAVEMETER DISAGREE`, stop and fix the Commander config or
wavemeter channel before retrying — the controller will not have engaged.

## Tuning

All lock parameters live in the *Laser Control* dialog inside the GUI;
each row has a `?` button with a one-line explanation. Values persist to
`settings.json → control_settings.laser`. Defaults are conservative; first
bench session usually only needs to adjust `activation_delay` and
`setpoint_settle` to match the laser's actual settling behaviour.

## Layout

- `main.py` — GUI entry point.
- `settings.json` — scan params, simulation toggle, lock parameters.
- `src/control/` — DAQ loop, scanner, laser controller.
- `src/devices/` — real-hardware drivers (Matisse XML-RPC client, EPICS).
- `src/simulation/` — mocks used when `simulation_mode: true`.
- `src/gui/` — PyQt5 widgets.
- `LASERLABCOMPUTER/laser_server.py` — XML-RPC bridge running on the
  laser-lab machine.
- `data/` — scan CSVs and per-scan metadata.
