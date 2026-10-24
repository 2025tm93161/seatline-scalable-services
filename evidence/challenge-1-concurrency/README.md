# Challenge 1: Concurrency

Run: `.venv/bin/python scripts/challenges.py concurrency`, then
`.venv/bin/python scripts/export_artifacts.py` with all services running.

- [result.json](result.json): timestamp, actual command, 20 parallel HTTP outcomes; exactly five 201 and fifteen 409 for capacity five.
- [database-state.json](database-state.json): final inventory row (available zero) and five holds, captured via Inventory's own login.
- [service-logs.txt](service-logs.txt): structured requests with propagated evidence correlation IDs; shared capture includes neighboring challenge traffic.

Mechanism: atomic conditional UPDATE and hold INSERT in one transaction; database
CHECK prevents available outside [0, capacity]. Plain application check-then-update
can observe the same last seat in two concurrent requests and accept both. No
Python mutex is relied upon. Raw outputs are authoritative; do not invent screenshots.