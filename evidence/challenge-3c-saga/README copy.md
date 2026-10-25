# Challenge 3C: Saga With Compensation

Run: `.venv/bin/python scripts/challenges.py saga`, then export artifacts.

- [result.json](result.json): forced notification failure after reservation and charge; transition history, REFUNDED, RELEASED, restored capacity, harmless repeated recovery.
- [database-state.json](database-state.json): independent databases show CANCELLED booking, REFUNDED payment, RELEASED hold, full capacity and no successful notification.
- [service-logs.txt](service-logs.txt): HTTP 503 from mock provider and subsequent compensation calls with the request ID.

Refund and release are idempotent and persist cancellation fences for late requests.
If compensation cannot contact a service, state remains COMPENSATION_PENDING and an
operator must invoke recovery after restoring it. A notification cannot be unsent;
the guarantee concerns inventory and mock money, not reversal of communications.