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
| `"grating"` | `LASERLABCOMPUTER/grating_controller.py` (the `laser==True` PI-stage path) | The grating is a bare PI motion stage (`MOV`/`qPOS`), so **the DAQ runs the search itself**: it reads the EPICS wavemeter and walks the stage position toward the target with the original "go_to" coarse/fine stepping algorithm. |

To switch, set `control_settings.laser_type` in `settings.json` to match whichever
server is running on the laser-lab machine, and start the DAQ. Everything above the
laser (scanner, GUI, data) is identical in both modes. Neither laser script is
modified by the DAQ.

### Grating search parameters

The defaults in `control_settings.grating` are the values the grating was actually
scanned with. It is a small-step search, not a PID — each poll it nudges the stage
position by `step_fine` toward the target (falling back to `step_coarse` when a fine
step would not move it). This grating has a **negative** slope: when the wavemeter
reads *above* target the controller steps the position *up* to bring it down.

- **`step_fine`** — normal step toward the target (default `0.0001`).
- **`step_coarse`** — fallback step used when a fine step does not move the stage
  (default `0.001`).
- **`tolerance`** — max |wavemeter − target| (cm⁻¹) that counts as on-target
  (default `0.0001`).
- **`poll_interval`, `required_stable_samples`, `wavechannel`** — same meaning as
  the Matisse lock parameters (defaults `0.01` s, `4`, `1`).

There is no command clamp — the stage's own travel limits bound it, exactly as the
original control did. The loop walks the stage until the wavemeter has been within
`tolerance` for `required_stable_samples` consecutive reads, then exits and lets the
PI stage hold its position; if the laser later drifts out of tolerance the Scanner
re-aims by calling the controller again.

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
