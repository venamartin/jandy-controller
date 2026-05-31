from jandy import JandyController
import time
import pprint
import threading

test = "airblower"

def display_status(api):
    waiting_for_input = [True]
    def print_status_loop():
        while waiting_for_input[0]:
            print("\n--- Current Status ---")
            pprint.pprint(api.get_status())
            time.sleep(5)
        
    status_thread = threading.Thread(target=print_status_loop, daemon=True)
    status_thread.start()

    input("\nPress Enter to turn everything off and conclude the test...\n")
    waiting_for_input[0] = False
    status_thread.join(timeout=1.0)


def main():
    print("Starting Jandy Autonomous API Test...")
    # Logging is enabled here for debugging, but can be set to False for production!
    api = JandyController(port='/dev/ttyUSB0', spoof_id=0x60, enable_logging=True, config_path="config.yaml")
    
    try:
        if test == "spa":
            
            # Test 1: Toggle SPA MODE ON
            print("\n--- Testing SPA MODE ON ---")
            api.spa_mode(True)
            time.sleep(1)
            
            # Test 2: Turn on Spa Heater and set to 98
            print("\n--- Testing SPA HEATER ON (98F) ---")
            api.spa_heat(True, 98)
            
            print("\nSpa and Heater are now ON.")
            api.print_screen()
            
            display_status(api)

            # Test 3: Toggle SPA HEATER OFF
            print("\n--- Testing SPA HEATER OFF ---")
            api.spa_heat(False)
            time.sleep(1)
            
            # Test 4: Toggle SPA MODE OFF
            print("\n--- Testing SPA MODE OFF ---")
            api.spa_mode(False)
            
            print("\nSpa and Heater are now OFF.")
            api.print_screen()
        
        if test == "airblower":
            print("\n--- Testing AIR BLOWER ON ---")
            api.air_blower(True)
            display_status(api)
            print("\n--- Testing AIR BLOWER OFF ---")
            api.air_blower(False)
            
        if test == "poollights":
            print("\n--- Testing POOL LIGHTS ON ---")
            api.pool_lights(True)
            display_status(api)
            print("\n--- Testing POOL LIGHTS OFF ---")
            api.pool_lights(False)
            display_status(api)

            
        if test == "alloff":
            print("\n--- Testing ALL OFF ---")
            api.air_blower(True)
            display_status(api)
            api.all_off()
            
    except KeyboardInterrupt:
        print("\nAborted by user.")
    finally:
        api.stop()
        print("API stopped.")

if __name__ == "__main__":
    main()
