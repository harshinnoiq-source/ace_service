import random
from datetime import datetime, timedelta, time

from django.utils import timezone

from api.models import UserMaster, LogEntry


# ── Configure each user's test data here ────────────────────────────────
# (user_id, number_of_days, device_id)
USER_CONFIGS = [
    ("INNOIQCGM00069", 4,  "Board2"),
    ("INNOIQCGM00055", 5,  "Board2"),
    ("INNOIQCGM00087", 14, "Board2"),
]

INTERVAL_MIN = 5

# Fixed seed makes the generated dataset reproducible.
random.seed(10010)


def make_aware_datetime(date_obj, hour, minute):
    naive = datetime.combine(date_obj, time(hour=hour, minute=minute))
    return timezone.make_aware(naive)


def generate_glucose_value():
    """Generates one realistic glucose reading based on time-of-day + occasional outliers."""
    return None  # placeholder, replaced inline below for clarity per-hour


def build_readings_for_user(user, device_id, from_date, to_date):
    readings = []
    current_date = from_date

    while current_date <= to_date:
        t = make_aware_datetime(current_date, 0, 0)
        day_end = make_aware_datetime(current_date, 23, 55)

        while t <= day_end:
            hour = t.hour

            # Base glucose pattern
            if 0 <= hour < 6:
                glucose = random.gauss(95, 12)
            elif 6 <= hour < 9:
                glucose = random.gauss(145, 28)
            elif 9 <= hour < 12:
                glucose = random.gauss(115, 18)
            elif 12 <= hour < 14:
                glucose = random.gauss(150, 30)
            elif 14 <= hour < 18:
                glucose = random.gauss(110, 18)
            elif 18 <= hour < 21:
                glucose = random.gauss(155, 32)
            else:
                glucose = random.gauss(110, 18)

            # Occasional low / high outliers — useful for testing AGP Time-in-Range
            chance = random.random()
            if chance < 0.008:
                glucose = random.uniform(45, 53)      # Very low
            elif chance < 0.025:
                glucose = random.uniform(55, 69)       # Low
            elif chance < 0.045:
                glucose = random.uniform(181, 230)     # High
            elif chance < 0.052:
                glucose = random.uniform(251, 290)     # Very high

            glucose = round(max(40, min(300, glucose)))

            readings.append(
                LogEntry(
                    user=user,
                    glucose_value=glucose,
                    amp=0.0,
                    timestamp=t,
                    note="",
                    deviceid=device_id,
                )
            )

            t += timedelta(minutes=INTERVAL_MIN)

        current_date += timedelta(days=1)

    return readings


# ── Run for each configured user ────────────────────────────────────────
for user_id, num_days, device_id in USER_CONFIGS:
    print("==============================================")
    print(f"Processing user_id={user_id}, days={num_days}, device={device_id}")
    print("==============================================")

    try:
        user = UserMaster.objects.get(user_id=user_id)
    except UserMaster.DoesNotExist:
        print(f"ERROR: User '{user_id}' not found. Skipping.")
        continue

    to_date   = timezone.now().date()
    from_date = to_date - timedelta(days=num_days - 1)

    readings = build_readings_for_user(user, device_id, from_date, to_date)

    start_dt = make_aware_datetime(from_date, 0, 0)
    end_dt   = make_aware_datetime(to_date, 23, 55)

    deleted_count, _ = LogEntry.objects.filter(
        user=user,
        deviceid=device_id,
        timestamp__gte=start_dt,
        timestamp__lte=end_dt,
    ).delete()

    print(f"Deleted existing readings: {deleted_count}")

    LogEntry.objects.bulk_create(readings, batch_size=1000)

    print(f"User ID       : {user_id}")
    print(f"Email         : {user.email_id}")
    print(f"Device        : {device_id}")
    print(f"From          : {from_date}")
    print(f"To            : {to_date}")
    print(f"Interval      : {INTERVAL_MIN} minutes")
    print(f"Total readings: {len(readings)}")
    print("")

print("==============================================")
print("ALL USERS PROCESSED")
print("==============================================")