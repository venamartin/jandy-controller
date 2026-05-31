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

This project uses [uv](https://github.com/astral-sh/uv), an extremely fast Python package manager.

1. **Clone the Repository**:
```bash
git clone https://github.com/YOUR_USERNAME/jandy-controller.git
cd jandy-controller
```

2. **Install `uv`**:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

3. **Configure your Hardware**:
Open `config.yaml` to specify your serial port connection and toggle the hardware installed at your pool. 

```yaml
system:
  serial_port: "/dev/ttyUSB0"

hardware:
  has_spa: true
  has_cleaner: true
  # ...
```

4. **Run the Server**:
The system includes a fully mobile-responsive Progressive Web App (PWA) dashboard. To run it continuously in the background, we recommend using `screen` or `tmux`.

**Using `screen`**:
```bash
# Start a new screen session
screen -S jandy

# Run the web server using uv
uv run uvicorn web:app --host 0.0.0.0 --port 8000

# To detach and leave it running, press: Ctrl+A, then D
# To reattach later, run: screen -r jandy
```

**Using `tmux`**:
```bash
# Start a new tmux session
tmux new -s jandy

# Run the web server using uv
uv run uvicorn web:app --host 0.0.0.0 --port 8000

# To detach and leave it running, press: Ctrl+B, then D
# To reattach later, run: tmux attach -t jandy
```

5. **Start on Boot (Optional)**:
To have the controller start automatically when your machine reboots, you can add a cron job. 

Run `crontab -e` and add **one** of the following lines to the bottom of the file. Be sure to replace `/path/to/jandy-controller` with the actual path to your repository.

**Using `screen`**:
```bash
@reboot cd /path/to/jandy-controller && screen -dmS jandy uv run uvicorn web:app --host 0.0.0.0 --port 8000
```

**Using `tmux`**:
```bash
@reboot cd /path/to/jandy-controller && tmux new-session -d -s jandy 'uv run uvicorn web:app --host 0.0.0.0 --port 8000'
```

*Note: `cron` environments do not load your normal terminal variables. If the script fails to run on boot, you may need to provide the absolute path to `uv` (e.g., `~/.local/bin/uv` or `~/.cargo/bin/uv`).*

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
