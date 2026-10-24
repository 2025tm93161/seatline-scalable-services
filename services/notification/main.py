from fastapi import Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from common.platform import Fault, create_service, idempotent
from services.notification.domain import resolve


app, engine = create_service("notification", [
    "CREATE TABLE IF NOT EXISTS deliveries (booking_id TEXT PRIMARY KEY, recipient TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('DELIVERED', 'FAILED')), reason TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
])


class Delivery(BaseModel):
    booking_id: str = Field(min_length=1, max_length=128)
    recipient: str = Field(min_length=3, max_length=160)


def find(connection, booking_id, lock=False):
    query = "SELECT booking_id, recipient, state, reason, created_at FROM deliveries WHERE booking_id = :id" + (" FOR UPDATE" if lock else "")
    row = connection.execute(text(query), {"id": booking_id}).mappings().first()
    return None if row is None else {**row, "created_at": row["created_at"].isoformat()}


@app.post("/api/v1/deliveries", status_code=201)
def deliver(body: Delivery, request: Request, idempotency_key: str = Header(...)):
    def action(connection):
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 3))"), {"id": body.booking_id})
        existing = find(connection, body.booking_id, lock=True)
        if existing:
            return 200, existing
        state = resolve(None, False)
        connection.execute(text("INSERT INTO deliveries (booking_id, recipient, state) VALUES (:id, :recipient, :state)"), {"id": body.booking_id, "recipient": body.recipient, "state": state})
        return 201, find(connection, body.booking_id)

    return idempotent(engine, request, idempotency_key, body.model_dump(), action)


@app.get("/api/v1/deliveries")
def deliveries():
    with engine.connect() as connection:
        rows = connection.execute(text("SELECT booking_id, recipient, state, reason, created_at FROM deliveries ORDER BY created_at")).mappings()
        return [{**row, "created_at": row["created_at"].isoformat()} for row in rows]


@app.get("/api/v1/deliveries/{booking_id}")
def get_delivery(booking_id: str):
    with engine.connect() as connection:
        delivery = find(connection, booking_id)
    if not delivery:
        raise Fault(404, "NOT_FOUND", "Delivery not found")
    return delivery
