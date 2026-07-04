import subprocess
import sys
import os
import time
import webbrowser

def start_backend():
    print("Starting FastAPI backend on http://localhost:8000...")
    return subprocess.Popen([sys.executable, "main.py"])

def start_frontend():
    print("Starting React frontend on http://localhost:5173...")
    frontend_dir = os.path.join(os.getcwd(), "frontend")
    # Use shell=True for npm commands on Windows
    return subprocess.Popen("npm run dev", cwd=frontend_dir, shell=True)

if __name__ == "__main__":
    backend_proc = None
    frontend_proc = None
    
    try:
        backend_proc = start_backend()
        frontend_proc = start_frontend()
        
        print("\nBoth servers are starting. Waiting a moment...")
        time.sleep(5)
        print("Opening browser...")
        webbrowser.open("http://localhost:5173")
        
        print("\nPress Ctrl+C to stop both servers.")
        while True:
            time.sleep(1)
            if backend_proc.poll() is not None:
                print("Backend process died unexpectedly.")
                break
            if frontend_proc.poll() is not None:
                print("Frontend process died unexpectedly.")
                break
                
    except KeyboardInterrupt:
        print("\nStopping servers...")
    finally:
        if backend_proc:
            backend_proc.terminate()
        if frontend_proc:
            # On Windows, terminate() might not kill sub-processes of npm
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(frontend_proc.pid)], capture_output=True)
            else:
                frontend_proc.terminate()
        print("Done.")
