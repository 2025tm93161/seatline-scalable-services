def charge_state(decline):
    return "DECLINED" if decline else "CHARGED"


def refund_state(state):
    return "REFUNDED" if state in ("CHARGED", "REFUNDED") else "CANCELLED"