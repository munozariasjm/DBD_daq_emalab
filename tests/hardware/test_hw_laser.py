import sys
import os
import time

from pipython import GCSDevice, pitools, datarectools

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from src.devices.laser import PIGCSDevice, EpicsClient

def test_laser_control():
    print("=== Testing Real Hardware: Laser Control ===")

    try:
        # --- PI Motor Controller ---
        print("\n[PI Controller]")
        print("1. Initializing PIGCSDevice...")
        pi = PIGCSDevice(controller_name="Real_PI") # TODO: Update controller name
        print("   [PASS] Initialized")

        print("2. Connecting (Simulated COM Port)...")
        pi.ConnectRS232(comport=5, baudrate=19200) # TODO: Update COM port
        print("   [PASS] Connection method call")

        # print("3. Checking Identity...")
        # idn = pi.qIDN()
        # print(f"   Identity: {idn}")

        print("4. Testing Movement Logic...")
        pi.SVO(axis=1, state=True)
        current_pos = pi.qPOS(axis=1)
        print(f"   Current Position: {current_pos}")

        target = 12625.187
        print(f"   Moving to {target}...")
        pi.MOV(axis=1, target=target)

        # Simulate wait
        # time.sleep(0.5)
        pitools.waitontarget(pi,axes=1)
        new_pos = pi.qPOS(axis=1)
        print(f"   Post-move Position (Simulated/Placeholder): {new_pos}")


        # --- Epics Client ---
        print("\n[Epics Client]")
        print("1. Initializing EpicsClient...")
        epics = EpicsClient(pi_device=pi)

        # print("2. Reading PV...")
        # Note: Replace with actual PV name

        # print("\n[Cleanup]")
        # pi.CloseConnection()
        # print("=== Laser Control Test Complete ===")

    except Exception as e:
        print(f"\n[FAIL] An error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_laser_control()
