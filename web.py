from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import threading
import queue
import time

from jandy import JandyController

import yaml
import os

# --- Load Config ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
config_path = os.path.join(BASE_DIR, "config.yaml")
if not os.path.exists(config_path):
    fallback_path = os.path.join(BASE_DIR, "config.example.yaml")
    if os.path.exists(fallback_path):
        print(f"[WEB] Warning: {config_path} not found. Falling back to {fallback_path}.")
        config_path = fallback_path

try:
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
        serial_port = config.get("system", {}).get("serial_port", "/dev/ttyUSB0")
        enable_logging = config.get("system", {}).get("enable_logging", False)
except Exception as e:
    print(f"[WEB] Failed to load config.yaml, defaulting to /dev/ttyUSB0. Error: {e}")
    serial_port = "/dev/ttyUSB0"
    enable_logging = False

import sys
import logging

monitor_mode = False
if "--monitor" in sys.argv:
    monitor_mode = True
    sys.argv.remove("--monitor")
    print("[WEB] Running in MONITOR MODE (TX disabled).")

# Reverse uvicorn's default access log behavior: hide by default unless --access-log is explicitly passed
if "--access-log" not in sys.argv:
    logging.getLogger("uvicorn.access").disabled = True
else:
    print("[WEB] Uvicorn access log enabled.")

# --- API & Queue Initialization ---
api = JandyController(
    port=serial_port, 
    spoof_id=0x60, 
    enable_logging=enable_logging, 
    log_file_path=os.path.join(BASE_DIR, "api-test.log"),
    config_path=config_path, 
    monitor_mode=monitor_mode
)

command_queue = queue.Queue()

def command_worker():
    """Background thread that executes JandyController commands sequentially."""
    print("[WEB] Command worker thread started.")
    while True:
        try:
            cmd = command_queue.get()
            action = cmd.get("action")
            state = cmd.get("state")
            temp = cmd.get("temp")
            
            print(f"[WEB] Executing queued command: {action} -> {state} (Temp: {temp})")
            
            if action == "all_off":
                api.all_off()
            elif hasattr(api, action):
                func = getattr(api, action)
                if temp is not None:
                    func(state, temp)
                else:
                    func(state)
            else:
                print(f"[WEB] Error: Unknown action '{action}'")
                
            command_queue.task_done()
        except Exception as e:
            print(f"[WEB] Worker error: {e}")

# Start the background worker
worker_thread = threading.Thread(target=command_worker, daemon=True)
worker_thread.start()

# --- FastAPI Setup ---
app = FastAPI(title="Jandy Autonomous API")

# Mount the static folder at the root to serve index.html, style.css, and app.js
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static"), html=True), name="static")

class CommandRequest(BaseModel):
    action: str
    state: bool = False
    temp: int = None

@app.get("/api/status")
def get_status():
    """Returns the instant snapshot of the equipment state and hardware configuration."""
    return {
        "status": api.get_status(),
        "config": api.config
    }

@app.post("/api/command")
def send_command(cmd: CommandRequest):
    """Queues a command for the background worker to execute."""
    command_queue.put({
        "action": cmd.action,
        "state": cmd.state,
        "temp": cmd.temp
    })
    return JSONResponse(status_code=202, content={"status": "queued", "command": cmd.model_dump()})

# Simple root redirect to the static HTML
from fastapi.responses import RedirectResponse
@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")
