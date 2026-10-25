import uuid

import httpx

from scripts.challenges import BASE, INVENTORY, PAYMENT, call, fixture


def test_error_contract_validation_and_correlation():
    response = httpx.post(BASE + "/api/v1/bookings", json={}, headers={"X-Request-ID": "contract-test"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers["X-Request-ID"] == "contract-test"
    missing = call("GET", PAYMENT + "/api/v1/charges/does-not-exist")
    assert missing["status"] == 404
    assert set(missing["body"]["error"]) == {"code", "message"}


def test_late_forward_requests_cannot_reverse_compensation():
    booking_id = str(uuid.uuid4())
    event_id = fixture(1)
    assert call("POST", INVENTORY + f"/api/v1/holds/{booking_id}/release")["status"] == 200
    late_hold = call("POST", INVENTORY + "/api/v1/holds", {"id": booking_id, "event_id": event_id, "quantity": 1}, booking_id)
    assert late_hold["status"] == 409
    assert call("POST", PAYMENT + f"/api/v1/charges/{booking_id}/refund")["body"]["state"] == "CANCELLED"
    late_charge = call("POST", PAYMENT + "/api/v1/charges", {"booking_id": booking_id, "amount_cents": 2500}, booking_id)
    assert late_charge["status"] == 409
    final = next(event for event in call("GET", INVENTORY + "/api/v1/events")["body"] if event["id"] == event_id)
    assert final["available"] == 1


def test_declined_payment_releases_capacity():
    event_id = fixture(1)
    result = call("POST", BASE + "/api/v1/bookings", {"event_id": event_id, "quantity": 1, "recipient": "student@example.test", "decline_payment": True}, str(uuid.uuid4()))
    assert result["status"] == 409
    assert result["body"]["state"] == "CANCELLED"
    assert result["body"]["error"]["code"] == "BOOKING_CANCELLED"
    final = next(event for event in call("GET", INVENTORY + "/api/v1/events")["body"] if event["id"] == event_id)
    assert final["available"] == 1