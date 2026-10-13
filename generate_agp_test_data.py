"""
Standalone script -- generates realistic 5-minute-interval LogEntry test
data for AGP testing. No Django management-command machinery, no
management/commands/ folder, no INSTALLED_APPS changes needed.

WHERE TO PUT THIS FILE
----------------------
Same folder as manage.py (your project root).

BEFORE RUNNING -- edit these 2 lines below:
    1. DJANGO_SETTINGS_MODULE  -> your actual settings module
       (open manage.py, copy the value it uses in os.environ.setdefault(...))
    2. the model import line   -> your actual app name

RUN FROM TERMINAL
-----------------
python generate_agp_test_data_standalone.py --user INNOIQCGM00003 --days 14 --clear
"""

import os
import sys
import math
import random
import argparse
import datetime as dt

# --- 1. point this at your real settings module (check manage.py for the exact value) ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import django
django.setup()

from django.utils.timezone import make_aware

# --- 2. models live in the "api" app ---
from api.models import UserMaster, DeviceMaster, LogEntry


READING_INTERVAL_MINUTES = 5
SLOTS_PER_DAY = (24 * 60) // READING_INTERVAL_MINUTES  # 288


def _bump(hour, center, amplitude, width):
    return amplitude * math.exp(-((hour - center) ** 2) / (2 * width ** 2))


def _glucose_at(hour, rng, day_shift):
    """One simulated CGM reading (mg/dL) for a given hour-of-day."""
    baseline = 115 + day_shift + 18 * math.sin((hour - 4) / 24 * 2 * math.pi)
    meal = (
        _bump(hour, 7.5, 70, 1.3)     # breakfast
        + _bump(hour, 12.5, 65, 1.4)  # lunch
        + _bump(hour, 19, 80, 1.5)    # dinner
    )
    noise = rng.gauss(0, 14)
    value = baseline + meal + noise

    r = rng.random()
    if r < 0.012:
        value -= 45    # occasional low excursion (dawn dip / exercise)
    elif r > 0.988:
        value += 100   # occasional high excursion (missed bolus / high-carb meal)

    return round(max(40.0, value), 1)


def main():
    parser = argparse.ArgumentParser(description="Generate random AGP test data.")
    parser.add_argument('--user', required=True, help="user_id, e.g. INNOIQCGM00003")
    parser.add_argument('--days', type=int, default=14, help="Number of days of data (5-14)")
    parser.add_argument('--end-date', type=str, default=None, help="YYYY-MM-DD, default: today")
    parser.add_argument('--device', type=str, default='TESTDEVICE001', help="device_serial_no to tag readings with")
    parser.add_argument('--clear', action='store_true', help="Delete existing LogEntry rows for this user/range first")
    parser.add_argument('--seed', type=int, default=11, help="Random seed for reproducibility")
    args = parser.parse_args()

    if not (5 <= args.days <= 14):
        print(f"ERROR: --days must be between 5 and 14 (AGP report window). Got {args.days}.")
        sys.exit(1)

    try:
        user = UserMaster.objects.get(user_id=args.user)
    except UserMaster.DoesNotExist:
        print(f"ERROR: UserMaster with user_id='{args.user}' not found. Create the user first.")
        sys.exit(1)

    end_date = (
        dt.datetime.strptime(args.end_date, "%Y-%m-%d").date()
        if args.end_date else dt.date.today()
    )
    start_date = end_date - dt.timedelta(days=args.days - 1)

    device, _ = DeviceMaster.objects.get_or_create(
        device_serial_no=args.device,
        defaults={
            "user": user,
            "device_type": "CGM-SENSOR",
            "status": "ACTIVE",
            "life_span_days": 14,
        },
    )

    if args.clear:
        range_start = make_aware(dt.datetime.combine(start_date, dt.time.min))
        range_end   = make_aware(dt.datetime.combine(end_date, dt.time.max))
        deleted, _ = LogEntry.objects.filter(
            user=user, timestamp__gte=range_start, timestamp__lte=range_end
        ).delete()
        print(f"Cleared {deleted} existing LogEntry rows for {args.user} in range.")

    rng = random.Random(args.seed)
    entries = []
    current_date = start_date

    while current_date <= end_date:
        day_shift = rng.gauss(0, 8)
        for slot in range(SLOTS_PER_DAY):
            minute_of_day = slot * READING_INTERVAL_MINUTES
            hour = minute_of_day / 60.0
            ts = make_aware(dt.datetime.combine(
                current_date, dt.time(minute_of_day // 60, minute_of_day % 60)
            ))
            glucose_value = _glucose_at(hour, rng, day_shift)

            entries.append(LogEntry(
                user=user,
                glucose_value=glucose_value,
                amp=round(rng.uniform(0.8, 1.2), 2),
                timestamp=ts,
                note='',
                deviceid=args.device,
            ))
        current_date += dt.timedelta(days=1)

    LogEntry.objects.bulk_create(entries, batch_size=500)

    print(f"Created {len(entries)} LogEntry rows for {args.user} "
          f"({start_date} to {end_date}, device={args.device}).")
    print(f"Test it: GET /api/agp/agp-report-data/?user={args.user}"
          f"&from_date={start_date}&to_date={end_date}")


if __name__ == '__main__':
    main()