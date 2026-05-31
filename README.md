# Jandy RS-485 Autonomous API

A fully autonomous, thread-safe Python library for controlling Jandy / Pentair Aqualink pool and spa systems via the RS-485 bus. 

Instead of relying on web interfaces or complex system spoofing, this library works by **spoofing a Jandy PDA Handheld Remote (`0x60`)**. It establishes a background thread to maintain active communication with the Master Controller, parsing the screen buffer and cursor position in real-time to enable highly intelligent, state-aware automation.

## Features

- **Non-Blocking Status Polling:** Extracts real-time Water Temperature and Heater Setpoints directly from RS-485 `CMD_JXI_PING` broadcasts without ever needing to look at the screen.
- **Opportunistic Screen Scraping:** Silently reads equipment statuses (Pool Mode, Spa Mode, Air Temp) from the Home Screen buffer as it updates.
- **State-Aware Navigation:** Tracks the Master Controller's internal menu cursor. If an item is already ON, the API will not accidentally turn it OFF.
- **High-Speed Bidirectional Scrolling:** Understands that Jandy menus wrap around. If an item is at the bottom of the menu (like `ALL OFF`), the API will scroll `UP` to instantly wrap around instead of pressing `DOWN` 15 times.
- **Safety Interlocks:** Automatically aborts actions if the system is in a transitional "Cool Down" state (`***`). 

## Hardware Requirements

- Any Linux-based machine (Raspberry Pi, etc.)
- A USB to RS-485 Serial Adapter (e.g., FTDI chipset)
- A physical connection to the red, black, yellow, and green wires of the Aqualink RS-485 bus.

## Quickstart

### Installation
Ensure you have `pyserial` installed:
```bash
uv pip install pyserial
```

### Usage Example
```python
import time
import pprint
from jandy import JandyController

# Initialize the API (Defaults to /dev/ttyUSB0)
# This instantly spawns a background thread to maintain RS-485 communication
api = JandyController(port='/dev/ttyUSB0', spoof_id=0x60, enable_logging=False)

try:
    # Get a complete snapshot of the system's current state
    print("System Status:")
    pprint.pprint(api.get_status())

    # Turn on the Spa and set the heater to 98°F
    api.spa_mode(True)
    api.spa_heat(True, 98)

    # Turn on the Air Blower and Spa Lights
    api.air_blower(True)
    api.spa_lights(True)

    time.sleep(10)

    # Shut everything down instantly
    api.all_off()

finally:
    # Always cleanly stop the background thread
    api.stop()
```

## Available API Methods

All methods automatically navigate the Jandy PDA menu structure, find the correct item, verify its current state, toggle it if necessary, and cleanly return to the Home Menu.

- `api.pool_mode(state: bool)`
- `api.spa_mode(state: bool)`
- `api.pool_heat(state: bool, temp: int = None)`
- `api.spa_heat(state: bool, temp: int = None)`
- `api.pool_lights(state: bool)`
- `api.spa_lights(state: bool)`
- `api.air_blower(state: bool)`
- `api.solar(state: bool)`
- `api.all_off()`
- `api.get_status() -> dict`

## Project Structure

- `jandy/` - The core Python package containing the `JandyController` and RS-485 decoding logic.
- `test_api.py` - A comprehensive test harness to demonstrate and validate the API.
- `jandy-rs485-protocol.md` - Extensive, newly-updated documentation detailing the exact bytes, commands, and secrets of the Jandy RS-485 protocol.
