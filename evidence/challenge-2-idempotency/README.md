# Challenge 2: Idempotency

Run: `.venv/bin/python scripts/challenges.py idempotency`, then export artifacts.

- [result.json](result.json): two barrier-synchronized identical bookings, sequential replay, changed-payload 409, one charge and one consumed seat.
- [database-state.json](database-state.json): one booking, hold and payment; idempotency row includes SHA-256 fingerprint, HTTP status and serialized response.
- [service-logs.txt](service-logs.txt): `idempotency_replay` records and request IDs. Captured log set includes neighboring challenges.

PostgreSQL transaction advisory locks serialize identical endpoint/key pairs across
processes. A deterministic booking ID and durable saga checkpoints allow restart
without a second business entity. The original response is immutable; inspect GET
for current state after explicit recovery. Keys are not expired in this demo.