"""Unit conversion between wavenumber (cm^-1) and vacuum wavelength (nm).

The DAQ uses cm^-1 internally; the Matisse Commander expects nm vacuum at its
MCP_WM.Counterdrift and MCP_WM.GoTo command interfaces. These two helpers are
the only place that conversion happens.
"""


def wn_to_nm_vacuum(wn_cm: float) -> float:
    return 1e7 / wn_cm


def nm_vacuum_to_wn(nm: float) -> float:
    return 1e7 / nm
