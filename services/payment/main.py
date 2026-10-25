import time

from fastapi import Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from common.platform import Fault, create_service, idempotent
from services.payment.domain import charge_state, refund_state


app, engine = create_service("payment", [
    "CREATE TABLE IF NOT EXISTS payments (booking_id TEXT PRIMARY KEY, amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0), state TEXT NOT NULL CHECK (state IN ('CHARGED', 'DECLINED', 'REFUNDED', 'CANCELLED')))",
])


class Charge(BaseModel):
    booking_id: str = Field(min_length=1, max_length=128)
    amount_cents: int = Field(ge=1, le=10000000)
    decline: bool = False
    delay_ms: int = Field(default=0, ge=0, le=5000)


@app.post("/api/v1/charges", status_code=201)
def charge(body: Charge, request: Request, idempotency_key: str = Header(...)):
    def action(connection):
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 1))"), {"id": body.booking_id})
        time.sleep(body.delay_ms / 1000)
        state = charge_state(body.decline)
        row = connection.execute(text("INSERT INTO payments VALUES (:booking_id, :amount_cents, :state) ON CONFLICT DO NOTHING RETURNING *"), {**body.model_dump(), "state": state}).mappings().first()
        if row is None:
            raise Fault(409, "PAYMENT_EXISTS", "Payment already exists or was cancelled")
        return 201, dict(row)
    return idempotent(engine, request, idempotency_key, body.model_dump(), action)


@app.post("/api/v1/charges/{booking_id}/refund")
def refund(booking_id: str):
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 1))"), {"id": booking_id})
        row = connection.execute(text("SELECT state FROM payments WHERE booking_id = :id FOR UPDATE"), {"id": booking_id}).first()
        state = refund_state(row[0] if row else "MISSING")
        connection.execute(text("INSERT INTO payments VALUES (:id, 0, :state) ON CONFLICT (booking_id) DO UPDATE SET state = :state"), {"id": booking_id, "state": state})
        return {"booking_id": booking_id, "state": state}


@app.get("/api/v1/charges/{booking_id}")
def get_charge(booking_id: str):
    with engine.connect() as connection:
        row = connection.execute(text("SELECT * FROM payments WHERE booking_id = :id"), {"id": booking_id}).mappings().first()
        if not row:
            raise Fault(404, "NOT_FOUND", "Payment not found")
        return dict(row)