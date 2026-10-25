import pytest

from services.notification import domain as notification


# BR6: a provider failure cannot be recorded as delivered (owner: Notification)

def test_br6_failed_notification_is_not_delivered():
    assert notification.attempt_outcome(simulate_failure=True) == notification.FAILED
    assert notification.can_deliver(notification.FAILED) is False
    with pytest.raises(ValueError):
        notification.resolve(notification.FAILED, simulate_failure=False)


def test_br6_successful_delivery_is_recorded_once():
    assert notification.resolve(None, simulate_failure=False) == notification.DELIVERED
    # A repeat after success keeps the original delivery, even if the repeat asks to fail.
    assert notification.resolve(notification.DELIVERED, simulate_failure=True) == notification.DELIVERED
