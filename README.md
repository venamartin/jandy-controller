# Jandy RS-485 Controller & Web App

<p align="center">
  <img src="screenshot.jpg" alt="Jandy Web App Dashboard" width="350">
</p>

A Python library and web dashboard for controlling Jandy / Pentair Aqualink pool and spa systems over RS-485. 

The system works by spoofing a Jandy PDA Handheld Remote (`0x60`). It runs a background thread that communicates with the Master Controller, reading the screen buffer and cursor position to keep track of menu states and equipment status.

## Features

### Web App
- **Mobile UI:** Clean, responsive interface designed for phones.
- **PWA Support:** Can be added to your home screen to run in full-screen mode like a native app.
- **Hardware Sync:** The UI automatically updates to match the physical equipment state (e.g., if someone turns on the spa using the physical remote outside, the web app updates).
- **Configurable:** Uses `config.yaml` to hide or show buttons depending on your specific pool setup.

### Python API
- **Status Polling:** Parses `CMD_JXI_PING` broadcasts to get real-time water temps and heater setpoints without navigating menus.
- **Screen Scraping:** Reads equipment status (Pool Mode, Spa Mode, etc.) directly from the screen buffer in the background.
- **State Tracking:** Keeps track of the menu cursor and equipment state so it won't accidentally toggle something off if it's already on.
- **Menu Wrapping:** Scrolls UP to reach items at the bottom of the menu (like `ALL OFF`) instead of pressing DOWN 15 times.
- **Safety Interlocks:** Aborts commands if the Jandy system is in a transitional state (`***`), and prevents heaters from turning on if the main pump is off.

## Hardware Requirements

- Any Linux-based machine (Raspberry Pi, etc.)
- A USB to RS-485 Serial Adapter (e.g., FTDI chipset)
- A physical connection to the red, black, yellow, and green wires of the Aqualink RS-485 bus.

## Quickstart

### Option 1: Automated Installation (Recommended)

You can use the included installation script to automatically install dependencies, set up your configuration, and create the background systemd service.

1. **Clone the Repository**:
```bash
git clone https://github.com/venamartin/jandy-controller.git
cd jandy-controller
```

2. **Run the Installer**:
```bash
bash install.sh
```
The script will automatically install `uv`, sync dependencies, prompt you to configure your hardware, and create the `jandy.service` for systemd.

---

### Option 2: Manual Installation

This project uses [uv](https://github.com/astral-sh/uv), an extremely fast Python package manager.

1. **Clone the Repository**:
```bash
git clone https://github.com/venamartin/jandy-controller.git
cd jandy-controller
```

2. **Install `uv`**:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

3. **Install Dependencies**:
```bash
uv sync
```

4. **Configure your Hardware**:
Copy the example configuration file and edit it using nano:
```bash
cp config.example.yaml config.yaml
nano config.yaml
```
Inside the file, specify your serial port connection and toggle the hardware installed at your pool. 

```yaml
system:
  serial_port: "/dev/ttyUSB0"
  enable_logging: false

hardware:
  has_spa: true
  has_cleaner: true
  # ...
```

> [!TIP]
> **Finding your Serial Port on a Raspberry Pi / Linux**
> - **USB Adapters:** If you aren't sure what your USB adapter is called, plug it into your machine and run `ls /dev/ttyUSB* /dev/ttyACM*`. It will almost always show up as `/dev/ttyUSB0`. You can also run `dmesg | tail -n 20` immediately after plugging it in to see the exact device name.
> - **GPIO (Built-in) Serial:** If you are using an RS-485 HAT or wiring directly to the Raspberry Pi's built-in GPIO pins (Pins 8 & 10), your serial port will typically be `/dev/serial0` (which automatically maps to `ttyS0` or `ttyAMA0`). You may need to enable the serial port using `sudo raspi-config` first!

5. **Run the Server (Systemd)**:
The system includes a fully mobile-responsive Progressive Web App (PWA) dashboard. The most robust way to run the controller in the background on Linux/Raspberry Pi is using a `systemd` service.

1. **Create the service file:**
```bash
sudo nano /etc/systemd/system/jandy.service
```

2. **Paste the following configuration** (be sure to replace `/path/to/jandy-controller` and `yourusername` with your actual path and username):
```ini
[Unit]
Description=Jandy RS-485 Controller
After=network.target

[Service]
User=yourusername
WorkingDirectory=/path/to/jandy-controller
# Note: Provide the absolute path to uv if it's not in the system PATH (e.g., /home/yourusername/.local/bin/uv)
ExecStart=/home/yourusername/.local/bin/uv run uvicorn web:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

3. **Enable and start the service:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable jandy
sudo systemctl start jandy
```

4. **View the Logs:**
You can see the systemd log files (journal) in real-time by running:
```bash
sudo journalctl -fu jandy
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
