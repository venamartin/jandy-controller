import serial
import time
import argparse
import sys
from typing import List

def decode_leds(payload: bytes) -> List[str]:
    leds = []
    for byte in payload[:5]:
        for bit in range(0, 8, 2):
            if (byte >> (bit + 1)) & 1:
                leds.append("FLASH")
            elif (byte >> bit) & 1:
                leds.append("ON")
            else:
                leds.append("OFF")
    return leds

def jandy_checksum(packet: bytes) -> int:
    """Calculates Jandy checksum: sum of all bytes up to checksum byte."""
    chk = 0
    for b in packet:
        chk = (chk + b) & 0xFF
    return chk

def create_ack() -> bytes:
    """Creates a properly checksummed ACK packet."""
    # DLE, STX, DEST(Master), CMD(ACK), ACK_TYPE(Normal), CMD_DATA(0x00)
    packet = bytearray([0x10, 0x02, 0x00, 0x01, 0x80, 0x00])
    packet.append(jandy_checksum(packet))
    packet.extend([0x10, 0x03]) # DLE, ETX
    return bytes(packet)

def main():
    parser = argparse.ArgumentParser(description="Jandy Status Bitmask Sniffer Wizard")
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Serial port")
    args = parser.parse_args()

    print(f"Opening {args.port} at 9600 baud...")
    ser = serial.Serial(args.port, 9600, timeout=1.0)
    
    mapping_sequence = [
        {"name": "POOL MODE", "action": "Turn ON", "prereq": "Make sure everything is OFF first."},
        {"name": "POOL HEATER", "action": "Turn ON", "prereq": "Pool Mode must be ON."},
        {"name": "CLEANER", "action": "Turn ON", "prereq": "Pool Mode must be ON."},
        {"name": "SOLAR HEATER", "action": "Turn ON", "prereq": "Pool Mode must be ON."},
        {"name": "ALL OFF (Prep for Spa)", "action": "Turn OFF everything", "prereq": "Wait for valves to rotate if needed."},
        {"name": "SPA MODE", "action": "Turn ON", "prereq": "Make sure Pool Mode is OFF."},
        {"name": "SPA HEATER", "action": "Turn ON", "prereq": "Spa Mode must be ON."},
        {"name": "POOL LIGHT", "action": "Turn ON", "prereq": "Independent."},
        {"name": "SPA LIGHT", "action": "Turn ON", "prereq": "Independent."}
    ]

    print("=" * 60)
    print("JANDY EQUIPMENT MAPPING WIZARD (ALL-BUTTON EDITION)")
    print("=" * 60)
    print("This script will guide you through turning on equipment one by one.")
    
    input("\nPress ENTER when you are ready to begin...")

    last_leds = None
    known_leds = {}
    current_step = 0
    
    buffer = bytearray()
    print("Getting baseline status. Please wait...")
    
    ALL_BUTTON_ACK = create_ack()
    
    while last_leds is None:
        if ser.in_waiting:
            buffer.extend(ser.read(ser.in_waiting))
            while b'\x10\x02' in buffer:
                start_idx = buffer.find(b'\x10\x02')
                end_idx = buffer.find(b'\x10\x03', start_idx)
                if end_idx != -1:
                    packet = buffer[start_idx:end_idx + 2]
                    buffer = buffer[end_idx + 2:]
                    if len(packet) > 3:
                        dest = packet[2]
                        cmd = packet[3]
                        
                        # Spoof the All-Button panel when probed
                        if dest == 0x58 and cmd == 0x00:
                            ser.write(ALL_BUTTON_ACK)
                        
                        # Listen for the 5-byte LED status payload
                        elif dest == 0x58 and cmd == 0x02:
                            payload = packet[4:-3]
                            if len(payload) >= 5:
                                last_leds = decode_leds(payload)
                                break
                else:
                    break
        time.sleep(0.01)
        
    print("Baseline acquired!")
    
    active_leds = [i for i, state in enumerate(last_leds) if state != "OFF"]
    if active_leds:
        print("\n" + "!" * 60)
        print("WARNING: Some equipment is currently turned ON!")
        print(f"Active LED Indices: {active_leds}")
        print("Please turn EVERYTHING OFF on your physical remote.")
        print("Waiting for all equipment to turn off...")
        print("!" * 60)
        
        while active_leds:
            if ser.in_waiting:
                buffer.extend(ser.read(ser.in_waiting))
                while b'\x10\x02' in buffer:
                    start_idx = buffer.find(b'\x10\x02')
                    end_idx = buffer.find(b'\x10\x03', start_idx)
                    if end_idx != -1:
                        packet = buffer[start_idx:end_idx + 2]
                        buffer = buffer[end_idx + 2:]
                        if len(packet) > 3:
                            dest = packet[2]
                            cmd = packet[3]
                            if dest == 0x58 and cmd == 0x00:
                                ser.write(ALL_BUTTON_ACK)
                            elif dest == 0x58 and cmd == 0x02:
                                payload = packet[4:-3]
                                if len(payload) >= 5:
                                    last_leds = decode_leds(payload)
                                    active_leds = [i for i, state in enumerate(last_leds) if state != "OFF"]
                    else:
                        break
            time.sleep(0.05)
            
        print("\n✅ PERFECT! Everything is OFF. Starting wizard...")
        time.sleep(2)
    
    try:
        while current_step < len(mapping_sequence):
            step = mapping_sequence[current_step]
            
            print("\n" + "-" * 60)
            print(f"STEP {current_step + 1} of {len(mapping_sequence)}: Map '{step['name']}'")
            print(f"-> PREREQUISITE: {step['prereq']}")
            print(f"-> ACTION: Please {step['action']} '{step['name']}' on your physical remote.")
            print("-" * 60)
            print("Waiting for you to press the button...")

            step_completed = False
            
            while not step_completed:
                if ser.in_waiting:
                    buffer.extend(ser.read(ser.in_waiting))
                    
                    while b'\x10\x02' in buffer:
                        start_idx = buffer.find(b'\x10\x02')
                        end_idx = buffer.find(b'\x10\x03', start_idx)
                        
                        if end_idx != -1:
                            packet = buffer[start_idx:end_idx + 2]
                            buffer = buffer[end_idx + 2:]
                            
                            if len(packet) > 3:
                                dest = packet[2]
                                cmd = packet[3]
                                
                                if dest == 0x58 and cmd == 0x00:
                                    ser.write(ALL_BUTTON_ACK)
                                elif dest == 0x58 and cmd == 0x02:
                                    payload = packet[4:-3]
                                    if len(payload) >= 5:
                                        leds = decode_leds(payload)
                                        
                                        if leds != last_leds:
                                            for i in range(20):
                                                if leds[i] != last_leds[i]:
                                                    if step['name'] != "ALL OFF (Prep for Spa)" and leds[i] in ("ON", "FLASH"):
                                                        if i not in known_leds.values():
                                                            print(f"\n✅ DETECTED! '{step['name']}' is mapped to LED Index {i} (State: {leds[i]})")
                                                            known_leds[step['name']] = i
                                                            last_leds = leds
                                                            step_completed = True
                                                            time.sleep(2)
                                                            break
                                                    elif step['name'] == "ALL OFF (Prep for Spa)":
                                                        all_off = True
                                                        for mapped_name, mapped_idx in known_leds.items():
                                                            if mapped_name in ["POOL MODE", "POOL HEATER", "CLEANER", "SOLAR HEATER"]:
                                                                if leds[mapped_idx] != "OFF":
                                                                    all_off = False
                                                        if all_off:
                                                            print("\n✅ DETECTED! Everything is OFF. Moving to Spa Mode mapping.")
                                                            last_leds = leds
                                                            step_completed = True
                                                            time.sleep(2)
                                                            break
                                            
                                            last_leds = leds
                        else:
                            break
                            
                time.sleep(0.05)
                
            current_step += 1

        print("\n" + "=" * 60)
        print("MAPPING COMPLETE! Here are your results:")
        print("=" * 60)
        for name, index in known_leds.items():
            print(f"'{name}': {index}")
            
        print("\nPlease copy/paste this list so we can update the API!")
            
    except KeyboardInterrupt:
        print("\nMapping aborted by user.")
        print("Partial results:")
        for name, index in known_leds.items():
            print(f"'{name}': {index}")
    finally:
        ser.close()

if __name__ == "__main__":
    main()
