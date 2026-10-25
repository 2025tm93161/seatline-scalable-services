from scripts.challenges import concurrency, e2e, idempotency, saga


def test_main_transaction():
    e2e()


def test_twenty_parallel_requests():
    concurrency()


def test_br7_simultaneous_idempotency_and_conflict():
    idempotency()


def test_br8_step_three_failure_compensates():
    saga()