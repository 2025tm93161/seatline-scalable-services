import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import uuid

import httpx


ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("BOOKING_URL", "http://127.0.0.1:8000")
INVENTORY = os.environ.get("INVENTORY_URL", "http://127.0.0.1:8001")
PAYMENT = os.environ.get("PAYMENT_URL", "http://127.0.0.1:8002")


def call(method, url, payload=None, key=None):
    headers = {"X-Request-ID": f"evidence-{uuid.uuid4()}"}
    if key:
        headers["Idempotency-Key"] = key
    response = httpx.request(method, url, json=payload, headers=headers, timeout=60)
    return {"status": response.status_code, "body": response.json(), "replayed": response.headers.get("Idempotency-Replayed", "false")}


def fixture(capacity=5):
    event_id = "evidence-" + str(uuid.uuid4())
    result = call("POST", INVENTORY + "/api/v1/events", {"id": event_id, "name": "Challenge fixture", "capacity": capacity, "price_cents": 2500}, event_id)
    assert result["status"] == 201, result
    return event_id


def concurrency():
    event_id = fixture()
    barrier = threading.Barrier(20)

    def attempt(index):
        identifier = str(uuid.uuid4())
        barrier.wait()
        return call("POST", INVENTORY + "/api/v1/holds", {"id": identifier, "event_id": event_id, "quantity": 1}, identifier)

    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(pool.map(attempt, range(20)))
    final = next(event for event in call("GET", INVENTORY + "/api/v1/events")["body"] if event["id"] == event_id)
    assert sum(item["status"] == 201 for item in responses) == 5, responses
    assert sum(item["status"] == 409 for item in responses) == 15, responses
    assert final["available"] == 0, final
    return {"claim": "Exactly 5 of 20 parallel requests succeed", "event_id": event_id, "responses": responses, "final_inventory": final}


def idempotency():
    event_id = fixture()
    key = str(uuid.uuid4())
    payload = {"event_id": event_id, "quantity": 1, "recipient": "student@example.test"}
    barrier = threading.Barrier(2)

    def attempt(index):
        barrier.wait()
        return call("POST", BASE + "/api/v1/bookings", payload, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        simultaneous = list(pool.map(attempt, range(2)))
    repeated = call("POST", BASE + "/api/v1/bookings", payload, key)
    conflict = call("POST", BASE + "/api/v1/bookings", {**payload, "quantity": 2}, key)
    assert all(item["status"] == 201 for item in simultaneous), simultaneous
    assert simultaneous[0]["body"] == simultaneous[1]["body"] == repeated["body"]
    assert repeated["replayed"] == "true"
    assert conflict["status"] == 409, conflict
    booking_id = repeated["body"]["id"]
    payment = call("GET", PAYMENT + f"/api/v1/charges/{booking_id}")
    assert payment["body"]["state"] == "CHARGED", payment
    final = next(event for event in call("GET", INVENTORY + "/api/v1/events")["body"] if event["id"] == event_id)
    assert final["available"] == 4
    return {"claim": "Concurrent and sequential replay produce one booking, hold and charge; changed payload rejected", "event_id": event_id, "key": key, "simultaneous": simultaneous, "repeated": repeated, "conflict": conflict, "payment": payment, "final_inventory": final}


def saga():
    event_id = fixture(1)
    failed = call("POST", BASE + "/api/v1/bookings", {"event_id": event_id, "quantity": 1, "recipient": "student@example.test", "fail_notification": True}, str(uuid.uuid4()))
    assert failed["status"] == 409, failed
    booking_id = failed["body"]["id"]
    history = call("GET", BASE + f"/api/v1/bookings/{booking_id}/transitions")
    payment = call("GET", PAYMENT + f"/api/v1/charges/{booking_id}")
    hold = call("GET", INVENTORY + f"/api/v1/holds/{booking_id}")
    recovered = call("POST", BASE + f"/api/v1/bookings/{booking_id}/recover")
    final = next(event for event in call("GET", INVENTORY + "/api/v1/events")["body"] if event["id"] == event_id)
    assert failed["body"]["state"] == recovered["body"]["state"] == "CANCELLED"
    assert payment["body"]["state"] == "REFUNDED"
    assert hold["body"]["state"] == "RELEASED"
    assert [row["state"] for row in history["body"]] == ["RESERVED", "PAID", "COMPENSATING", "CANCELLED"]
    assert final["available"] == 1
    return {"claim": "Step 3 failure refunds payment and releases inventory; repeated recovery is harmless", "event_id": event_id, "failed": failed, "history": history, "payment": payment, "hold": hold, "recovered": recovered, "final_inventory": final}


def e2e():
    event_id = fixture(1)
    result = call("POST", BASE + "/api/v1/bookings", {"event_id": event_id, "quantity": 1, "recipient": "student@example.test"}, str(uuid.uuid4()))
    assert result["status"] == 201 and result["body"]["state"] == "CONFIRMED", result
    booking_id = result["body"]["id"]
    notification_url = os.environ.get("NOTIFICATION_URL", "http://127.0.0.1:8003")
    delivery = call("GET", notification_url + f"/api/v1/deliveries/{booking_id}")
    assert delivery["body"]["state"] == "DELIVERED", delivery
    return {"claim": "Main transaction completes across all four services", "event_id": event_id, "booking": result, "delivery": delivery}


CHECKS = {"concurrency": (concurrency, "challenge-1-concurrency"), "idempotency": (idempotency, "challenge-2-idempotency"), "saga": (saga, "challenge-3c-saga"), "e2e": (e2e, "tests")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("challenge", choices=[*CHECKS, "all"], default="all", nargs="?")
    arguments = parser.parse_args()
    for name in CHECKS if arguments.challenge == "all" else [arguments.challenge]:
        function, folder = CHECKS[name]
        result = {"timestamp": datetime.now(timezone.utc).isoformat(), "command": f"python scripts/challenges.py {name}", **function()}
        target = ROOT / "evidence" / folder
        target.mkdir(parents=True, exist_ok=True)
        output = json.dumps(result, indent=2)
        (target / "result.json").write_text(output + "\n")
        print(output, flush=True)


if __name__ == "__main__":
    main()