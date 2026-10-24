from fastapi import Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from common.platform import Fault, create_service, idempotent
from services.inventory.domain import RuleViolation, release, reserve


app, engine = create_service("inventory", [
    "CREATE TABLE IF NOT EXISTS released_holds (id TEXT PRIMARY KEY)",
    "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, name TEXT NOT NULL, capacity INTEGER NOT NULL, available INTEGER NOT NULL CHECK (available >= 0 AND available <= capacity), price_cents INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS holds (id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id), quantity INTEGER NOT NULL CHECK (quantity > 0), state TEXT NOT NULL CHECK (state IN ('RESERVED', 'RELEASED')))",
    "INSERT INTO events VALUES ('jazz-night', 'Rooftop Jazz Session', 40, 40, 2500) ON CONFLICT DO NOTHING",
    "INSERT INTO events VALUES ('design-forum', 'Independent Design Forum', 24, 24, 1800) ON CONFLICT DO NOTHING",
])


class Hold(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(ge=1, le=10)


class Event(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    capacity: int = Field(ge=1, le=10000)
    price_cents: int = Field(ge=1, le=1000000)


@app.get("/api/v1/events")
def events():
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text("SELECT * FROM events ORDER BY id")).mappings()]


@app.post("/api/v1/events", status_code=201)
def create_event(body: Event, request: Request, idempotency_key: str = Header(...)):
    def action(connection):
        result = connection.execute(text("INSERT INTO events VALUES (:id, :name, :capacity, :capacity, :price_cents) ON CONFLICT DO NOTHING RETURNING id"), body.model_dump()).first()
        if result is None:
            raise Fault(409, "EVENT_EXISTS", "Event ID already exists")
        return 201, body.model_dump()
    return idempotent(engine, request, idempotency_key, body.model_dump(), action)


@app.post("/api/v1/holds", status_code=201)
def create_hold(body: Hold, request: Request, idempotency_key: str = Header(...)):
    def action(connection):
        try:
            result = reserve(connection, body.event_id, body.quantity, body.id)
        except RuleViolation as exception:
            raise Fault(409, "INSUFFICIENT_CAPACITY", str(exception))
        return 201, result
    return idempotent(engine, request, idempotency_key, body.model_dump(), action)


@app.post("/api/v1/holds/{hold_id}/release")
def release_hold(hold_id: str):
    with engine.begin() as connection:
        return release(connection, hold_id)


@app.get("/api/v1/holds/{hold_id}")
def get_hold(hold_id: str):
    with engine.connect() as connection:
        row = connection.execute(text("SELECT * FROM holds WHERE id = :id"), {"id": hold_id}).mappings().first()
        if not row:
            raise Fault(404, "NOT_FOUND", "Hold not found")
        return dict(row)