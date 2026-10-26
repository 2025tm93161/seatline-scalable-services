import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text

from services.inventory.domain import RuleViolation, release, reserve


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set",
)


@pytest.fixture
def database():
    engine = create_engine(TEST_DATABASE_URL)

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS released_holds (
                id TEXT PRIMARY KEY
            )
        """))

        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                capacity INTEGER NOT NULL,
                available INTEGER NOT NULL
                    CHECK (available >= 0 AND available <= capacity),
                price_cents INTEGER NOT NULL
            )
        """))

        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS holds (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL REFERENCES events(id),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                state TEXT NOT NULL
                    CHECK (state IN ('RESERVED', 'RELEASED'))
            )
        """))

    yield engine

    engine.dispose()


def create_test_event(engine, capacity=5):
    event_id = f"test-event-{uuid.uuid4()}"

    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO events
                    (id, name, capacity, available, price_cents)
                VALUES
                    (:id, 'Concurrency Test Event',
                     :capacity, :capacity, 1000)
            """),
            {
                "id": event_id,
                "capacity": capacity,
            },
        )

    return event_id


def test_br1_twenty_requests_cannot_overallocate(database):
    event_id = create_test_event(database, capacity=5)

    barrier = threading.Barrier(20)

    def attempt_reservation(index):
        reservation_id = f"br1-{uuid.uuid4()}-{index}"

        barrier.wait()

        try:
            with database.begin() as connection:
                reserve(
                    connection,
                    event_id,
                    1,
                    reservation_id,
                )
            return True
        except RuleViolation:
            return False

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(attempt_reservation, range(20)))

    assert results.count(True) == 5
    assert results.count(False) == 15

    with database.connect() as connection:
        available = connection.execute(
            text("""
                SELECT available
                FROM events
                WHERE id = :id
            """),
            {"id": event_id},
        ).scalar_one()

        reserved_count = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM holds
                WHERE event_id = :event_id
                  AND state = 'RESERVED'
            """),
            {"event_id": event_id},
        ).scalar_one()

    assert available == 0
    assert reserved_count == 5


def test_br2_release_is_idempotent(database):
    event_id = create_test_event(database, capacity=5)
    reservation_id = f"br2-{uuid.uuid4()}"

    with database.begin() as connection:
        reserve(
            connection,
            event_id,
            2,
            reservation_id,
        )

    with database.connect() as connection:
        available_after_reserve = connection.execute(
            text("""
                SELECT available
                FROM events
                WHERE id = :id
            """),
            {"id": event_id},
        ).scalar_one()

    assert available_after_reserve == 3

    with database.begin() as connection:
        first_release = release(
            connection,
            reservation_id,
        )

    with database.begin() as connection:
        second_release = release(
            connection,
            reservation_id,
        )

    assert first_release == {
        "id": reservation_id,
        "state": "RELEASED",
    }

    assert second_release == {
        "id": reservation_id,
        "state": "RELEASED",
    }

    with database.connect() as connection:
        available = connection.execute(
            text("""
                SELECT available
                FROM events
                WHERE id = :id
            """),
            {"id": event_id},
        ).scalar_one()

        hold_state = connection.execute(
            text("""
                SELECT state
                FROM holds
                WHERE id = :id
            """),
            {"id": reservation_id},
        ).scalar_one()

    assert available == 5
    assert hold_state == "RELEASED"


def test_br2_release_before_late_reservation_prevents_leak(database):
    event_id = create_test_event(database, capacity=5)
    reservation_id = f"br2-late-{uuid.uuid4()}"

    with database.begin() as connection:
        release(
            connection,
            reservation_id,
        )

    with pytest.raises(
        RuleViolation,
        match="Reservation was already cancelled",
    ):
        with database.begin() as connection:
            reserve(
                connection,
                event_id,
                1,
                reservation_id,
            )

    with database.connect() as connection:
        available = connection.execute(
            text("""
                SELECT available
                FROM events
                WHERE id = :id
            """),
            {"id": event_id},
        ).scalar_one()

        hold_count = connection.execute(
            text("""
                SELECT COUNT(*)
                FROM holds
                WHERE id = :id
            """),
            {"id": reservation_id},
        ).scalar_one()

    assert available == 5
    assert hold_count == 0
