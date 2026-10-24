# Seatline: concurrent event reservations

SEZG583 Assignment 1. Four Python/FastAPI services, PostgreSQL database-per-service,
a small JavaScript operator console, and pytest. Chosen optional challenge:
**3C, orchestrated saga with compensation**. All payments and notifications are mocks.

## Quick start (macOS/Linux)

Prerequisites: Python 3.9+, Docker with a running daemon, and ports 8000-8003 / 55432.
On this development machine, `colima start` starts Docker. Run commands from the repository root.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
docker compose up -d postgres
.venv/bin/python scripts/run.py
```

The database image initializes four databases and four separate logins on its **first** start.
Wait for PostgreSQL to report healthy (`docker compose ps`) before running the launcher.
Open **http://127.0.0.1:8000**. The launcher reports readiness, writes logs per service,
and stops all four child processes on Ctrl+C. Do not run two launchers on the same ports.
The console is optional; every assessment flow works through HTTP scripts.

This workspace currently uses a manually started `scalable-postgres` container with the
same databases on port 55432. It is already initialized. To use Compose instead, stop
that container first (`docker stop scalable-postgres`); do not delete databases to rerun tests.

## Independently run a service

Each service has its own dependency file and example environment. Shared `common/`
contains only transport/database plumbing, not business rules or cross-database access.
Each process loads only its own service module. From the root, in a separate terminal:

```sh
python3 -m venv .venv-inventory
.venv-inventory/bin/python -m pip install -r services/inventory/requirements.txt
set -a
. services/inventory/.env.example
set +a
.venv-inventory/bin/python -m uvicorn services.inventory.main:app --host "$HOST" --port "$PORT"
```

Replace `inventory` with `payment`, `notification`, or `booking` for the other services.
Each can run without the other processes; its `/health` needs only its own database.
The example credentials are **local development credentials**, not production secrets.
There is no authentication, as requested by the assignment. Do not expose these ports publicly.

| Service | Port | Database / login | Responsibility |
|---|---|---|---|
| Booking | 8000 | booking / booking_user | Booking lifecycle, saga orchestration, durable recovery |
| Inventory | 8001 | inventory / inventory_user | Capacity, atomic holds, idempotent release |
| Payment | 8002 | payment / payment_user | Mock charges, declines, refund/cancellation fences |
| Notification | 8003 | notification / notification_user | Mock delivery and provider failure |

All services expose `/health`, `/docs`, and `/openapi.json`.
Business endpoints use `/api/v1/...`. Config is read from environment variables:

| Configuration | Meaning |
|---|---|
| DATABASE_URL | Required per-service PostgreSQL URL; no fallback in service code |
| HOST, PORT | Bind address and port passed to Uvicorn |
| INVENTORY_URL, PAYMENT_URL, NOTIFICATION_URL | Required by Booking |
| HTTP_TIMEOUT_SECONDS | Booking outbound request timeout, default 3 seconds |
| FRONTEND_DIR | Static console path, default `frontend` |
| DB_PORT | Local launcher/export database port, default 55432 |
| BOOKING_PORT, INVENTORY_PORT, PAYMENT_PORT, NOTIFICATION_PORT | Launcher port overrides |
| BOOKING_DATABASE_URL, INVENTORY_DATABASE_URL, PAYMENT_DATABASE_URL, NOTIFICATION_DATABASE_URL | Launcher/export per-database overrides |
| BOOKING_URL, INVENTORY_URL, PAYMENT_URL, NOTIFICATION_URL | Script service URL overrides |
| TEST_DATABASE_URL | Dedicated PostgreSQL test database; see below |

The launcher supplies documented local defaults. `.env.example` files are sourced explicitly;
there is no implicit dotenv loading. Currency amounts are integer minor units (the console displays INR).

## Test and reproduce evidence

With all four services running, use a second terminal. The inventory tests create uniquely
named fixtures and must use a **test** database, not an application database.

```sh
# Create once; use a dedicated non-production PostgreSQL instance.
docker exec scalable-postgres createdb -U postgres seatline_test
export TEST_DATABASE_URL=postgresql+psycopg://postgres:local-admin-only@localhost:55432/seatline_test
.venv/bin/python -m pytest tests services/inventory/tests -v
.venv/bin/python scripts/challenges.py all
.venv/bin/python scripts/export_artifacts.py
.venv/bin/python scripts/build_report.py
```

For a Compose database, replace `docker exec scalable-postgres` with `docker compose exec -T postgres`.
The superuser is used only to provision/test locally, **never by application processes**.
Unit-only checks: `.venv/bin/python -m pytest tests/test_business_rules.py -v`.
Individual scripts: `scripts/challenges.py concurrency`, `idempotency`, `saga`, or `e2e`.
Each script asserts outcomes and writes timestamped JSON under `evidence/`.
Direct SQL in the offline exporter is an assessment tool, not service communication.
Fixtures accumulate deliberately; tests do not truncate existing application data.

## Main API examples

```sh
curl -i http://127.0.0.1:8000/api/v1/bookings \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-booking-001' \
  -H 'X-Request-ID: demo-request-001' \
  -d '{"event_id":"jazz-night","quantity":1,"recipient":"student@example.test"}'
```

Repeat with the same key for an exact status/body replay (including simultaneous requests).
Change quantity with that key for `409 IDEMPOTENCY_CONFLICT`.
Use a **new key** and `"fail_notification":true` to force the saga's third step to fail.
Expected state: `CANCELLED`; charge: `REFUNDED`; hold: `RELEASED`.
Use `"decline_payment":true` to demonstrate mock decline, or `"payment_delay_ms":4000`
to exceed the default timeout. A failed compensation remains `COMPENSATION_PENDING`.
Restore the dependency and `POST /api/v1/bookings/{id}/recover` to finish recovery.
The original create response remains immutable; GET the booking for its current state.

## Business rules and traceability

| Rule | Enforcement | Test |
|---|---|---|
| BR1: no over-allocation | Inventory `domain.reserve`: atomic conditional UPDATE + DB CHECK | `test_br1_twenty_requests_cannot_overallocate`; HTTP concurrency script |
| BR2: releases restore capacity once; late reservations cannot resurrect a cancellation | Inventory `domain.release`, cancellation tombstone + advisory lock | `test_br2_release_is_idempotent`, `test_br2_release_before_late_reservation_prevents_leak` |
| BR3: declined payment is not charged | Payment `domain.charge_state` | `test_br3_payment_decline_is_not_charge` |
| BR4: repeated refunds have one final effect | Payment `domain.refund_state`, per-booking transaction lock | `test_br4_refund_can_be_repeated` |
| BR5: confirmed bookings are terminal | Booking `domain.assert_transition` | `test_br5_confirmed_booking_is_terminal` |
| BR6: provider failure cannot be recorded as delivered | Notification `domain.can_deliver` | `test_br6_failed_notification_is_not_delivered` |
| BR7: same unsafe request/key replays; changed payload conflicts | `common.platform.idempotent`, persisted fingerprint and response | `test_br7_simultaneous_idempotency_and_conflict` |
| BR8: step-three failure reverses the charge and hold | Booking `run_saga` + local compensators | `test_br8_step_three_failure_compensates` |

BR7/BR8 are distributed contracts exercised by integration tests rather than artificial isolated mocks.
Local rules BR1-BR6 have direct focused domain tests.

## Repository and submission

- `services/`: independently runnable business services and per-service configuration.
- `frontend/`: optional framework-free JavaScript console. Fonts and event photos use Google Fonts/Unsplash; offline use affects visuals only.
- `scripts/`: launcher, main flow/challenges, artifact export, PDF generation.
- `docs/report.md`, `docs/report.pdf`: technical report and generated PDF.
- `docs/diagrams.md`: editable architecture, sequences, state machine, ER diagrams.
- `docs/openapi/`: exported specs for each service.
- `docs/submission.md`: team/contribution/reflection/AI declaration and video outline.
- `evidence/`: actual outputs, database snapshots, logs and test reports.

Container preparation for Assignment 2: `docker compose up --build` runs all services.
Stop the local launcher first and ensure the database port is free. Compose packaging is
included; Minikube manifests/deployment are intentionally deferred to Assignment 2.
Normal `docker compose down` preserves the database volume. Never use `down -v` unless
you deliberately want to erase that local data.

Read the report's limitations: manual recovery, bounded connection pools, no automatic hold
expiry, no production migrations, no durable queue, and notification side effects are not undoable.
Create a real GitHub repository, replace submission placeholders, record the 8-10 minute demo,
and add honest individual contributions/reflections before submission. No commit history or
video link has been fabricated. Declare AI assistance and be able to explain every mechanism.