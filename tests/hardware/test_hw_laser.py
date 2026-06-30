"""Hardware smoke test for the MatisseDevice XML-RPC bridge.

Run manually with the laser_server.py instance reachable. This exercises the
public MCP wrappers without engaging CounterDrift — it just confirms the
dialogs open and the wavelength readback round-trips.
"""

import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.devices.laser import MatisseDevice


def test_matisse_smoke():
    print("=== Hardware: Matisse XML-RPC smoke test ===")
    m = MatisseDevice("Matisse")
    print("1. cd_open:", m.cd_open())
    print("2. goto_open:", m.goto_open())
    nm = m.cd_get_wavelength()
    print(f"3. cd_get_wavelength: {nm} nm")
    print("4. goto_status:", m.goto_status())
    print("=== Smoke test complete ===")


if __name__ == "__main__":
    test_matisse_smoke()
