import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import httpx


ROOT = Path(__file__).resolve().parents[1]
SERVICES = {"inventory": 8001, "payment": 8002, "notification": 8003, "booking": 8000}


def main():
    processes = []
    streams = []
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    (ROOT / "logs").mkdir(exist_ok=True)
    try:
        for service, default_port in SERVICES.items():
            port = os.environ.get(f"{service.upper()}_PORT", str(default_port))
            environment = dict(os.environ)
            environment["DATABASE_URL"] = os.environ.get(f"{service.upper()}_DATABASE_URL", f"postgresql+psycopg://{service}_user:{service}_local@localhost:{os.environ.get('DB_PORT', '55432')}/{service}")
            environment["FRONTEND_DIR"] = str(ROOT / "frontend")
            for dependency in ("inventory", "payment", "notification"):
                environment[f"{dependency.upper()}_URL"] = os.environ.get(f"{dependency.upper()}_URL", f"http://127.0.0.1:{os.environ.get(dependency.upper() + '_PORT', str(SERVICES[dependency]))}")
            stream = open(ROOT / "logs" / f"{service}.log", "a", buffering=1)
            streams.append(stream)
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", f"services.{service}.main:app", "--host", os.environ.get("HOST", "127.0.0.1"), "--port", port], cwd=ROOT, env=environment, stdout=stream, stderr=stream)
            processes.append(process)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("A service exited. Inspect logs/*.log (ports may be occupied).")
            try:
                for service, default_port in SERVICES.items():
                    httpx.get(f"http://127.0.0.1:{os.environ.get(service.upper() + '_PORT', str(default_port))}/health", timeout=1).raise_for_status()
                break
            except httpx.HTTPError:
                continue
        else:
            raise RuntimeError("Services did not become healthy; inspect logs/*.log")
        print(json.dumps({"status": "ready", "console": f"http://127.0.0.1:{os.environ.get('BOOKING_PORT', '8000')}", "logs": "logs/"}), flush=True)
        while not stopping:
            if any(process.poll() is not None for process in processes):
                raise RuntimeError("A service stopped. Inspect logs/*.log")
            signal.pause()
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for stream in streams:
            stream.close()


if __name__ == "__main__":
    main()