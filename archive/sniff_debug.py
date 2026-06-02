import serial
import time

def decode_leds(payload):
    leds = []
    for byte in payload[:5]:
        for bit in range(0, 8, 2):
            if (byte >> (bit + 1)) & 1: leds.append("FLASH")
            elif (byte >> bit) & 1: leds.append("ON")
            else: leds.append("OFF")
    return leds

ser = serial.Serial('/dev/ttyUSB0', 9600, timeout=1.0)
last_leds = None
buffer = bytearray()
print("Spoofing an All-Button Panel to trick the Master Controller into sending LED states...")
print("Listening to ALL 0x02 LED state changes...")
print("-" * 50)

# The ACK packet from an All-Button panel (ID 0x58) back to the Master (0x00)
ACK_PACKET = bytes([0x10, 0x02, 0x00, 0x01, 0x58, 0x00, 0x6B, 0x10, 0x03])

try:
    while True:
        if ser.in_waiting:
            buffer.extend(ser.read(ser.in_waiting))
            while b'\x10\x02' in buffer:
                s = buffer.find(b'\x10\x02')
                e = buffer.find(b'\x10\x03', s)
                if e != -1:
                    packet = buffer[s:e+2]
                    buffer = buffer[e+2:]
                    
                    if len(packet) > 3:
                        dest = packet[2]
                        cmd = packet[3]
                        
                        # If the master is probing for our fake All-Button panel (0x58), ACK it!
                        if dest == 0x58 and cmd == 0x00:
                            ser.write(ACK_PACKET)
                            
                        # If the master is sending an LED Status packet (0x02) to our fake panel
                        if cmd == 0x02:
                            payload = packet[4:-3] # Skip checksum and ETX
                            if len(payload) >= 5:
                                leds = decode_leds(payload)
                                if leds != last_leds:
                                    on_idx = [i for i, x in enumerate(leds) if x != "OFF"]
                                    print(f"[{time.strftime('%H:%M:%S')}] Active LEDs: {on_idx}")
                                    last_leds = leds
                else:
                    break
        time.sleep(0.01)
except KeyboardInterrupt:
    pass
