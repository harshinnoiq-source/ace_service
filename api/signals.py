import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import LogEntry, Alert

logger = logging.getLogger(__name__)

LOW_GLUCOSE_THRESHOLD = 70
HIGH_GLUCOSE_THRESHOLD = 180


@receiver(post_save, sender=LogEntry)
def create_alert_if_out_of_range(sender, instance, created, **kwargs):
    """
    Runs whenever a LogEntry is saved (via API, admin, shell, fixtures, etc.)
    and creates an Alert if the glucose reading is out of the safe range.

    Note: bulk_create() does NOT trigger signals, so bulk-inserted test data
    still won't generate alerts automatically.
    """
    if not created:
        return  # only fire on new LogEntry rows, not updates

    glucose_value = instance.glucose_value
    if glucose_value is None:
        return

    if glucose_value < LOW_GLUCOSE_THRESHOLD:
        reason = f"Low glucose reading: {glucose_value} mg/dL (below {LOW_GLUCOSE_THRESHOLD})"
        severity = 'LOW'
    elif glucose_value > HIGH_GLUCOSE_THRESHOLD:
        reason = f"High glucose reading: {glucose_value} mg/dL (above {HIGH_GLUCOSE_THRESHOLD})"
        severity = 'HIGH'
    else:
        return

    Alert.objects.create(user=instance.user, log=instance, reason=reason, severity=severity)
    logger.info(f"Alert created via signal: user_id={instance.user.user_id}, glucose={glucose_value}, reason={reason}")