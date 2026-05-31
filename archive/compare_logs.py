import sys

def extract_unique_commands(log_file):
    commands = set()
    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()
            for i in range(len(lines)):
                if lines[i].startswith('[JANDY]'):
                    raw = lines[i].strip()[8:]
                    parts = raw.split()
                    if len(parts) >= 4:
                        dest = parts[2]
                        cmd = parts[3]
                        
                        # Filter out normal polling and telemetry to avoid noise
                        if cmd in ['00']: # Probes
                            continue
                        if cmd in ['0C', '0D']: # JXi Heater pings and status
                            continue
                        if cmd in ['1F', '41', '42', '43', '44', '45', '46', '20']: # ePump polling and watts
                            continue
                        if cmd == '08': # MSG_LOOP_ST
                            continue
                        
                        # For display updates (0x04), only track the screen index/line to avoid timestamp differences
                        if cmd == '04':
                            # parts: 10 02 60 04 <line_idx> ...
                            if len(parts) >= 5:
                                commands.add(f"Display Update to {dest}, Line: {parts[4]}")
                            continue
                            
                        # Add full packet for anything else (like ACKs or specific commands)
                        commands.add(raw)
    except FileNotFoundError:
        pass
    return commands

if len(sys.argv) != 3:
    print("Usage: uv run python compare_logs.py <baseline_log> <action_log>")
    sys.exit(1)

off_cmds = extract_unique_commands(sys.argv[1])
on_cmds = extract_unique_commands(sys.argv[2])

# Find what was uniquely sent when you toggled the pump!
unique_to_action = on_cmds - off_cmds

print("===================================================")
print("COMMANDS ISOLATED DURING FILTER PUMP ON/OFF ACTION:")
print("===================================================")
if unique_to_action:
    for cmd in sorted(unique_to_action):
        print(cmd)
else:
    print("No unique command packets found. (Pump is likely triggered via physical relay or snooping!)")
