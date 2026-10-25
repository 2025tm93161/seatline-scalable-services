from datetime import datetime, timezone
import json
import os
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[1]
SERVICES = {"booking": 8000, "inventory": 8001, "payment": 8002, "notification": 8003}


def main():
    specs = ROOT / "docs" / "openapi"
    specs.mkdir(parents=True, exist_ok=True)
    for name, port in SERVICES.items():
        url = os.environ.get(f"{name.upper()}_URL", f"http://127.0.0.1:{port}")
        response = httpx.get(url + "/openapi.json")
        response.raise_for_status()
        (specs / f"{name}.json").write_text(json.dumps(response.json(), indent=2) + "\n")
    isolation = {"timestamp": datetime.now(timezone.utc).isoformat(), "command": "python scripts/export_artifacts.py", "roles": {}}
    for service in SERVICES:
        database = create_engine(os.environ.get(f"{service.upper()}_DATABASE_URL", f"postgresql+psycopg://{service}_user:{service}_local@localhost:{os.environ.get('DB_PORT', '55432')}/{service}"))
        with database.connect() as connection:
            identity = dict(connection.execute(text("SELECT current_user AS role, current_database() AS database")).mappings().one())
            permissions = {other: connection.execute(text("SELECT has_database_privilege(current_user, :database, 'CONNECT')"), {"database": other}).scalar_one() for other in SERVICES}
            assert permissions == {other: other == service for other in SERVICES}, permissions
            isolation["roles"][service] = {**identity, "connect_permissions": permissions}
        database.dispose()
    (ROOT / "evidence" / "tests" / "database-isolation.json").write_text(json.dumps(isolation, indent=2) + "\n")
    for folder in (ROOT / "evidence").glob("challenge-*"):
        result_file = folder / "result.json"
        if not result_file.exists():
            continue
        result = json.loads(result_file.read_text())
        snapshot = {"timestamp": datetime.now(timezone.utc).isoformat(), "command": "python scripts/export_artifacts.py", "event_id": result["event_id"], "databases": {}}
        booking_id = result.get("repeated", result.get("failed", {})).get("body", {}).get("id", "")
        queries = {
            "inventory": [("events", "SELECT * FROM events WHERE id = :event_id"), ("holds", "SELECT * FROM holds WHERE event_id = :event_id")],
            "booking": [("bookings", "SELECT * FROM bookings WHERE id = :booking_id"), ("idempotency", "SELECT * FROM idempotency WHERE response LIKE :pattern")],
            "payment": [("payments", "SELECT * FROM payments WHERE booking_id = :booking_id")],
            "notification": [("deliveries", "SELECT * FROM deliveries WHERE booking_id = :booking_id")],
        }
        for service, statements in queries.items():
            database = create_engine(os.environ.get(f"{service.upper()}_DATABASE_URL", f"postgresql+psycopg://{service}_user:{service}_local@localhost:{os.environ.get('DB_PORT', '55432')}/{service}"))
            with database.connect() as connection:
                snapshot["databases"][service] = {table: [dict(row) for row in connection.execute(text(query), {"event_id": result["event_id"], "booking_id": booking_id, "pattern": f"%{booking_id or result['event_id']}%"}).mappings()] for table, query in statements}
            database.dispose()
        (folder / "database-state.json").write_text(json.dumps(snapshot, indent=2, default=str) + "\n")
        logs = []
        for path in (ROOT / "logs").glob("*.log"):
            logs.extend(line for line in path.read_text().splitlines() if line.startswith("{") and ('evidence-' in line or 'idempotency_replay' in line))
        (folder / "service-logs.txt").write_text("Captured " + snapshot["timestamp"] + "\n" + "\n".join(logs) + "\n")
    print("Exported OpenAPI specs, database snapshots and structured logs")


if __name__ == "__main__":
    main()