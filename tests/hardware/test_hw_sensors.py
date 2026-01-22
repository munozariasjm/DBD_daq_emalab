import sys
import os
import time
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.devices.sensors import Multimeter, SpectrometreReader, WavenumberReader

def test_sensors():
    print("=== Testing Real Hardware: Sensors ===")

    try:
        # --- Multimeter ---
        print("\n[Multimeter]")
        print("1. Initializing...")
        mm = Multimeter(port="COM1") # TODO: Update COM port

        print("2. Setup...")
        mm.reset()
        mm.setRemote()
        print(f"   Identity: {mm.identity()}")

        print("3. Reading Voltage...")
        v = mm.getVoltage()
        print(f"   Voltage: {v} V")
        print("   [PASS] Multimeter")

        # --- Spectrometer ---
        print("\n[Spectrometer]")
        print("1. Initializing Reader...")
        spec = SpectrometreReader()
        spec.start()

        print("2. Reading Spectrum Peak (3s)...")
        for _ in range(3):
            time.sleep(1)
            print(f"   Current Spectrum Peak: {spec.spectrum}")

        spec.stop()
        spec.join()
        print("   [PASS] Spectrometer")

        # --- Wavemeter ---
        print("\n[Wavemeter]")
        print("1. Initializing Reader...")
        wave = WavenumberReader()
        wave.start()

        print("2. Reading Wavenumbers (3s)...")
        for _ in range(3):
            time.sleep(1)
            wns = wave.get_wavenumbers()
            print(f"   Wavenumbers: {wns}")

        wave.stop()
        wave.join()
        print("   [PASS] Wavemeter")

        print("\n=== Sensors Test Complete ===")

    except Exception as e:
        print(f"\n[FAIL] An error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_sensors()
