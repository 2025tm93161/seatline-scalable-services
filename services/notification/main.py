import json

from fastapi import Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from common.platform import ErrorResponse, Fault, create_service, error, idempotent, logger
from services.notification.domain import FAILED, resolve


app, engine = create_service("notification", [
    "CREATE TABLE IF NOT EXISTS deliveries (booking_id TEXT PRIMARY KEY, recipient TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('DELIVERED', 'FAILED')), reason TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    # BR6 defence in depth: even a direct UPDATE cannot turn a FAILED delivery into DELIVERED.
    "CREATE OR REPLACE FUNCTION deliveries_failed_is_final() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF OLD.state = 'FAILED' AND NEW.state <> 'FAILED' THEN RAISE EXCEPTION 'BR6 violation - failed notification for booking % cannot become %', OLD.booking_id, NEW.state; END IF; RETURN NEW; END $$",
    "CREATE OR REPLACE TRIGGER deliveries_failed_is_final BEFORE UPDATE ON deliveries FOR EACH ROW EXECUTE FUNCTION deliveries_failed_is_final()",
])
PROVIDER_FAILURE = "Simulated notification provider failure"


class Delivery(BaseModel):
    booking_id: str = Field(min_length=1, max_length=128)
    recipient: str = Field(min_length=3, max_length=160)
    simulate_failure: bool = False


def find(connection, booking_id, lock=False):
    query = "SELECT booking_id, recipient, state, reason, created_at FROM deliveries WHERE booking_id = :id" + (" FOR UPDATE" if lock else "")
    row = connection.execute(text(query), {"id": booking_id}).mappings().first()
    return None if row is None else {**row, "created_at": row["created_at"].isoformat()}


@app.post("/api/v1/deliveries", status_code=201, responses={200: {"description": "Delivery already recorded for this booking"}, 502: {"model": ErrorResponse, "description": "Mock provider failed; the FAILED delivery is persisted"}})
def deliver(body: Delivery, request: Request, idempotency_key: str = Header(...)):
    def action(connection):
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 3))"), {"id": body.booking_id})
        existing = find(connection, body.booking_id, lock=True)
        if existing:
            try:
                resolve(existing["state"], body.simulate_failure)
            except ValueError:
                raise Fault(409, "NOTIFICATION_FAILED", "Delivery already failed for this booking and cannot be marked delivered")
            return 200, existing
        state = resolve(None, body.simulate_failure)
        reason = PROVIDER_FAILURE if state == FAILED else ""
        connection.execute(text("INSERT INTO deliveries (booking_id, recipient, state, reason) VALUES (:id, :recipient, :state, :reason)"), {"id": body.booking_id, "recipient": body.recipient, "state": state, "reason": reason})
        if state == FAILED:
            # Recorded first, then reported upstream: Booking treats this 502 as saga step 3 failing.
            logger.info(json.dumps({"event": "notification_failed", "service": "notification", "request_id": request.state.correlation_id, "booking_id": body.booking_id}))
            return 502, error("NOTIFICATION_PROVIDER_FAILURE", PROVIDER_FAILURE)
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
