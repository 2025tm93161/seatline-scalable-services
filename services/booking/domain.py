TRANSITIONS = {
    "PENDING": {"RESERVED", "COMPENSATING"},
    "RESERVED": {"PAID", "COMPENSATING"},
    "PAID": {"CONFIRMED", "COMPENSATING"},
    "COMPENSATING": {"CANCELLED", "COMPENSATION_PENDING"},
    "COMPENSATION_PENDING": {"COMPENSATING"},
    "CONFIRMED": set(),
    "CANCELLED": set(),
}


def assert_transition(current, target):
    if target not in TRANSITIONS[current]:
        raise ValueError(f"Illegal booking transition: {current} -> {target}")