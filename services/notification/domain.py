DELIVERED = "DELIVERED"
FAILED = "FAILED"
STATES = (DELIVERED, FAILED)


def attempt_outcome(simulate_failure):
    """Result of one call to the mock provider."""
    return FAILED if simulate_failure else DELIVERED


def can_deliver(current_state):
    """BR6: a provider failure is final. A FAILED delivery can never be recorded as DELIVERED."""
    return current_state != FAILED


def resolve(current_state, simulate_failure):
    """State a delivery request ends in, given what is already recorded for the booking.

    - Nothing recorded: the mock provider is called once.
    - DELIVERED recorded: the earlier delivery stands; the customer is not messaged twice.
    - FAILED recorded: rejected (BR6), because the booking was already compensated on that failure.
    """
    if current_state is None:
        return attempt_outcome(simulate_failure)
    if not can_deliver(current_state):
        raise ValueError("Failed notification cannot be marked delivered")
    return current_state
