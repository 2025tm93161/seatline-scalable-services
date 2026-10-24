"""Database-backed BR6 tests for the Notification service API.

Requires TEST_DATABASE_URL pointing at a dedicated, non-production PostgreSQL test database
(see README). Booking ids are unique per run, so existing rows are never truncated.
"""
import os
import threading
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")


@pytest.fixture(scope="module")
def client():
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    from fastapi.testclient import TestClient
    from services.notification.main import app

    with TestClient(app) as test_client:
        yield test_client


def deliver(client, booking_id, key=None, simulate_failure=False, recipient="student@example.test"):
    return client.post(
        "/api/v1/deliveries",
        json={"booking_id": booking_id, "recipient": recipient, "simulate_failure": simulate_failure},
        headers={"Idempotency-Key": key or str(uuid.uuid4()), "X-Request-ID": "test-" + booking_id},
    )


def new_booking():
    return "test-" + str(uuid.uuid4())


def test_health_uses_own_database(client):
    assert client.get("/health").json() == {"service": "notification", "status": "ok"}


def test_successful_delivery_is_recorded(client):
    booking_id = new_booking()
    response = deliver(client, booking_id, key=booking_id)
    assert response.status_code == 201
    assert response.json()["state"] == "DELIVERED"
    assert client.get(f"/api/v1/deliveries/{booking_id}").json()["state"] == "DELIVERED"


def test_simulated_failure_is_persisted_and_reported_upstream(client):
    booking_id = new_booking()
    response = deliver(client, booking_id, key=booking_id, simulate_failure=True)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "NOTIFICATION_PROVIDER_FAILURE"
    stored = client.get(f"/api/v1/deliveries/{booking_id}").json()
    assert stored["state"] == "FAILED"
    assert stored["reason"]


def test_br6_failed_delivery_cannot_later_be_delivered(client):
    booking_id = new_booking()
    deliver(client, booking_id, key=booking_id, simulate_failure=True)
    retry = deliver(client, booking_id, key="different-" + booking_id)
    assert retry.status_code == 409
    assert retry.json()["error"]["code"] == "NOTIFICATION_FAILED"
    assert client.get(f"/api/v1/deliveries/{booking_id}").json()["state"] == "FAILED"


def test_br6_database_rejects_direct_update_of_failed_delivery(client):
    booking_id = new_booking()
    deliver(client, booking_id, key=booking_id, simulate_failure=True)
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with pytest.raises(DBAPIError, match="BR6"):
            with engine.begin() as connection:
                connection.execute(text("UPDATE deliveries SET state = 'DELIVERED' WHERE booking_id = :id"), {"id": booking_id})
    finally:
        engine.dispose()
    assert client.get(f"/api/v1/deliveries/{booking_id}").json()["state"] == "FAILED"


def test_same_key_replays_failure_without_second_attempt(client):
    booking_id = new_booking()
    first = deliver(client, booking_id, key=booking_id, simulate_failure=True)
    second = deliver(client, booking_id, key=booking_id, simulate_failure=True)
    assert first.status_code == second.status_code == 502
    assert first.json() == second.json()
    assert second.headers["Idempotency-Replayed"] == "true"


def test_same_key_with_changed_payload_conflicts(client):
    booking_id = new_booking()
    deliver(client, booking_id, key=booking_id)
    conflict = deliver(client, booking_id, key=booking_id, recipient="other@example.test")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_concurrent_requests_for_one_booking_record_one_delivery(client):
    booking_id = new_booking()
    barrier = threading.Barrier(10)
    statuses = []

    def attempt(index):
        barrier.wait()
        # Different keys on purpose: the per-booking lock, not idempotency, must keep this to one row.
        statuses.append(deliver(client, booking_id, key=f"{booking_id}-{index}").status_code)

    threads = [threading.Thread(target=attempt, args=(index,)) for index in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(statuses) == [200] * 9 + [201]
    rows = [row for row in client.get("/api/v1/deliveries").json() if row["booking_id"] == booking_id]
    assert len(rows) == 1
