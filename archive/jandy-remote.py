import sys
import tty
import termios
import threading
import queue
import time
import argparse
import serial
from datetime import datetime
from collections import deque
from jandy import JandyPacket, DLE, STX, BUTTON_CODES

# Device ID we will "Spoof"
# We are changing this to 0x60 to hijack the physical keypad's identity!
SPOOF_ID = 0x60 

def getch():
    """Reads a single character from standard input without requiring Enter."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
        if ch == '\x1b':
            # Arrow keys are multiple characters
            ch2 = sys.stdin.read(2)
            return ch + ch2
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def input_thread(cmd_queue: queue.Queue, log_file):
    """Thread to asynchronously read keyboard input."""
    print("Remote Control Started! Use Arrow Keys or W/S/ENTER/B. Press Ctrl+C to quit.")
    while True:
        ch = getch()
        if ch == '\x03': # Ctrl+C
            cmd_queue.put('QUIT')
            break
        
        command = None
        if ch in ('w', 'W', '\x1b[A'):
            command = 'UP'
        elif ch in ('s', 'S', '\x1b[B'):
            command = 'DOWN'
        elif ch in ('\r', '\n', ' '):
            command = 'SELECT'
        elif ch in ('b', 'B', '\x1b', '\x1b[D'):
            command = 'BACK'
            
        if command:
            print(f"\n[QUEUE] Queued button press: {command}\n\r")
            log_file.write(f"{datetime.now()} - USER PRESSED KEYBOARD: Queued {command}\n")
            log_file.flush()
            cmd_queue.put(command)

def calculate_checksum(packet_bytes: bytes) -> int:
    return sum(packet_bytes) & 0xFF

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="Serial device path")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--spoof", type=int, default=SPOOF_ID, help="ID to spoof (default 0x58)")
    args = parser.parse_args()

    cmd_queue = queue.Queue()
    log_file = open("remote-test.log", "w")
    log_file.write(f"--- Jandy Remote Test Started at {datetime.now()} ---\n")
    
    # Start input thread
    t = threading.Thread(target=input_thread, args=(cmd_queue, log_file))
    t.daemon = True
    t.start()

    pending_command = None

    try:
        with serial.Serial(args.port, args.baud, timeout=0.1) as ser:
            buffer = deque()
            
            while True:
                # Check for quit
                try:
                    msg = cmd_queue.get_nowait()
                    if msg == 'QUIT':
                        break
                    elif msg:
                        pending_command = msg
                except queue.Empty:
                    pass

                # Read RS485
                data = ser.read(1024)
                if data:
                    buffer.extend(data)
                
                # Process buffer
                while buffer:
                    if buffer[0] == DLE:
                        if len(buffer) < 2:
                            break
                        if buffer[1] != STX:
                            buffer.popleft()
                            continue
                            
                        parsed = JandyPacket.parse(list(buffer))
                        if parsed is None:
                            break
                        packet, consumed = parsed
                        
                        # Log everything to file
                        hex_bytes = " ".join(f"{b:02X}" for b in packet.raw_bytes)
                        log_file.write(f"{datetime.now()} - [RECV] {hex_bytes}\n")
                        log_file.write(f"  {packet.summary(True)}\n")
                        
                        # If it's a display update to the physical keypad (0x60), print it so user can see menu!
                        if packet.cmd == 0x04 and packet.dest == 0x60:
                            if len(packet.payload) > 1:
                                line_idx = packet.payload[0]
                                text = ''.join(chr(b) if 32 <= b < 127 else ' ' for b in packet.payload[1:])
                                print(f"\r[SCREEN] Line {line_idx:02d}: {text.strip()}")
                        
                        # Print the Cursor Position!
                        if packet.cmd == 0x08 and packet.dest == 0x60:
                            if len(packet.payload) > 0:
                                cursor_line = packet.payload[0]
                                print(f"\r[CURSOR] =======> HIGHLIGHT IS NOW ON LINE {cursor_line:02d} <=======")
                        
                        # If the packet is destined for us, we MUST ACK!
                        if packet.dest == args.spoof and packet.cmd != 0x01:
                            # We always send an ACK. If we have a pending command, we send the button!
                            button_val = BUTTON_CODES["NONE"]
                            if pending_command:
                                button_val = BUTTON_CODES[pending_command]
                                log_file.write(f"{datetime.now()} - [ACTION] INJECTING '{pending_command}' (0x{button_val:02X}) INTO BUS!\n")
                                print(f"\r[INJECT] Firing {pending_command} into bus window!     ")
                                pending_command = None
                            
                            # Construct ACK: [DLE, STX, DEST, CMD, 0x40, BUTTON, CHKSUM, DLE, ETX]
                            ack_bytes = bytearray([0x10, 0x02, 0x00, 0x01, 0x40, button_val])
                            chk = calculate_checksum(ack_bytes)
                            ack_bytes.extend([chk, 0x10, 0x03])
                            
                            ser.write(ack_bytes)
                            log_file.write(f"{datetime.now()} - [SEND] {' '.join(f'{b:02X}' for b in ack_bytes)}\n")
                            
                        # Consume packet from buffer
                        for _ in range(consumed):
                            buffer.popleft()
                        
                        log_file.flush()
                    else:
                        buffer.popleft() # Drop garbage
                        
                time.sleep(0.005)

    except serial.SerialException as e:
        print(f"\rSerial Error: {e}")
    finally:
        log_file.write(f"--- Stopped at {datetime.now()} ---\n")
        log_file.close()
        print("\rExiting.")

if __name__ == "__main__":
    main()
