import pytest
import httpx

from scripts.challenges import concurrency, e2e, idempotency, saga


SERVICES = {
    "booking": "http://127.0.0.1:8000",
    "inventory": "http://127.0.0.1:8001",
    "payment": "http://127.0.0.1:8002",
    "notification": "http://127.0.0.1:8003",
}


@pytest.fixture(scope="module", autouse=True)
def verify_services_are_running():
    unavailable = []

    for name, url in SERVICES.items():
        try:
            response = httpx.get(f"{url}/health", timeout=2)
            response.raise_for_status()
        except httpx.HTTPError:
            unavailable.append(name)

    if unavailable:
        pytest.fail(
            "E2E prerequisites not available. Start all services using "
            "`python scripts/run.py`. "
            f"Unavailable services: {', '.join(unavailable)}"
        )


def test_successful_booking_transaction_end_to_end():
    e2e()


def test_br1_concurrent_requests_never_overallocate_capacity():
    concurrency()


def test_br7_duplicate_requests_are_idempotent_and_conflicts_are_rejected():
    idempotency()


def test_br8_notification_failure_triggers_saga_compensation():
    saga()
