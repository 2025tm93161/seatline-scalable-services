from sqlalchemy import text


class RuleViolation(Exception):
    pass


def reserve(connection, event_id, quantity, reservation_id):
    if quantity < 1:
        raise RuleViolation("Quantity must be positive")
    connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 3))"), {"id": reservation_id})
    cancelled = connection.execute(text("SELECT id FROM released_holds WHERE id = :id"), {"id": reservation_id}).first()
    if cancelled:
        raise RuleViolation("Reservation was already cancelled")
    existing = connection.execute(text("SELECT id FROM holds WHERE id = :id"), {"id": reservation_id}).first()
    if existing:
        raise RuleViolation("Reservation ID already exists; replay with the original key")
    event = connection.execute(
        text("UPDATE events SET available = available - :quantity "
             "WHERE id = :event_id AND available >= :quantity "
             "RETURNING id, price_cents"),
        {"event_id": event_id, "quantity": quantity},
    ).mappings().first()
    if event is None:
        raise RuleViolation("Event unavailable or insufficient seats")
    connection.execute(
        text("INSERT INTO holds (id, event_id, quantity, state) "
             "VALUES (:id, :event_id, :quantity, 'RESERVED')"),
        {"id": reservation_id, "event_id": event_id, "quantity": quantity},
    )
    return {"id": reservation_id, "amount_cents": quantity * event["price_cents"]}


def release(connection, reservation_id):
    connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 3))"), {"id": reservation_id})
    connection.execute(text("INSERT INTO released_holds VALUES (:id) ON CONFLICT DO NOTHING"), {"id": reservation_id})
    hold = connection.execute(
        text("UPDATE holds SET state = 'RELEASED' "
             "WHERE id = :id AND state = 'RESERVED' RETURNING event_id, quantity"),
        {"id": reservation_id},
    ).mappings().first()
    if hold:
        connection.execute(
            text("UPDATE events SET available = available + :quantity WHERE id = :event_id"),
            dict(hold),
        )
    return {"id": reservation_id, "state": "RELEASED"}