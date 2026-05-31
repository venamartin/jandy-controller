from fastapi import FastAPI, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import threading
import queue
import time

from jandy import JandyController

# --- API & Queue Initialization ---
api = JandyController(port='/dev/ttyUSB0', spoof_id=0x60, enable_logging=True, config_path="config.yaml")

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
app.mount("/static", StaticFiles(directory="static"), name="static")

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
