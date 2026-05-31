from __future__ import annotations

"""
Jandy RS-485 Protocol Library
=============================

ARCHITECTURE NOTES:
- The Jandy RS-485 architecture is highly centralized. The Master Controller (0x00) is the "brain", 
  while keypads (0x60), spa-side remotes, and iAqualink modules are "dumb" terminals.
- When a user interacts with the system, keypads send Button Press codes (via CMD_ACK or CMD_MSG payloads).
- The Master Controller processes these presses, physically toggles internal 24V relays for power, and 
  broadcasts screen updates (CMD_MSG_LONG) back to the keypads.
- Equipment like the ePump (0x78) does not typically receive direct "Turn On/Off" commands over RS-485. 
  Instead, it powers on because the Master clicked the physical Filter Pump Relay (supplying power or a digital input trigger), 
  and the Master continuously polls the pump for Watts and RPM regardless of its power state.

EPUMP ENCODING QUIRKS:
- The Master sends setpoint requests (e.g., CMD_EPUMP_WATTS 0x45) with parameters encoded in Big-Endian.
- The ePump responds with a CMD_EPUMP_STATUS (0x1F) packet that echoes the requested command, 
  echoes the Big-Endian setpoint, and appends the actual live telemetry data.
- The appended live telemetry data (like Watts) is encoded in Little-Endian (e.g., 1977W = 0x07B9 -> B9 07).
"""

from typing import Dict, List, Optional, Tuple


# Protocol Constants
DLE = 0x10
STX = 0x02
ETX = 0x03

# Device IDs
MASTER_ID = 0x00
HEATER_JXI_MIN = 0x68
HEATER_JXI_MAX = 0x6B
EPUMP_MIN = 0x78
EPUMP_MAX = 0x7B
SWG_MIN = 0x50
SWG_MAX = 0x53

# Jandy Commands
CMD_PROBE = 0x00
CMD_ACK = 0x01
CMD_STATUS = 0x02
CMD_MSG = 0x03
CMD_MSG_LONG = 0x04
CMD_MSG_LOOP_ST = 0x08
CMD_PDA_HIGHLIGHT = 0x08
CMD_PDA_CLEAR = 0x09
CMD_JXI_PING = 0x0C
CMD_JXI_STATUS = 0x0D
CMD_PDA_SHIFTLINES = 0x0F
CMD_PDA_HIGHLIGHTCHARS = 0x10
CMD_PERCENT = 0x11
CMD_PPM = 0x16
CMD_EPUMP_STATUS = 0x1F
CMD_EPUMP_RPM = 0x44
CMD_EPUMP_WATTS = 0x45

JANDY_CMD_NAMES: Dict[int, str] = {
    CMD_PROBE: "CMD_PROBE",
    CMD_ACK: "CMD_ACK",
    CMD_STATUS: "CMD_STATUS",
    CMD_MSG: "CMD_MSG",
    CMD_MSG_LONG: "CMD_MSG_LONG",
    CMD_PDA_HIGHLIGHT: "CMD_PDA_HIGHLIGHT / CMD_MSG_LOOP_ST",
    CMD_PDA_CLEAR: "CMD_PDA_CLEAR",
    CMD_PDA_SHIFTLINES: "CMD_PDA_SHIFTLINES",
    CMD_PDA_HIGHLIGHTCHARS: "CMD_PDA_HIGHLIGHTCHARS",
    CMD_JXI_PING: "CMD_JXI_PING",
    CMD_JXI_STATUS: "CMD_JXI_STATUS",
    CMD_PERCENT: "CMD_PERCENT",
    CMD_PPM: "CMD_PPM",
    CMD_EPUMP_STATUS: "CMD_EPUMP_STATUS",
    CMD_EPUMP_RPM: "CMD_EPUMP_RPM",
    CMD_EPUMP_WATTS: "CMD_EPUMP_WATTS",
}

# Keypad Button Codes (Sent in Payload of CMD_ACK 0x01 to Master)
BUTTON_CODES: Dict[str, int] = {
    "UP": 0x06,
    "DOWN": 0x05,
    "SELECT": 0x04,
    "BACK": 0x02,
    "NONE": 0x00,
}


def get_cmd_name(cmd: int) -> str:
    """Returns a friendly name for the Jandy command."""
    return JANDY_CMD_NAMES.get(cmd, f"CMD_0x{cmd:02X}")


def get_device_name(device_id: int) -> str:
    """Returns a friendly name for the Jandy device ID."""
    if device_id == MASTER_ID:
        return "Master/Controller"
    if HEATER_JXI_MIN <= device_id <= HEATER_JXI_MAX:
        return f"JXi Heater (0x{device_id:02X})"
    if EPUMP_MIN <= device_id <= EPUMP_MAX:
        return f"ePump (0x{device_id:02X})"
    if SWG_MIN <= device_id <= SWG_MAX:
        return f"Aquapure SWG (0x{device_id:02X})"
    return f"Device_0x{device_id:02X}"


def calculate_checksum(packet_bytes: bytes) -> int:
    """Calculates Jandy 8-bit checksum over packet excluding last 3 bytes."""
    if len(packet_bytes) < 3:
        return 0
    return sum(packet_bytes[:-3]) & 0xFF


def validate_checksum(packet_bytes: bytes) -> bool:
    """Validates the checksum of a complete Jandy packet."""
    if len(packet_bytes) < 6:
        return False
    
    # Extract the checksum byte
    checksum_val = packet_bytes[-3]
    
    # 1. Standard checksum validation
    if calculate_checksum(packet_bytes) == checksum_val:
        return True

    # 2. Known bug workaround: Long messages (0x04) to OneTouch keypad sometimes have bad checksums
    cmd = packet_bytes[3]
    if cmd == CMD_MSG_LONG and len(packet_bytes) >= 5:
        first_payload_byte = packet_bytes[4]
        if first_payload_byte == 0x03 and checksum_val == 0x0A:
            return True

    return False


def format_temp(temp: int) -> str:
    """Formats temperature values, mapping 255 to N/A."""
    if temp == 255:
        return "N/A"
    return f"{temp}°F"


class JandyPacket:
    """Represents a Jandy RS485 protocol packet."""

    def __init__(self, raw_bytes: bytes, valid: bool):
        self.raw_bytes = raw_bytes
        self.valid = valid
        self.dest = raw_bytes[2] if len(raw_bytes) > 2 else 0
        self.cmd = raw_bytes[3] if len(raw_bytes) > 3 else 0
        self.payload = raw_bytes[4:-3] if len(raw_bytes) > 7 else b""

    @classmethod
    def parse(cls, buffer: List[int]) -> Optional[Tuple[JandyPacket, int]]:
        """Parses a Jandy packet from a byte buffer.
        
        Returns a tuple of (JandyPacket, bytes_consumed) if a packet is found,
        otherwise returns None.
        """
        if len(buffer) < 6:
            return None

        if buffer[0] != DLE or buffer[1] != STX:
            return None

        decoded: List[int] = []
        index = 2
        while index < len(buffer):
            byte = buffer[index]
            if byte == DLE:
                if index + 1 >= len(buffer):
                    return None
                next_byte = buffer[index + 1]
                if next_byte == 0x00:
                    decoded.append(DLE)
                    index += 2
                    continue
                if next_byte == ETX:
                    packet_bytes = bytes([DLE, STX] + decoded + [DLE, ETX])
                    if len(decoded) < 3:
                        return None
                    valid = validate_checksum(packet_bytes)
                    return cls(packet_bytes, valid), index + 2
            decoded.append(byte)
            index += 1
        return None

    def decode_details(self) -> Dict[str, any]:
        """Decodes the command-specific payload fields."""
        details: Dict[str, any] = {
            "dest_name": get_device_name(self.dest),
            "cmd_name": get_cmd_name(self.cmd),
        }

        if self.cmd == CMD_JXI_PING and len(self.payload) >= 4:
            details["flags"] = self.payload[0]
            details["pool_sp"] = self.payload[1]
            details["spa_sp"] = self.payload[2]
            details["water_temp"] = self.payload[3]
            details["formatted_water_temp"] = format_temp(self.payload[3])
            details["formatted_pool_sp"] = format_temp(self.payload[1])
            details["formatted_spa_sp"] = format_temp(self.payload[2])

        elif self.cmd == CMD_PERCENT and len(self.payload) >= 1:
            details["swg_percent"] = self.payload[0]

        elif self.cmd == CMD_PPM and len(self.payload) >= 2:
            details["swg_ppm"] = self.payload[0] * 100
            details["swg_status"] = self.payload[1]

        elif self.cmd == CMD_EPUMP_RPM and len(self.payload) >= 2:
            details["rpm"] = (self.payload[0] << 8) | self.payload[1]

        elif self.cmd == CMD_EPUMP_WATTS and len(self.payload) >= 2:
            details["watts"] = (self.payload[0] << 8) | self.payload[1]

        elif self.cmd == CMD_EPUMP_STATUS and len(self.payload) >= 5:
            orig_cmd = self.payload[0]
            details["orig_cmd"] = orig_cmd
            if orig_cmd == CMD_EPUMP_WATTS:
                # payload[1:3] is the echoed WATTS_SET value (big-endian)
                # payload[3:5] is the actual current WATTS (little-endian)
                details["watts"] = (self.payload[4] << 8) | self.payload[3]
            elif orig_cmd == CMD_EPUMP_RPM and len(self.payload) >= 5:
                # RPM encoding may be different, we will parse what we can safely
                pass

        return details

    def summary(self, ignore_checksum: bool = False) -> str:
        """Returns a human-readable text summary of the packet."""
        cmd_name = get_cmd_name(self.cmd)
        dest_name = get_device_name(self.dest)
        parts = [
            f"Jandy ({cmd_name})",
            f"DEST={dest_name}",
            f"len={len(self.payload)}",
        ]

        details = self.decode_details()
        if self.cmd == CMD_JXI_PING and "water_temp" in details:
            parts.append(
                f"POOL_SP={details['formatted_pool_sp']} "
                f"SPA_SP={details['formatted_spa_sp']} "
                f"WATER_TEMP={details['formatted_water_temp']}"
            )
        elif self.cmd == CMD_PERCENT and "swg_percent" in details:
            parts.append(f"SWG%={details['swg_percent']}%")
        elif self.cmd == CMD_PPM and "swg_ppm" in details:
            parts.append(f"PPM={details['swg_ppm']} STATUS=0x{details['swg_status']:02X}")
        elif self.cmd == CMD_EPUMP_RPM and "rpm" in details:
            parts.append(f"RPM_SET={details['rpm']}")
        elif self.cmd == CMD_EPUMP_WATTS and "watts" in details:
            parts.append(f"WATTS_SET={details['watts']}")
        elif self.cmd == CMD_EPUMP_STATUS and "rpm" in details:
            parts.append(f"RPM={details['rpm']} WATTS={details['watts']}")

        if not self.valid and not ignore_checksum:
            parts.append("CHECKSUM=BAD")

        return ", ".join(parts)
