import serial
import time
from collections import Counter

ser = serial.Serial('/dev/ttyUSB0', 9600, timeout=1.0)
buffer = bytearray()
cmd_counts = Counter()
start_time = time.time()

print("Analyzing all packets on the RS-485 bus for 10 seconds...")
print("-" * 50)

try:
    while time.time() - start_time < 10:
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
                        cmd_counts[(dest, cmd)] += 1
                else:
                    break
        time.sleep(0.01)
        
    print("\n--- PACKET FREQUENCY ANALYSIS ---")
    for (dest, cmd), count in cmd_counts.most_common():
        print(f"DEST: 0x{dest:02X} | CMD: 0x{cmd:02X} | Count: {count}")
        
except KeyboardInterrupt:
    pass
finally:
    ser.close()
