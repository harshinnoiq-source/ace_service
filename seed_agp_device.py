from datetime import datetime, time
from django.utils import timezone
from api.models import UserMaster, DeviceMaster

USER_ID   = "INNOIQCGM00193"
DEVICE_ID = "Board2"
FROM_DATE = "2026-10-12"          # first day of the seeded readings

user = UserMaster.objects.get(user_id=USER_ID)

start = timezone.make_aware(
    datetime.combine(datetime.strptime(FROM_DATE, "%Y-%m-%d").date(), time(0, 0))
)

# device_serial_no is unique across all users
device, created = DeviceMaster.objects.get_or_create(
    device_serial_no=DEVICE_ID,
    defaults=dict(user=user, device_type="CGM Sensor", status="ACTIVE", life_span_days=14),
)

# If the device still belongs to the deleted user, deleting that user already
# removed it (CASCADE), so this normally just created it. If it belongs to
# someone else, move it:
if device.user_id != user.user_id:
    device.user = user
    device.save(update_fields=["user"])

# update() skips auto_now_add / auto_now, so the date sticks
DeviceMaster.objects.filter(pk=device.pk).update(assigned_at=start, updated_at=start)

device.refresh_from_db()
print("created:", created, "| assigned_at:", device.assigned_at, "| status:", device.status)