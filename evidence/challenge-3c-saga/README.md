# Challenge 3C: orchestrated saga with compensation

**Claim:** when step 3 (notification) fails after seats are held (step 1) and payment is
charged (step 2), Booking compensates both earlier steps. The customer is never left with a
charge for seats they did not get, or with seats held for a cancelled booking.

Ownership: failure injection and evidence by Notification (Omkar); orchestration and
compensation by Booking (Angshuman).

## How the failure is forced

1. The client sends `"fail_notification": true` on `POST /api/v1/bookings`.
2. Booking forwards it as `"simulate_failure": true` to `POST /api/v1/deliveries`.
3. Notification persists the delivery as `FAILED` and answers
   `502 NOTIFICATION_PROVIDER_FAILURE`.
4. Booking's `remote()` raises a `Fault`, and `run_saga` moves the booking to `COMPENSATING`.
5. Booking calls `POST /api/v1/charges/{id}/refund` and then `POST /api/v1/holds/{id}/release`,
   and finishes in `CANCELLED`. If either compensator is unreachable, the booking stays in
   `COMPENSATION_PENDING` until `POST /api/v1/bookings/{id}/recover` is called.

Notification records the failure before replying, and BR6 makes `FAILED` final. A retry or a
late request therefore cannot report the confirmation as sent after the booking was cancelled.

## Reproduce

With all four services running (`python scripts/run.py`):

```sh
python scripts/challenges.py saga
python scripts/export_artifacts.py
```

## Files in this folder

| File | Produced by | Shows |
|---|---|---|
| `result.json` | `challenges.py saga` | Failed create response, transition history, payment, hold, recovery, final capacity |
| `database-state.json` | `export_artifacts.py` | Rows in each service's own database for the fixture booking |
| `service-logs.txt` | `export_artifacts.py` | Structured logs from all services sharing one `X-Request-ID` |

## What a passing run must show

| Check | Expected value | Service and database |
|---|---|---|
| Create booking response | `409`, state `CANCELLED`, error `BOOKING_CANCELLED` | Booking |
| Transition history | `RESERVED → PAID → COMPENSATING → CANCELLED` | Booking |
| Delivery | `FAILED`, reason "Simulated notification provider failure" | Notification |
| Charge | `REFUNDED` | Payment |
| Hold | `RELEASED` | Inventory |
| Event `available` | back to capacity (`1`) | Inventory |
| `POST /recover` repeated | still `CANCELLED`, no second refund or release | Booking |
| Logs | one `X-Request-ID` across booking, inventory, payment and notification, including a `notification_failed` event | all |
