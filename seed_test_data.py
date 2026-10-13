# # ---------------------------------------------------------------------------
# # Seed 14 days of test glucose readings for user_id = INNOIQCGM00010
# #
# # HOW TO RUN:
# #   python manage.py shell < seed_test_data.py
# #
# # OR paste the whole block into:
# #   python manage.py shell
# # ---------------------------------------------------------------------------
#
# import random
# from datetime import timedelta
# from django.utils import timezone
# from api.models import UserMaster, LogEntry
#
# USER_ID       = "INNOIQCGM00010"
# DAYS          = 14
# INTERVAL_MIN  = 1           # one reading every 1 minute
# DEVICE_ID     = "TEST-DEVICE-0010"
#
# try:
#     user = UserMaster.objects.get(user_id=USER_ID)
# except UserMaster.DoesNotExist:
#     print(f"ERROR: User '{USER_ID}' not found. Create the user first.")
# else:
#     now        = timezone.now()
#     start_time = now - timedelta(days=DAYS)
#
#     readings   = []
#     t          = start_time
#     day_index  = 0
#
#     # simple day/night glucose pattern so avg / TIR / AGP curve looks realistic
#     while t <= now:
#         hour = t.hour
#
#         if 0 <= hour < 6:          # overnight -> a bit lower, some dips
#             base = random.randint(65, 110)
#         elif 6 <= hour < 9:        # morning rise (breakfast spike)
#             base = random.randint(110, 190)
#         elif 12 <= hour < 14:      # lunch spike
#             base = random.randint(120, 200)
#         elif 18 <= hour < 20:      # dinner spike
#             base = random.randint(120, 210)
#         else:                      # normal daytime
#             base = random.randint(80, 160)
#
#         # occasional random outlier to test alert creation (LOW < 70, HIGH > 180)
#         if random.random() < 0.03:
#             base = random.choice([random.randint(40, 65), random.randint(220, 300)])
#
#         readings.append(LogEntry(
#             user          = user,
#             glucose_value = base,
#             amp           = 0.0,
#             timestamp     = t,
#             note           = "",
#             deviceid      = DEVICE_ID,
#         ))
#
#         t += timedelta(minutes=INTERVAL_MIN)
#
#     LogEntry.objects.bulk_create(readings, batch_size=500)
#
#     print(f"Inserted {len(readings)} readings for user {USER_ID}")
#     print(f"Range: {start_time} -> {now}")
#     print("Note: bulk_create skips model .save(), so the auto-alert logic in "
#           "LogEntryViewSet.create() (Alert.objects.create for out-of-range values) "
#           "was NOT triggered. See the alert-seeding snippet below if you need alerts too.")


# ---------------------------------------------------------------------------
# Seed AGP test glucose readings
#
# User:   INNOIQCGM00003
# Device: Board2
# Period: 2026-08-12 -> 2026-08-24
#
# AGP expects 5-minute readings.
#
# Run:
#   python manage.py shell < seed_agp_test_data.py
# ---------------------------------------------------------------------------

import random
from datetime import datetime, timedelta, time

from django.utils import timezone

from api.models import UserMaster, LogEntry


USER_ID = "INNOIQCGM00003"
DEVICE_ID = "Board2"

FROM_DATE = "2026-08-27"
TO_DATE   = "2026-09-10"

INTERVAL_MIN = 5

# Fixed seed makes the generated dataset reproducible.
random.seed(10010)


def make_aware_datetime(date_obj, hour, minute):
    naive = datetime.combine(
        date_obj,
        time(hour=hour, minute=minute)
    )
    return timezone.make_aware(naive)


try:
    user = UserMaster.objects.get(user_id=USER_ID)
except UserMaster.DoesNotExist:
    print(f"ERROR: User '{USER_ID}' not found.")
else:

    from_date = datetime.strptime(FROM_DATE, "%Y-%m-%d").date()
    to_date = datetime.strptime(TO_DATE, "%Y-%m-%d").date()

    readings = []

    current_date = from_date

    while current_date <= to_date:

        t = make_aware_datetime(current_date, 0, 0)
        day_end = make_aware_datetime(current_date, 23, 55)

        while t <= day_end:

            hour = t.hour
            minute = t.minute

            # ---------------------------------------------------------------
            # Base glucose pattern
            # ---------------------------------------------------------------

            # Overnight
            if 0 <= hour < 6:
                glucose = random.gauss(95, 12)

            # Breakfast rise
            elif 6 <= hour < 9:
                glucose = random.gauss(145, 28)

            # Late morning
            elif 9 <= hour < 12:
                glucose = random.gauss(115, 18)

            # Lunch spike
            elif 12 <= hour < 14:
                glucose = random.gauss(150, 30)

            # Afternoon
            elif 14 <= hour < 18:
                glucose = random.gauss(110, 18)

            # Dinner spike
            elif 18 <= hour < 21:
                glucose = random.gauss(155, 32)

            # Late evening
            else:
                glucose = random.gauss(110, 18)

            # Occasional low / high values
            # Useful for testing AGP Time-in-Range.

            chance = random.random()

            if chance < 0.008:
                # Very low
                glucose = random.uniform(45, 53)

            elif chance < 0.025:
                # Low
                glucose = random.uniform(55, 69)

            elif chance < 0.045:
                # High
                glucose = random.uniform(181, 230)

            elif chance < 0.052:
                # Very high
                glucose = random.uniform(251, 290)

            # Keep values realistic.
            glucose = max(40, min(300, glucose))

            glucose = round(glucose)

            readings.append(
                LogEntry(
                    user=user,
                    glucose_value=glucose,
                    amp=0.0,
                    timestamp=t,
                    note="",
                    deviceid=DEVICE_ID,
                )
            )

            t += timedelta(minutes=INTERVAL_MIN)

        current_date += timedelta(days=1)

    # ---------------------------------------------------------------
    # Optional: remove existing test data for this exact user/device
    # and date range before inserting.
    # ---------------------------------------------------------------

    start_dt = make_aware_datetime(from_date, 0, 0)
    end_dt = make_aware_datetime(to_date, 23, 55)

    deleted_count, _ = LogEntry.objects.filter(
        user=user,
        deviceid=DEVICE_ID,
        timestamp__gte=start_dt,
        timestamp__lte=end_dt,
    ).delete()

    print(f"Deleted existing readings: {deleted_count}")

    LogEntry.objects.bulk_create(
        readings,
        batch_size=1000
    )

    print("")
    print("==============================================")
    print("AGP TEST DATA CREATED")
    print("==============================================")
    print(f"User ID       : {USER_ID}")
    print(f"Device        : {DEVICE_ID}")
    print(f"From          : {FROM_DATE}")
    print(f"To            : {TO_DATE}")
    print(f"Interval      : {INTERVAL_MIN} minutes")
    print(f"Total readings: {len(readings)}")
    print("==============================================")
