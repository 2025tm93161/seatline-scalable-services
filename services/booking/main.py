import json
import os
import uuid

import httpx
from fastapi import Header, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from common.platform import Fault, create_service, idempotent
from services.booking.domain import assert_transition


app, engine = create_service("booking", [
    "CREATE TABLE IF NOT EXISTS bookings (id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL, amount_cents INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE IF NOT EXISTS transitions (sequence BIGSERIAL PRIMARY KEY, booking_id TEXT NOT NULL REFERENCES bookings(id), state TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
])
URLS = {name: os.environ[f"{name.upper()}_URL"] for name in ("inventory", "payment", "notification")}
TIMEOUT = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "3"))


class Booking(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(ge=1, le=10)
    recipient: str = Field(min_length=3, max_length=160)
    decline_payment: bool = False
    fail_notification: bool = False
    payment_delay_ms: int = Field(default=0, ge=0, le=5000)


def remote(service, method, path, request_id, key=None, payload=None):
    headers = {"X-Request-ID": request_id}
    if key:
        headers["Idempotency-Key"] = key
    try:
        response = httpx.request(method, URLS[service] + "/api/v1" + path, json=payload, headers=headers, timeout=TIMEOUT)
    except httpx.RequestError as exception:
        raise Fault(503, "DEPENDENCY_UNAVAILABLE", f"{service}: {type(exception).__name__}")
    if response.is_error:
        detail = response.json().get("error", {})
        raise Fault(response.status_code, detail.get("code", "DEPENDENCY_ERROR"), detail.get("message", service))
    return response.json()


def fetch(booking_id):
    with engine.connect() as connection:
        row = connection.execute(text("SELECT id, state, amount_cents, reason FROM bookings WHERE id = :id"), {"id": booking_id}).mappings().first()
        if not row:
            raise Fault(404, "NOT_FOUND", "Booking not found")
        return dict(row)


def transition(booking_id, target, amount=None, reason=""):
    with engine.begin() as connection:
        current = connection.execute(text("SELECT state FROM bookings WHERE id = :id FOR UPDATE"), {"id": booking_id}).scalar_one()
        assert_transition(current, target)
        connection.execute(text("UPDATE bookings SET state = :state, amount_cents = COALESCE(:amount, amount_cents), reason = :reason WHERE id = :id"), {"id": booking_id, "state": target, "amount": amount, "reason": reason})
        connection.execute(text("INSERT INTO transitions (booking_id, state) VALUES (:id, :state)"), {"id": booking_id, "state": target})


def run_saga(booking_id, payload, request_id):
    with engine.begin() as lock:
        lock.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 2))"), {"id": booking_id})
        state = fetch(booking_id)["state"]
        if state in ("CONFIRMED", "CANCELLED"):
            return fetch(booking_id)
        if state == "COMPENSATION_PENDING":
            transition(booking_id, "COMPENSATING", reason="Recovery requested")
            state = "COMPENSATING"
        if state != "COMPENSATING":
            try:
                if state == "PENDING":
                    hold = remote("inventory", "POST", "/holds", request_id, booking_id, {"id": booking_id, "event_id": payload["event_id"], "quantity": payload["quantity"]})
                    transition(booking_id, "RESERVED", amount=hold["amount_cents"])
                    state = "RESERVED"
                if state == "RESERVED":
                    payment = remote("payment", "POST", "/charges", request_id, booking_id, {"booking_id": booking_id, "amount_cents": fetch(booking_id)["amount_cents"], "decline": payload["decline_payment"], "delay_ms": payload["payment_delay_ms"]})
                    if payment["state"] != "CHARGED":
                        raise Fault(402, "PAYMENT_DECLINED", "Mock payment declined")
                    transition(booking_id, "PAID")
                remote("notification", "POST", "/deliveries", request_id, booking_id, {"booking_id": booking_id, "recipient": payload["recipient"], "simulate_failure": payload["fail_notification"]})
                transition(booking_id, "CONFIRMED")
                return fetch(booking_id)
            except Fault as exception:
                transition(booking_id, "COMPENSATING", reason=exception.message)
        try:
            remote("payment", "POST", f"/charges/{booking_id}/refund", request_id)
            remote("inventory", "POST", f"/holds/{booking_id}/release", request_id)
            transition(booking_id, "CANCELLED", reason="Saga compensated; payment reversed and seats released")
        except Fault as exception:
            transition(booking_id, "COMPENSATION_PENDING", reason=exception.message)
        return fetch(booking_id)


@app.get("/api/v1/events")
def events(request: Request):
    return remote("inventory", "GET", "/events", request.state.correlation_id)


@app.get("/api/v1/bookings")
def bookings():
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text("SELECT id, state, amount_cents, reason FROM bookings ORDER BY id")).mappings()]


@app.post("/api/v1/bookings", status_code=201)
def create_booking(body: Booking, request: Request, idempotency_key: str = Header(...)):
    payload = body.model_dump()
    booking_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "seatline:" + idempotency_key))

    def action(connection):
        with engine.begin() as durable:
            durable.execute(text("INSERT INTO bookings (id, payload, state) VALUES (:id, :payload, 'PENDING') ON CONFLICT DO NOTHING"), {"id": booking_id, "payload": json.dumps(payload)})
            original = durable.execute(text("SELECT payload FROM bookings WHERE id = :id"), {"id": booking_id}).scalar_one()
            if json.loads(original) != payload:
                raise Fault(409, "IDEMPOTENCY_CONFLICT", "Key already belongs to a different booking payload")
        result = run_saga(booking_id, payload, request.state.correlation_id)
        if result["state"] == "CANCELLED":
            result["error"] = {"code": "BOOKING_CANCELLED", "message": result["reason"]}
        return (201 if result["state"] == "CONFIRMED" else 202 if result["state"] == "COMPENSATION_PENDING" else 409), result

    return idempotent(engine, request, idempotency_key, payload, action)


@app.get("/api/v1/bookings/{booking_id}")
def get_booking(booking_id: str):
    return fetch(booking_id)


@app.get("/api/v1/bookings/{booking_id}/transitions")
def history(booking_id: str):
    fetch(booking_id)
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text("SELECT state, created_at FROM transitions WHERE booking_id = :id ORDER BY sequence"), {"id": booking_id}).mappings()]


@app.post("/api/v1/bookings/{booking_id}/recover")
def recover(booking_id: str, request: Request):
    fetch(booking_id)
    with engine.connect() as connection:
        payload = json.loads(connection.execute(text("SELECT payload FROM bookings WHERE id = :id"), {"id": booking_id}).scalar_one())
    return run_saga(booking_id, payload, request.state.correlation_id)


app.mount("/", StaticFiles(directory=os.environ.get("FRONTEND_DIR", "frontend"), html=True), name="console")