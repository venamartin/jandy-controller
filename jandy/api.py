import serial
import time
import threading
import queue
from datetime import datetime
from typing import Dict, Optional, Callable

import re
import yaml
import os
from .protocol import JandyPacket, DLE, STX, BUTTON_CODES, calculate_checksum, CMD_JXI_PING

class JandyController:
    """
    A robust, thread-safe controller that spoofs a PDA device on the Jandy RS-485 bus.
    It tracks the Master Controller's screen state to perform intelligent state-aware navigation.
    """
    def __init__(self, port: str = '/dev/ttyUSB0', spoof_id: int = 0x60, enable_logging: bool = True, log_file_path: str = "api-test.log", config_path: str = "config.yaml", monitor_mode: bool = False):
        self.port = port
        self.spoof_id = spoof_id
        self.enable_logging = enable_logging
        self.monitor_mode = monitor_mode
        self.dynamic_monitor_timeout = 0.0
        self.pending_ack = False
        self.pending_ack_time = 0.0
        self.pending_button_val = 0x00
        
        self.log_file = None
        if self.enable_logging:
            self.log_file = open(log_file_path, "w")
            
        # Hardware Configuration
        self.config = {
            "has_spa": True,
            "has_pool_heater": True,
            "has_spa_heater": True,
            "has_pool_lights": True,
            "has_spa_lights": True,
            "has_blower": True,
            "has_solar": True
        }
        
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                data = yaml.safe_load(f)
                if data and "hardware" in data:
                    self.config.update(data["hardware"])
            print(f"[API] Loaded configuration from {config_path}")
        else:
            print(f"[API] Config file {config_path} not found. Assuming all hardware exists.")
            
        # Serial connection
        self.ser = serial.Serial(port, 9600, timeout=0.1)
        
        # Threading and State
        self._running = True
        self._button_queue = queue.Queue()
        self.lock = threading.Lock()
        
        # Screen State
        self.screen_lines: Dict[int, str] = {}
        self.cursor_line: int = -1
        
        # Global Status State
        self.status: Dict[str, any] = {
            "air_temp": None,
            "water_temp": None,
            "pool_heater_setpoint": None,
            "spa_heater_setpoint": None,
            "pool_mode_on": False,
            "spa_mode_on": False,
            "pool_heater_on": False,
            "pool_heater_ena": False,
            "spa_heater_on": False,
            "spa_heater_ena": False,
            "solar_on": None, # Unimplemented
            "blower_on": None, # Unimplemented
            "pool_lights_on": None, # Unimplemented
            "spa_lights_on": None, # Unimplemented
            "cleaner_on": None
        }
        
        self._button_event = threading.Event()
        
        # Start background thread
        self._thread = threading.Thread(target=self._run_bus, daemon=True)
        self._thread.start()
        print(f"[API] Initialized JandyController on {port} spoofing 0x{spoof_id:02X}")
        
        # Wait for Master Controller to boot the spoofed PDA
        print("[API] Waiting for Master Controller boot sequence...")
        if self.wait_for_text("EQUIPMENT", timeout=15):
            print("[API] PDA Menu Ready!")
        else:
            print("[API] Warning: Menu did not appear within 15 seconds.")

    def stop(self):
        self._running = False
        self._thread.join()
        self.ser.close()
        if self.log_file:
            self.log_file.close()

    def _log(self, prefix: str, msg: str):
        if self.log_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            self.log_file.write(f"{timestamp} - [{prefix}] {msg}\n")
            self.log_file.flush()

    def _run_bus(self):
        """Background thread that continuously parses packets and ACKs the Master."""
        buffer = bytearray()
        
        while self._running:
            if self.ser.in_waiting:
                buffer.extend(self.ser.read(self.ser.in_waiting))
            
            while len(buffer) >= 4:
                # Find DLE STX
                try:
                    start_idx = buffer.index(bytes([DLE, STX]))
                except ValueError:
                    buffer.clear()
                    break
                
                if start_idx > 0:
                    del buffer[:start_idx]
                
                parsed = JandyPacket.parse(buffer)
                if parsed is None:
                    break # Not enough data
                    
                packet, consumed = parsed
                
                # We successfully parsed a packet, consume it
                del buffer[:consumed]
                
                hex_bytes = " ".join(f"{b:02X}" for b in packet.raw_bytes)
                self._log("RECV", f"{hex_bytes}\n  {packet.summary(True)}")
                
                self._handle_packet(packet)
            
            # Check for delayed ACK (35ms delay)
            if self.pending_ack and (time.time() - self.pending_ack_time >= 0.035):
                self.pending_ack = False
                
                # Construct ACK
                ack_bytes = bytearray([0x10, 0x02, 0x00, 0x01, 0x40, self.pending_button_val, 0x00, 0x10, 0x03])
                chk = calculate_checksum(ack_bytes)
                ack_bytes[-3] = chk
                self.ser.write(ack_bytes)
                
                hex_bytes = " ".join(f"{b:02X}" for b in ack_bytes)
                self._log("SEND", hex_bytes)
            
            time.sleep(0.005)

    def _handle_packet(self, packet: JandyPacket):
        # Track the destination of the last command sent by the Master
        # Any packet not sent TO 0x00 (Master) is sent BY the Master
        if packet.dest != 0x00:
            self.last_master_dest = packet.dest

        # Update JXi Ping Status
        if packet.cmd == CMD_JXI_PING and len(packet.payload) >= 4:
            with self.lock:
                # Water Temp (255 means N/A)
                wt = packet.payload[3]
                self.status["water_temp"] = wt if wt != 255 else None
                
                # Setpoints
                self.status["pool_heater_setpoint"] = packet.payload[1]
                self.status["spa_heater_setpoint"] = packet.payload[2]

        # Update Screen State
        if packet.cmd == 0x04 and packet.dest == self.spoof_id:
            if len(packet.payload) > 1:
                line_idx = packet.payload[0]
                text = ''.join(chr(b) if 32 <= b < 127 else ' ' for b in packet.payload[1:]).strip()
                with self.lock:
                    self.screen_lines[line_idx] = text
                    
                    # Opportunistically scrape Home Menu items if they appear
                    if line_idx == 130:
                        # Temperatures usually appear on line 130, e.g., "62` 73`" or "70`" or "62` --"
                        match = re.search(r"^\s*(\d+)`", text)
                        if match:
                            self.status["air_temp"] = int(match.group(1))
                    
                    if "POOL MODE" in text:
                        self.status["pool_mode_on"] = " ON" in text
                    elif "SPA MODE" in text:
                        self.status["spa_mode_on"] = " ON" in text
                    elif "POOL HEATER" in text:
                        self.status["pool_heater_on"] = " ON" in text or " ENA" in text
                        self.status["pool_heater_ena"] = " ENA" in text
                    elif "SPA HEATER" in text:
                        self.status["spa_heater_on"] = " ON" in text or " ENA" in text
                        self.status["spa_heater_ena"] = " ENA" in text
                    elif "AIR BLOWER" in text:
                        self.status["blower_on"] = " OFF" not in text and "***" not in text
                    elif "POOL LIGHT" in text:
                        self.status["pool_lights_on"] = " OFF" not in text and "***" not in text
                    elif "SPA LIGHT" in text:
                        self.status["spa_lights_on"] = " OFF" not in text and "***" not in text
                    elif "SOLAR HEAT" in text:
                        self.status["solar_on"] = " OFF" not in text and "***" not in text
                    elif "DECK LIGHT" in text:
                        self.status["deck_lights_on"] = " OFF" not in text and "***" not in text
                    elif "CLEANER" in text:
                        self.status["cleaner_on"] = " OFF" not in text and "***" not in text
        
        # Update Cursor Position
        elif packet.cmd == 0x08 and packet.dest == self.spoof_id:
            if len(packet.payload) > 0:
                with self.lock:
                    self.cursor_line = packet.payload[0]
        
        # Monitor Mode Check
        if packet.dest == 0x00 and packet.cmd == 0x01:
            # ONLY trigger monitor mode if this ACK was in response to a packet directed at OUR spoofed ID!
            if getattr(self, "last_master_dest", None) == self.spoof_id:
                # Is it the physical remote or our own echo?
                # If we are pending an ACK, we haven't sent ours yet, so it must be the physical remote.
                # If we are in monitor mode, we don't send ACKs, so it must be the physical remote.
                if getattr(self, "pending_ack", False) or self.monitor_mode:
                    if getattr(self, "pending_ack", False):
                        self.pending_ack = False
                        print("[API] Physical remote active! Yielding bus for 30s.")
                    
                    self.dynamic_monitor_timeout = time.time() + 30.0

        # Reply to Master (We must ACK ANY packet sent to our spoof ID to stay alive)
        if not self.monitor_mode and packet.dest == self.spoof_id and packet.cmd != 0x01:
            if time.time() < self.dynamic_monitor_timeout:
                return # We are yielding to the physical remote
                
            button_val = BUTTON_CODES["NONE"]
            try:
                # Non-blocking pop from the queue
                cmd = self._button_queue.get_nowait()
                button_val = BUTTON_CODES[cmd]
                print(f"[API] Queued Button: {cmd}")
                self._button_event.set() # Signal that the button was sent
            except queue.Empty:
                pass
            
            # Defer the ACK by 35ms
            self.pending_ack = True
            self.pending_ack_time = time.time()
            self.pending_button_val = button_val

    # =======================================================
    # Navigation Primitives
    # =======================================================

    def press(self, button: str, sleep_time: float = 0.5):
        """Queue a button press and wait for it to be sent to the Master."""
        if button not in BUTTON_CODES:
            raise ValueError(f"Invalid button: {button}")
        self._button_event.clear()
        self._button_queue.put(button)
        # Wait until the background thread actually ACKs the Master with this button
        self._button_event.wait(timeout=5.0) 
        # Wait a little longer for the Master to process the button and update the screen
        time.sleep(sleep_time)

    def wait_for_text(self, text: str, timeout: int = 10) -> bool:
        """Blocks until the specified text appears anywhere on the screen."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.lock:
                for line in self.screen_lines.values():
                    if text in line:
                        return True
            time.sleep(0.1)
        return False

    def wait_for_cursor(self, timeout: int = 10) -> int:
        """Blocks until the cursor position is known, returning the line number."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.lock:
                if self.cursor_line != -1:
                    return self.cursor_line
            time.sleep(0.1)
        return -1
        
    def wait_for_cursor_change(self, old_cursor: int, timeout: float = 5.0) -> int:
        """Blocks until the cursor moves away from old_cursor."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.lock:
                if self.cursor_line != -1 and self.cursor_line != old_cursor:
                    return self.cursor_line
            time.sleep(0.1)
        return self.cursor_line

    def get_line_text(self, line_idx: int) -> str:
        """Returns the text currently on the specified line."""
        with self.lock:
            return self.screen_lines.get(line_idx, "")

    def get_cursor_text(self) -> str:
        """Returns the text currently highlighted by the cursor."""
        with self.lock:
            if self.cursor_line != -1:
                return self.screen_lines.get(self.cursor_line, "")
        return ""

    def print_screen(self):
        """Prints the current known state of the PDA screen."""
        with self.lock:
            print("--- PDA Screen ---")
            for idx in sorted(self.screen_lines.keys()):
                cursor_marker = "->" if idx == self.cursor_line else "  "
                print(f"{cursor_marker} [{idx:02d}] {self.screen_lines[idx]}")
            print("------------------")

    def go_home(self):
        """Spams BACK until we are reasonably sure we are on the Home Menu."""
        print("[API] Navigating to Home Menu...")
        for _ in range(3):
            self.press("BACK", 0.5)
        self.wait_for_text("EQUIPMENT", timeout=5)

    def navigate_to(self, text: str, max_scrolls: int = 15, direction: str = "DOWN") -> bool:
        """
        Scrolls in the specified direction until the cursor highlights the specified text.
        Returns True if successful, False if the text was never found.
        """
        print(f"[API] Navigating to '{text}' (direction: {direction})...")
        scrolls = 0
        while scrolls < max_scrolls:
            cursor_idx = self.wait_for_cursor()
            if cursor_idx == -1:
                print("[API] Warning: Cursor position unknown.")
                time.sleep(0.5)
                continue
            
            cursor_text = self.get_cursor_text()
            if text in cursor_text:
                print(f"[API] Found '{text}' at line {cursor_idx}")
                return True
            
            # Scroll
            self.press(direction, 0.0) 
            
            # Wait for EITHER the cursor to move OR the text under the cursor to change
            start_time = time.time()
            while time.time() - start_time < 5.0:
                with self.lock:
                    new_cursor = self.cursor_line
                    new_text = self.screen_lines.get(new_cursor, "")
                
                if new_cursor != cursor_idx or new_text != cursor_text:
                    break
                time.sleep(0.1)
                
            time.sleep(0.2) # Allow text to settle
            scrolls += 1
            
        print(f"[API] Error: Could not find '{text}' after {max_scrolls} scrolls.")
        return False

    # =======================================================
    # High-Level Commands
    # =======================================================

    def _toggle_equipment(self, equip_name: str, desired_state: bool):
        """Helper to toggle standard equipment directly on the Home menu."""
        self.go_home()
        
        if not self.navigate_to(equip_name):
            return False
            
        # Check current state. The text looks like "SPA MODE    OFF" or "SPA MODE    ***"
        current_text = self.get_cursor_text()
        
        if "***" in current_text:
            print(f"[API] SAFETY LOCKOUT: {equip_name.strip()} is in a transitional state (***). Aborting.")
            return False
            
        is_on = " ON" in current_text
        
        if is_on == desired_state:
            print(f"[API] {equip_name.strip()} is already {'ON' if is_on else 'OFF'}.")
            return True
            
        print(f"[API] Toggling {equip_name.strip()} to {'ON' if desired_state else 'OFF'}...")
        self.press("SELECT", 1.0)
        return True

    def _toggle_aux_equipment(self, equip_name: str, desired_state: bool):
        """Helper to toggle equipment located in the EQUIPMENT ON/OFF menu."""
        self.go_home()
        
        # EQUIPMENT ON/OFF is at the bottom of the home menu, so scrolling UP wraps around faster!
        if not self.navigate_to("EQUIPMENT ON/OFF", direction="UP"):
            return False
            
        self.press("SELECT", 1.5)
        
        if not self.navigate_to(equip_name):
            self.press("BACK")
            return False
            
        current_text = self.get_cursor_text()
        
        if "***" in current_text:
            print(f"[API] SAFETY LOCKOUT: {equip_name.strip()} is in a transitional state (***). Aborting.")
            self.press("BACK")
            return False
            
        is_on = " ON" in current_text
        
        # Sync current known state just in case it was missed by the scraper
        if equip_name == "AIR BLOWER": self.status["blower_on"] = is_on
        elif equip_name == "POOL LIGHT": self.status["pool_lights_on"] = is_on
        elif equip_name == "SPA LIGHT": self.status["spa_lights_on"] = is_on
        elif equip_name == "SOLAR HEAT": self.status["solar_on"] = is_on
        elif equip_name == "DECK LIGHT": self.status["deck_lights_on"] = is_on
        elif equip_name == "CLEANER": self.status["cleaner_on"] = is_on
        
        if is_on == desired_state:
            print(f"[API] {equip_name.strip()} is already {'ON' if is_on else 'OFF'}.")
            self.press("BACK")
            return True
            
        print(f"[API] Toggling {equip_name.strip()} to {'ON' if desired_state else 'OFF'}...")
        self.press("SELECT", 1.0)
        
        # Force update the internal state because we are about to press BACK immediately 
        # and the scraper will miss the updated text!
        if equip_name == "AIR BLOWER": self.status["blower_on"] = desired_state
        elif equip_name == "POOL LIGHT": self.status["pool_lights_on"] = desired_state
        elif equip_name == "SPA LIGHT": self.status["spa_lights_on"] = desired_state
        elif equip_name == "SOLAR HEAT": self.status["solar_on"] = desired_state
        elif equip_name == "DECK LIGHT": self.status["deck_lights_on"] = desired_state
        elif equip_name == "CLEANER": self.status["cleaner_on"] = desired_state
        
        self.press("BACK")
        return True

    def all_off(self):
        """Executes the ALL OFF command from the EQUIPMENT ON/OFF menu."""
        self.go_home()
        if not self.navigate_to("EQUIPMENT ON/OFF", direction="UP"):
            return False
        self.press("SELECT", 1.5)
        # ALL OFF is at the bottom of the EQUIPMENT ON/OFF menu, so scrolling UP wraps around faster!
        if not self.navigate_to("ALL OFF", direction="UP"):
            self.press("BACK")
            return False
        print("[API] Executing ALL OFF...")
        self.press("SELECT", 1.0)
        
        # Force update the internal state manually since ALL OFF shuts down everything
        self.status["pool_mode_on"] = False
        self.status["spa_mode_on"] = False
        self.status["pool_heater_on"] = False
        self.status["pool_heater_ena"] = False
        self.status["spa_heater_on"] = False
        self.status["spa_heater_ena"] = False
        self.status["blower_on"] = False
        self.status["pool_lights_on"] = False
        self.status["spa_lights_on"] = False
        self.status["solar_on"] = False
        self.status["cleaner_on"] = False
        
        self.press("BACK")
        return True

    def air_blower(self, state: bool):
        """Turns the Air Blower on or off."""
        if not self.config.get("has_blower", True):
            print("[API] CONFIG LOCKOUT: Air Blower is disabled in config. Aborting.")
            return False
            
        if state:
            # SAFETY CHECK: Air blower requires Spa to be ON
            self.go_home()
            if not self.navigate_to("SPA MODE"):
                return False
            if " ON" not in self.get_cursor_text():
                print("[API] SAFETY LOCKOUT: Cannot turn on Air Blower while Spa Mode is OFF.")
                return False
                
        return self._toggle_aux_equipment("AIR BLOWER", state)

    def pool_lights(self, state: bool):
        """Turns the Pool Lights on or off."""
        if not self.config.get("has_pool_lights", True):
            print("[API] CONFIG LOCKOUT: Pool Lights are disabled in config. Aborting.")
            return False
        return self._toggle_aux_equipment("POOL LIGHT", state)

    def spa_lights(self, state: bool):
        """Turns the Spa Lights on or off."""
        if not self.config.get("has_spa_lights", True):
            print("[API] CONFIG LOCKOUT: Spa Lights are disabled in config. Aborting.")
            return False
        return self._toggle_aux_equipment("SPA LIGHT", state)

    def deck_lights(self, state: bool):
        """Turns the Deck Lights on or off."""
        if not self.config.get("has_deck_lights", True):
            print("[API] CONFIG LOCKOUT: Deck Lights are disabled in config. Aborting.")
            return False
        return self._toggle_aux_equipment("DECK LIGHT", state)

    def solar(self, state: bool):
        """Turns the Solar Heater on or off."""
        if not self.config.get("has_solar", True):
            print("[API] CONFIG LOCKOUT: Solar Heater is disabled in config. Aborting.")
            return False
            
        if state:
            # SAFETY CHECK: Solar Heat requires Spa Mode to be OFF
            self.go_home()
            if not self.navigate_to("SPA MODE"):
                return False
            if " ON" in self.get_cursor_text():
                print("[API] SAFETY LOCKOUT: Cannot turn on Solar Heat while Spa Mode is ON.")
                return False
                
        return self._toggle_aux_equipment("SOLAR HEAT", state)

    def cleaner(self, state: bool):
        """Turns the Cleaner on or off."""
        if not self.config.get("has_cleaner", True):
            print("[API] CONFIG LOCKOUT: Cleaner is disabled in config. Aborting.")
            return False
            
        if state:
            # SAFETY CHECK: Cleaner requires Pool to be ON
            self.go_home()
            if not self.navigate_to("POOL MODE"):
                return False
            if " ON" not in self.get_cursor_text():
                print("[API] SAFETY LOCKOUT: Cannot turn on Cleaner while Pool Mode is OFF.")
                return False
                
        return self._toggle_aux_equipment("CLEANER", state)

    def pool_mode(self, state: bool):
        """Turns the Pool on or off."""
        if state:
            # SAFETY CHECK: Turn off Spa Heater before turning on Pool Mode
            print("[API] SAFETY CHECK: Ensuring Spa Heater is OFF before turning Pool ON...")
            self.spa_heat(False)
            
            if self.config.get("has_spa", True):
                # SAFETY CHECK: Turn off Spa Mode before turning on Pool Mode
                self.go_home()
                if self.navigate_to("SPA MODE"):
                    if " ON" in self.get_cursor_text():
                        print("[API] SAFETY CHECK: Spa Mode is ON. Turning it OFF before turning Pool ON...")
                        self._toggle_equipment("SPA MODE", False)
                        print("[API] Waiting 35 seconds for Jandy firmware to process the valve transition...")
                        time.sleep(35.0)
                    
        return self._toggle_equipment("POOL MODE", state)

    def spa_mode(self, state: bool):
        """Turns the Spa on or off."""
        if not self.config.get("has_spa", True):
            print("[API] CONFIG LOCKOUT: Spa Mode is disabled in config. Aborting.")
            return False
            
        if state:
            # SAFETY CHECK: Turn off Pool Heater, Solar Heat, and Cleaner before turning on Spa Mode
            print("[API] SAFETY CHECK: Ensuring Pool Equipment is OFF before turning Spa ON...")
            self.cleaner(False)
            self.solar(False)
            self.pool_heat(False)
            
            # SAFETY CHECK: Turn off Pool Mode before turning on Spa Mode
            self.go_home()
            if self.navigate_to("POOL MODE"):
                if " ON" in self.get_cursor_text():
                    print("[API] SAFETY CHECK: Pool Mode is ON. Turning it OFF before turning Spa ON...")
                    self._toggle_equipment("POOL MODE", False)
                    print("[API] Waiting 35 seconds for Jandy firmware to process the valve transition...")
                    time.sleep(35.0)
            
        return self._toggle_equipment("SPA MODE", state)

    def _toggle_heater(self, heater_name: str, pump_name: str, state: bool, temp: int = None):
        """Helper to toggle a heater with safety checks for the associated pump."""
        self.go_home()
        
        # SAFETY CHECK: Never turn on a heater if its main pump is OFF
        if state:
            if not self.navigate_to(pump_name):
                return False
            pump_text = self.get_cursor_text()
            if "***" in pump_text:
                print(f"[API] SAFETY LOCKOUT: Cannot turn on {heater_name.strip()} because {pump_name.strip()} is transitional (***).")
                return False
            if " ON" not in pump_text:
                print(f"[API] SAFETY LOCKOUT: Cannot turn on {heater_name.strip()} while {pump_name.strip()} is OFF.")
                return False
                
        if not self.navigate_to(heater_name):
            return False
            
        current_text = self.get_cursor_text()
        
        if "***" in current_text:
            print(f"[API] SAFETY LOCKOUT: {heater_name.strip()} is in a transitional state (***). Aborting.")
            return False
            
        is_on = " ON" in current_text or " ENA" in current_text
        
        if not state:
            if not is_on:
                print(f"[API] {heater_name.strip()} is already OFF.")
                return True
            print(f"[API] Turning {heater_name.strip()} OFF...")
            self.press("SELECT", 2.0)
            return True
            
        # We want to turn it ON
        if not is_on:
            print(f"[API] Turning {heater_name.strip()} ON...")
            self.press("SELECT", 2.0)
        else:
            if temp is not None:
                print(f"[API] {heater_name.strip()} is already ON. Toggling OFF then ON to access Temp Menu...")
                self.press("SELECT", 2.0) # Turn OFF
                self.press("SELECT", 2.0) # Turn ON (opens Temp Menu)
        
        # If we turned it ON (or cycled it) AND we want to change temp, the Temp Sub-Menu is now OPEN!
        if temp is not None:
            # The Temp menu looks like "SET TO 82`F"
            # It usually shows up on line 3, but let's wait for "SET TO"
            if not self.wait_for_text("SET TO", timeout=8):
                print("[API] Failed to find temperature sub-menu!")
                # Attempt to back out
                self.press("BACK")
                return False
                
            # Smart temperature adjustment: find the "SET TO" line, extract the temp, and press UP/DOWN
            print("[API] Adjusting temperature...")
            import re
            for _ in range(30):
                temp_text = ""
                with self.lock:
                    for line in self.screen_lines.values():
                        if "SET TO" in line:
                            temp_text = line
                            break
                            
                match = re.search(r"SET TO\s+(\d+)", temp_text)
                if match:
                    current_temp = int(match.group(1))
                    if current_temp == temp:
                        print(f"[API] Temp set to {temp}. Confirming...")
                        self.press("SELECT", 1.0)
                        return True
                    elif current_temp < temp:
                        self.press("UP", 0.0)
                    else:
                        self.press("DOWN", 0.0)
                else:
                    self.press("DOWN", 0.0)
                    
                # Wait for screen update
                time.sleep(0.5)
                
            print(f"[API] Failed to set temp.")
            self.press("BACK")
            return False
        
        return True

    def pool_heat(self, state: bool, temp: int = None):
        """Turns the pool heater on/off and optionally sets the temperature."""
        if not self.config.get("has_pool_heater", True):
            print("[API] CONFIG LOCKOUT: Pool Heater is disabled in config. Aborting.")
            return False
        return self._toggle_heater("POOL HEATER", "POOL MODE", state, temp)
        
    def spa_heat(self, state: bool, temp: int = None):
        """Turns the spa heater on/off and optionally sets the temperature."""
        if not self.config.get("has_spa_heater", True):
            print("[API] CONFIG LOCKOUT: Spa Heater is disabled in config. Aborting.")
            return False
        return self._toggle_heater("SPA HEATER", "SPA MODE", state, temp)

    def get_status(self) -> Dict[str, any]:
        """
        Returns a thread-safe, constantly updated snapshot of the equipment status.
        Values are populated from background RS485 snooping and screen scraping.
        Unimplemented states (like solar, blower) will return None until navigated to.
        """
        with self.lock:
            # Return a copy to avoid dictionary mutation during iteration by the caller
            ret = self.status.copy()
            ret["monitor_mode"] = self.monitor_mode or (time.time() < self.dynamic_monitor_timeout)
            return ret
