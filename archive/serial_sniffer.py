#!/usr/bin/env python3
"""RS485 serial sniffer for Jandy/Pentair packets.

Reads raw data from a serial port and tries to identify Jandy and Pentair
RS485 packets, decode packet fields, validate checksums, and print the
packet function summary.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

try:
    import serial
except ImportError as exc:
    raise SystemExit(
        "pyserial is required. Install it with: pip install pyserial"
    ) from exc

from jandy import (
    JandyPacket,
    CMD_JXI_PING,
    DLE as JANDY_DLE,
    STX as JANDY_STX,
    ETX as JANDY_ETX,
)

PENTAIR_PP1 = 0xFF
PENTAIR_PP2 = 0x00
PENTAIR_PP3 = 0xFF
PENTAIR_PP4 = 0xA5

PENTAIR_CMD_NAMES: Dict[int, str] = {
    0x01: "PEN_CMD_SPEED",
    0x04: "PEN_CMD_REMOTECTL",
    0x06: "PEN_CMD_POWER",
    0x07: "PEN_CMD_STATUS",
}


def format_bytes(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def get_pentair_cmd_name(cmd: int) -> str:
    return PENTAIR_CMD_NAMES.get(cmd, f"CMD_0x{cmd:02X}")


TEMPERATURE_TEXT_PATTERN = re.compile(r'(\d{1,3}\s*(?:°|º|`)\s*[FC]?)', re.IGNORECASE)


def checksum_pentair(packet: bytes) -> int:
    # Checksum is over CMD through last data byte.
    if len(packet) < 9:
        return -1
    return sum(packet[6:-2]) & 0xFFFF


def find_text_temperatures(payload: bytes) -> List[str]:
    text = ''.join(chr(b) if 32 <= b < 127 else ' ' for b in payload)
    return TEMPERATURE_TEXT_PATTERN.findall(text)


def extract_temp_candidates(payload: bytes) -> List[int]:
    candidates = [b for b in payload if 35 <= b <= 110]
    unique_values: List[int] = []
    for candidate in candidates:
        if candidate not in unique_values:
            unique_values.append(candidate)
        if len(unique_values) >= 4:
            break
    return unique_values


def format_payload(payload: bytes) -> str:
    return " ".join(f"{b:02X}" for b in payload)


def format_payload_text(payload: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in payload)


def render_temperature_candidates(cmd: int, payload: bytes) -> List[str]:
    temps: List[str] = []
    if cmd == 0x1F and len(payload) >= 8:
        temp1 = payload[6]
        if 0 <= temp1 <= 140:
            temps.append(f"TEMP1={temp1}")
        if len(payload) >= 9:
            temp2 = payload[7]
            if 0 <= temp2 <= 140 and temp2 != temp1:
                temps.append(f"TEMP2={temp2}")
    if len(payload) >= 30:
        for match in find_text_temperatures(payload):
            temps.append(f"TEXT={match.strip()}")
    return temps


def is_jandy_packet_start(data: bytes) -> bool:
    return len(data) >= 2 and data[0] == JANDY_DLE and data[1] == JANDY_STX


def is_pentair_packet_start(data: bytes) -> bool:
    return (
        len(data) >= 4
        and data[0] == PENTAIR_PP1
        and data[1] == PENTAIR_PP2
        and data[2] == PENTAIR_PP3
        and data[3] == PENTAIR_PP4
    )


def parse_pentair_packet(buffer: Deque[int]) -> Optional[Tuple[bytes, int, bool]]:
    if len(buffer) < 9:
        return None

    header = bytes([buffer[0], buffer[1], buffer[2], buffer[3]])
    if header != bytes([PENTAIR_PP1, PENTAIR_PP2, PENTAIR_PP3, PENTAIR_PP4]):
        return None

    length = buffer[7]
    total_length = 9 + length
    if len(buffer) < total_length:
        return None

    packet_bytes = bytes([buffer[i] for i in range(total_length)])
    checksum = checksum_pentair(packet_bytes)
    if total_length >= 2:
        packet_checksum = (packet_bytes[-2] << 8) | packet_bytes[-1]
    else:
        packet_checksum = -1
    return packet_bytes, total_length, checksum == packet_checksum


def summary_pentair(packet: bytes, valid: bool, ignore_checksum: bool = False) -> str:
    source = packet[4]
    dest = packet[5]
    cmd = packet[6]
    length = packet[7]
    payload = packet[8:-2]
    cmd_name = get_pentair_cmd_name(cmd)
    summary = [f"Pentair packet ({cmd_name})", f"FROM=0x{source:02X}", f"DEST=0x{dest:02X}", f"len={length}"]
    if cmd == 0x07:
        summary.append("STATUS")

    temp_candidates = extract_temp_candidates(bytes(payload))
    if temp_candidates:
        summary.append("TEMPS=" + ",".join(str(v) for v in temp_candidates))

    # Highlight if our specific target temperatures are in the payload as raw bytes
    found_targets = [t for t in [71, 72, 77, 21, 22, 25] if t in payload]
    if found_targets:
        summary.append(f"🎯 TARGETS FOUND: {found_targets}")

    if not valid and not ignore_checksum:
        summary.append("CHECKSUM=BAD")
    return ", ".join(summary)


def consume_buffer(buffer: Deque[int], ignore_checksum: bool, debug: bool, temp_only: bool = False, button_only: bool = False) -> None:
    while buffer:
        if buffer[0] == JANDY_DLE:
            if len(buffer) < 2:
                return
            if buffer[1] != JANDY_STX:
                dropped = buffer.popleft()
                if not temp_only and not button_only:
                    print(f"[SYNC] dropped 0x{dropped:02X} to realign")
                continue
            parsed = JandyPacket.parse(list(buffer))
            if parsed is None:
                return
            packet, consumed = parsed
            
            if temp_only:
                if packet.cmd == CMD_JXI_PING and len(packet.payload) >= 4:
                    details = packet.decode_details()
                    current_temps = (details.get('pool_sp'), details.get('spa_sp'), details.get('water_temp'))
                    # Hacky way to store state across calls without refactoring to a class:
                    if not hasattr(consume_buffer, 'last_temps'):
                        consume_buffer.last_temps = None
                    if current_temps != consume_buffer.last_temps:
                        print(f"\n\033[96m>>> SETPOINTS UPDATED! Pool: {details.get('formatted_pool_sp')} | Spa: {details.get('formatted_spa_sp')} | Water: {details.get('formatted_water_temp')} <<<\033[0m")
                        consume_buffer.last_temps = current_temps
            elif button_only:
                # INTERCEPT BUTTON PRESSES LIVE (SILENT MODE)
                if packet.cmd == 0x01 and packet.dest == 0x00 and len(packet.payload) >= 2:
                    button_code = packet.payload[0]
                    # Filter out Idle Heartbeats and Screen ACKs
                    idle_codes = {0x00, 0x40, 0x54, 0xC4, 0xBC, 0x20}
                    if button_code not in idle_codes:
                        print(f"\n\033[93m>>> BUTTON PRESSED! CODE: 0x{button_code:02X} <<<\033[0m\n")
            else:
                # INTERCEPT BUTTON PRESSES LIVE
                if packet.cmd == 0x01 and packet.dest == 0x00 and len(packet.payload) >= 2:
                    button_code = packet.payload[0]
                    idle_codes = {0x00, 0x40, 0x54, 0xC4, 0xBC, 0x20}
                    if button_code not in idle_codes:
                        print(f"\n\033[93m>>> BUTTON PRESSED! CODE: 0x{button_code:02X} <<<\033[0m\n")

                print("\n[JANDY]", format_bytes(packet.raw_bytes))
                print(packet.summary(ignore_checksum=ignore_checksum))
                if debug and len(packet.payload) > 0:
                    print("  payload:", format_payload(packet.payload))
                    print("  text:   ", format_payload_text(packet.payload))
            for _ in range(consumed):
                buffer.popleft()
            continue

        if buffer[0] == PENTAIR_PP1:
            if len(buffer) < 4:
                return
            if not is_pentair_packet_start(bytes(buffer)[:4]):
                dropped = buffer.popleft()
                if not temp_only:
                    print(f"[SYNC] dropped 0x{dropped:02X} to realign")
                continue
            parsed = parse_pentair_packet(buffer)
            if parsed is None:
                return
            packet_bytes, consumed, valid = parsed
            
            if not temp_only:
                print("\n[PENTAIR]", format_bytes(packet_bytes))
                print(summary_pentair(packet_bytes, valid, ignore_checksum=ignore_checksum))
                if debug and len(packet_bytes) > 5:
                    print("  payload:", format_payload(packet_bytes[8:-2]))
                    print("  text:   ", format_payload_text(packet_bytes[8:-2]))
            for _ in range(consumed):
                buffer.popleft()
            continue

        dropped = buffer.popleft()
        if not temp_only:
            print(f"[SYNC] dropped 0x{dropped:02X} to realign")


def main() -> int:
    parser = argparse.ArgumentParser(description="RS485 serial packet sniffer for Jandy/Pentair")
    parser.add_argument("--port", required=True, help="Serial device path, e.g. /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default 9600)")
    parser.add_argument("--timeout", type=float, default=0.5, help="Read timeout in seconds")
    parser.add_argument("--ignore-checksum", action="store_true", help="Show packets even if checksum validation fails")
    parser.add_argument("--debug", action="store_true", help="Print packet payload bytes for debug")
    parser.add_argument("--temp-only", action="store_true", help="Only show the water temperature")
    parser.add_argument("--button-only", action="store_true", help="Only show intercepted button presses")
    args = parser.parse_args()

    # Pass button_only flag to consume_buffer. Since consume_buffer signature needs it, let's just pass args directly or add a new parameter.
    # Actually, it's cleaner to just update the consume_buffer function signature.

    serial_kwargs = {
        "port": args.port,
        "baudrate": args.baud,
        "bytesize": serial.EIGHTBITS,
        "parity": serial.PARITY_NONE,
        "stopbits": serial.STOPBITS_ONE,
        "timeout": args.timeout,
    }

    try:
        with serial.Serial(**serial_kwargs) as ser:
            print(f"Listening on {args.port} @ {args.baud} baud")
            buffer: Deque[int] = deque()
            while True:
                data = ser.read(4096)
                if data:
                    buffer.extend(data)
                    consume_buffer(buffer, args.ignore_checksum, args.debug, args.temp_only, args.button_only)
                else:
                    time.sleep(0.01)
    except serial.SerialException as exc:
        print(f"Serial error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped by user")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
