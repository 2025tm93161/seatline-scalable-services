import pytest

from services.booking.domain import assert_transition
from services.notification.domain import can_deliver
from services.payment.domain import charge_state, refund_state


def test_br3_payment_decline_is_not_charge():
    assert charge_state(True) == "DECLINED"
    assert charge_state(False) == "CHARGED"


def test_br4_refund_can_be_repeated():
    assert refund_state("CHARGED") == "REFUNDED"
    assert refund_state(refund_state("CHARGED")) == "REFUNDED"
    assert refund_state("MISSING") == "CANCELLED"


def test_br5_confirmed_booking_is_terminal():
    with pytest.raises(ValueError):
        assert_transition("CONFIRMED", "COMPENSATING")
    assert_transition("PAID", "COMPENSATING")


def test_br6_failed_notification_is_not_delivered():
    assert not can_deliver(True)
    assert can_deliver(False)