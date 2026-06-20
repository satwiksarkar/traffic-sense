import os
import subprocess
import sys
import time

def start_servers():
    print("🚀 Initializing service stack...")
    processes = []

    try:
        # 1. Start the root-level script (app.py)
        print("📁 Starting root-level application (app.py)...")
        app_process = subprocess.Popen(
            [sys.executable, "app.py"],
            stdout=None,  # Streams directly to your terminal window
            stderr=None
        )
        processes.append(app_process)

        # 2. Start the Uvicorn Backend server (backend/main.py)
        print("⚡ Starting Uvicorn backend server on port 8000...")
        
        # Determine correct absolute path to the backend directory
        backend_dir = os.path.abspath("backend")
        
        backend_process = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "main:app", 
                "--reload", 
                "--port", "8000"
            ],
            cwd=backend_dir,  # Emulates executing "cd backend" first
            stdout=None,
            stderr=None
        )
        processes.append(backend_process)

        print("\n🟢 Both servers are running. Press Ctrl+C to terminate both safely.\n")
        
        # Keep the starter script alive to monitor background tasks
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n🛑 Gracefully shutting down both execution processes...")
        for proc in processes:
            proc.terminate()
            
        # Give them a moment to close nicely, force close if they hang
        for proc in processes:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                
        print("✨ All server processes terminated.")

if __name__ == "__main__":
    start_servers()