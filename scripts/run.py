import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import httpx


ROOT = Path(__file__).resolve().parents[1]

SERVICES = {
    "inventory": 8001,
    "payment": 8002,
    "notification": 8003,
    "booking": 8000,
}

STARTUP_TIMEOUT_SECONDS = 30
HEALTH_CHECK_TIMEOUT_SECONDS = 1


def main():
    processes = []
    streams = []
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    log_directory = ROOT / "logs"
    log_directory.mkdir(exist_ok=True)

    print("Starting Seatline microservices...", flush=True)

    try:
        for service, default_port in SERVICES.items():
            port = os.environ.get(
                f"{service.upper()}_PORT",
                str(default_port),
            )

            environment = dict(os.environ)

            environment["DATABASE_URL"] = os.environ.get(
                f"{service.upper()}_DATABASE_URL",
                (
                    f"postgresql+psycopg://"
                    f"{service}_user:{service}_local@127.0.0.1:"
                    f"{os.environ.get('DB_PORT', '55432')}/{service}"
                ),
            )

            environment["FRONTEND_DIR"] = str(ROOT / "frontend")

            for dependency in ("inventory", "payment", "notification"):
                environment[f"{dependency.upper()}_URL"] = os.environ.get(
                    f"{dependency.upper()}_URL",
                    (
                        f"http://127.0.0.1:"
                        f"{os.environ.get(dependency.upper() + '_PORT', str(SERVICES[dependency]))}"
                    ),
                )

            log_file = log_directory / f"{service}.log"

            stream = open(
                log_file,
                "a",
                buffering=1,
            )
            streams.append(stream)

            print(
                f"Starting {service} service "
                f"on port {port} "
                f"(log: logs/{service}.log)",
                flush=True,
            )

            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    f"services.{service}.main:app",
                    "--host",
                    os.environ.get("HOST", "127.0.0.1"),
                    "--port",
                    port,
                ],
                cwd=ROOT,
                env=environment,
                stdout=stream,
                stderr=stream,
            )

            processes.append(process)

        print(
            f"Waiting up to {STARTUP_TIMEOUT_SECONDS} seconds "
            "for all services to become healthy...",
            flush=True,
        )

        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS

        while time.monotonic() < deadline:
            for (service, _), process in zip(SERVICES.items(), processes):
                if process.poll() is not None:
                    raise RuntimeError(
                        f"{service} service exited with code "
                        f"{process.returncode}. "
                        f"Inspect logs/{service}.log"
                    )

            try:
                for service, default_port in SERVICES.items():
                    port = os.environ.get(
                        f"{service.upper()}_PORT",
                        str(default_port),
                    )

                    health_url = f"http://127.0.0.1:{port}/health"

                    httpx.get(
                        health_url,
                        timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
                    ).raise_for_status()

                break

            except httpx.HTTPError:
                continue

        else:
            unhealthy_services = []

            for service, default_port in SERVICES.items():
                port = os.environ.get(
                    f"{service.upper()}_PORT",
                    str(default_port),
                )

                health_url = f"http://127.0.0.1:{port}/health"

                try:
                    httpx.get(
                        health_url,
                        timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
                    ).raise_for_status()

                except httpx.HTTPError:
                    unhealthy_services.append(service)

            raise RuntimeError(
                "Services did not become healthy within "
                f"{STARTUP_TIMEOUT_SECONDS} seconds. "
                f"Unhealthy services: {', '.join(unhealthy_services)}. "
                "Inspect the corresponding logs/*.log files."
            )

        print(
            json.dumps(
                {
                    "status": "ready",
                    "console": (
                        f"http://127.0.0.1:"
                        f"{os.environ.get('BOOKING_PORT', '8000')}"
                    ),
                    "logs": "logs/",
                }
            ),
            flush=True,
        )

        while not stopping:
            for (service, _), process in zip(SERVICES.items(), processes):
                if process.poll() is not None:
                    raise RuntimeError(
                        f"{service} service stopped unexpectedly "
                        f"with code {process.returncode}. "
                        f"Inspect logs/{service}.log"
                    )

            signal.pause()

    finally:
        print("Stopping Seatline microservices...", flush=True)

        for (service, _), process in zip(SERVICES.items(), processes):
            if process.poll() is None:
                print(
                    f"Stopping {service} service...",
                    flush=True,
                )
                process.terminate()

        for (service, _), process in zip(SERVICES.items(), processes):
            try:
                process.wait(timeout=5)

            except subprocess.TimeoutExpired:
                print(
                    f"{service} service did not stop within 5 seconds. "
                    "Forcing termination.",
                    flush=True,
                )

                process.kill()
                process.wait()

        for stream in streams:
            stream.close()

        print("All Seatline services stopped.", flush=True)


if __name__ == "__main__":
    main()
