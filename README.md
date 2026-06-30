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

## Controlling the grating laser instead of the Matisse

The laser-lab machine serves **one** laser on port 8000 at a time — never both:

| `control_settings.laser_type` | Server it talks to | How it holds a wavenumber |
|---|---|---|
| `"matisse"` (default) | `LASERLABCOMPUTER/matisse_cd_controller.py` | Matisse **firmware** CounterDrift lock; the DAQ only sets a setpoint and watches the wavemeter. |
| `"grating"` | `LASERLABCOMPUTER/grating_controller.py` | The grating is a bare PI motion stage (`MOV`/`qPOS`), so **the DAQ runs the lock itself**: it reads the EPICS wavemeter and nudges the stage until the measured wavenumber is on target. |

To switch, set `control_settings.laser_type` in `settings.json` to match whichever
server is running on the laser-lab machine, and start the DAQ. Everything above the
laser (scanner, GUI, data) is identical in both modes. Neither laser script is
modified by the DAQ.

### Grating calibration — the one number you must set

The grating servo needs to know how the stage position maps to wavenumber. That
lives in `control_settings.grating`:

- **`wn_per_unit`** — cm⁻¹ of wavenumber change per one stage position unit,
  **including sign**. This is rig-specific; calibrate it on the bench (move the
  stage a known amount, read the wavemeter delta). A wrong *magnitude* only slows
  convergence; a wrong *sign* is caught automatically (see guards below).
- **`kp` / `ki`** — servo gains. `kp` alone (default `0.5`) gives a damped
  proportional lock; add `ki` to remove residual steady-state error.
- **`tolerance`, `poll_interval`, `required_stable_samples`, `wavechannel`,
  `wm_averaging_samples`** — same meaning as the Matisse lock parameters.
- **`step_limit`** — largest stage move commanded per poll (caps how hard a bad
  reading can drive the stage).
- **`pos_min` / `pos_max`** — hard travel clamp on the commanded position. **Set
  these to the real mechanical limits of your stage.**

Three guards disengage and latch an aborted state (like the Matisse runaway guard)
rather than drive the stage into a hard stop: the per-poll `step_limit`, the
`pos_min`/`pos_max` travel clamp, and a divergence/out-of-range abort that fires
when the error grows instead of shrinking (the classic wrong-`wn_per_unit`-sign
failure) or the commanded position is pinned at a travel limit while still off
target. After an abort, fix the calibration and restart the DAQ.

## Tuning

All lock parameters live in the *Laser Control* dialog inside the GUI;
each row has a `?` button with a one-line explanation. Values persist to
`settings.json → control_settings.laser`. Defaults are conservative; first
bench session usually only needs to adjust `activation_delay` and
`setpoint_settle` to match the laser's actual settling behaviour.

## Layout

- `main.py` — GUI entry point.
- `settings.json` — scan params, simulation toggle, lock parameters.
- `src/control/` — DAQ loop, scanner, laser controllers
  (`laser_controller.py` = Matisse CounterDrift, `grating_controller.py` =
  grating software servo).
- `src/devices/` — real-hardware drivers (`MatisseDevice` / `GratingDevice`
  XML-RPC clients, EPICS).
- `src/simulation/` — mocks used when `simulation_mode: true`.
- `src/gui/` — PyQt5 widgets.
- `LASERLABCOMPUTER/matisse_cd_controller.py` — XML-RPC bridge for the Matisse
  (CounterDrift via Matisse Commander).
- `LASERLABCOMPUTER/grating_controller.py` — XML-RPC bridge for the grating
  (PI motion stage). One of these runs on the laser-lab machine at a time;
  `control_settings.laser_type` selects which the DAQ drives.
- `data/` — scan CSVs and per-scan metadata.
