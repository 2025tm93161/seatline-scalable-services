# Seatline submission: SEZG583 Assignment 1

Coordinator: Omkar. Each member edits only their own rows and reflection, in their own commits.

## Links

| Item | Link |
|---|---|
| Repository | https://github.com/2025tm93161/seatline-scalable-services |
| Demo video (8-10 min) | _TODO before submission_ |
| Report | `docs/report.pdf` |

## Team

| Member | BITS ID | Service owned | Distributed-systems concept |
|---|---|---|---|
| Angshuman | 2025TM93161 | Booking (:8000) | Saga orchestration, state machine, recovery |
| Siva Aravindan | _TODO_ | Inventory (:8001) | Challenge 1: concurrency, atomic conditional update |
| Susheel Kumaraswamy S | 2025TM93096 | Payment (:8002) | Challenge 2: idempotency, request fingerprinting |
| Bandgar Omkar Sudhakar Sheetal | 2025TM93075 | Notification (:8003) | Challenge 3C: step-3 failure injection, saga evidence |

## Contribution table

Each member should be able to point to their commits on their feature branch.

| Member | Code | Tests | Evidence and docs | Reviewed |
|---|---|---|---|---|
| Angshuman | `services/booking/`, `scripts/run.py` | `tests/test_e2e.py`, BR5, BR8 | `docs/diagrams.md`, README | Inventory |
| Siva Aravindan | `services/inventory/` | `services/inventory/tests/`, BR1, BR2 | `evidence/challenge-1-concurrency/` | Payment |
| Susheel Kumaraswamy S | `services/payment/`, `common/platform.py` | `tests/test_api_contract.py`, BR3, BR4, BR7 | `evidence/challenge-2-idempotency/` | Notification |
| Omkar | `services/notification/` (mock delivery, failure simulation, BR6 trigger) | BR6 in `tests/test_business_rules.py`, `services/notification/tests/` | `evidence/challenge-3c-saga/`, `docs/openapi/`, this file | Booking |

## Business-rule ownership

| Rule | Owner |
|---|---|
| BR1 no over-allocation, BR2 single release | Siva |
| BR3 decline is not a charge, BR4 single refund effect, BR7 replay/conflict | Susheel |
| BR5 confirmed is terminal | Angshuman |
| BR6 failed notification is never delivered | Omkar |
| BR8 step-3 failure compensates payment and hold | Angshuman + Omkar |

## Individual reflections

Each member writes their own (150-250 words): what you built, one hard problem, what you would change.

### Angshuman
_TODO_

### Siva Aravindan
_TODO_

### Susheel Kumaraswamy S
_TODO_

### Omkar
I built the Notification Service: a mock delivery provider with its own `notification`
database, a `POST /api/v1/deliveries` endpoint protected by an `Idempotency-Key`, and a
`simulate_failure` switch that Booking uses as saga step 3. Because Notification is the
last step, it is the dependency we use to prove compensation: when it fails, Payment
refunds and Inventory releases the hold.

The hard problem was BR6, making a provider failure final. A failure is meaningful to the
saga only if Notification and Booking agree on it. If a retry could later turn a FAILED
delivery into DELIVERED, a customer would be told their booking was confirmed after we had
already refunded them and released their seats. I solved this in three layers. The
domain rule `can_deliver` rejects the transition. The FAILED row is written before the 502
is returned, so the record exists before Booking starts compensating. A PostgreSQL trigger
blocks the transition even for a direct UPDATE. A per-booking advisory lock plus the
shared idempotency layer stop concurrent retries from racing to insert two outcomes.

What I would change: notification is called synchronously over REST, so a slow provider
holds up the booking. In production I would publish a `BookingConfirmed` event through a
transactional outbox and let Notification consume it asynchronously, with bounded retries
and a dead-letter queue, keeping the saga to the steps that truly need to be reversed.

## AI assistance declaration

The README asks the team to declare AI assistance. Each member states, for their own part,
which tools were used and for what, and confirms they can explain every mechanism they submitted.

| Member | Declaration |
|---|---|
| Angshuman | _TODO_ |
| Siva Aravindan | _TODO_ |
| Susheel Kumaraswamy S | _TODO_ |
| Omkar | Claude (Anthropic) assisted with planning the team split, demo speaking points, a pre-submission review of `main`, the Compose health-check/restart change, and drafting my reflection. I designed and wrote the Notification Service, BR6 enforcement and its tests, reviewed every AI-suggested change, and can explain each mechanism. |

## Demo video outline (8-10 minutes)

| Time | Presenter | Content |
|---|---|---|
| 0:00-1:30 | Angshuman | Architecture, database-per-service, REST only, booking state machine |
| 1:30-3:00 | All | `scripts/run.py`, every `/health` and `/docs`, one confirmed booking |
| 3:00-4:30 | Siva | Challenge 1: 20 parallel holds, 5 succeed, 15 rejected, available = 0 |
| 4:30-6:00 | Susheel | Challenge 2: simultaneous same key, replay header, changed payload → 409 |
| 6:00-8:00 | Omkar + Angshuman | Challenge 3C: `fail_notification`, delivery `FAILED`, refund, release, `CANCELLED`, one `X-Request-ID` in all logs |
| 8:00-9:30 | All | Tests run, evidence folders, limitations |

## Pre-submission checklist

- [ ] All four feature branches merged to `main` with each member's own commits
- [ ] `pytest tests services/*/tests` passes against `TEST_DATABASE_URL`
- [ ] `scripts/challenges.py all` run on the final code, results committed under `evidence/`
- [ ] `scripts/export_artifacts.py` run; `docs/openapi/*.json` and database snapshots refreshed
- [ ] `docs/report.pdf` built with `scripts/build_report.py`
- [ ] README followed from a fresh clone by someone other than its author
- [ ] Every TODO in this file replaced; video link added
