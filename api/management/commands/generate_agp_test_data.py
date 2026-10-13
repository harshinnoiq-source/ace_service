"""
Django management command: generate_agp_test_data

WHERE THIS FILE GOES
---------------------
Inside whichever app contains your models.py / views.py (the one with
UserMaster, DeviceMaster, LogEntry, Alert), create this exact structure
if it doesn't already exist:

    <your_app>/
        management/
            __init__.py            <- empty file, must exist
            commands/
                __init__.py        <- empty file, must exist
                generate_agp_test_data.py   <- THIS file

If you already have a management/commands folder with other commands in
it, just drop this file in there — you don't need to redo the __init__.py
files.

HOW TO RUN
----------
    python manage.py generate_agp_test_data

Optional flags (all have sensible defaults matching your test case):
    python manage.py generate_agp_test_data \
        --user INNOIQCGM00003 \
        --device TESTDEVICE001 \
        --from-date 2026-07-02 \
        --to-date 2026-07-15 \
        --interval-minutes 5 \
        --clear

    --clear   deletes existing LogEntry rows for this user+device+date
              range before generating fresh ones (handy for re-runs).

WHAT IT DOES
------------
- Looks up UserMaster by user_id (does NOT create the user — create that
  via your app/API first).
- get_or_create's the DeviceMaster row for device_serial_no (status
  defaults to ACTIVE, life_span_days=14, since your model has no default
  for status).
- Generates a glucose reading every N minutes (default 5, i.e. 288/day)
  for each day in [from_date, to_date], following a realistic "normal
  patient" diurnal curve: overnight dip, mild breakfast/lunch/dinner
  bumps, random noise, mostly within 70-180 mg/dL.
- Creates each LogEntry via the ORM (amp is a required FloatField on your
  model with no defined meaning in the code shown — filled with a
  placeholder correlated to glucose_value; swap in your real formula if
  you have one).
- Mirrors the same out-of-range Alert creation your LogEntryViewSet.create
  does (LOW < 70, HIGH > 180), so alerts look realistic too.
- Prints a summary + the AGP report URL to hit afterwards.
"""

import math
import random
import statistics
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.timezone import make_aware, is_naive

from ...models import UserMaster, DeviceMaster, LogEntry, Alert

LOW_GLUCOSE_THRESHOLD = 70
HIGH_GLUCOSE_THRESHOLD = 180


class Command(BaseCommand):
    help = "Generate realistic 'normal patient' CGM test data for AGP report testing."

    def add_arguments(self, parser):
        parser.add_argument("--user", type=str, default="INNOIQCGM00003",
                            help="UserMaster.user_id")
        parser.add_argument("--device", type=str, default="TESTDEVICE001",
                            help="Device serial number")
        parser.add_argument("--from-date", type=str, default="2026-07-02",
                            help="YYYY-MM-DD")
        parser.add_argument("--to-date", type=str, default="2026-07-15",
                            help="YYYY-MM-DD (inclusive)")
        parser.add_argument("--interval-minutes", type=int, default=5)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--clear", action="store_true",
                            help="Delete existing LogEntry rows for this "
                                 "user+device+date range before generating")

    def handle(self, *args, **options):
        random.seed(options["seed"])

        user_id       = options["user"]
        device_serial = options["device"]
        from_date     = datetime.strptime(options["from_date"], "%Y-%m-%d").date()
        to_date       = datetime.strptime(options["to_date"], "%Y-%m-%d").date()
        interval      = options["interval_minutes"]

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            raise CommandError(
                f"UserMaster with user_id='{user_id}' not found. "
                f"Create the user first (this command does not create users)."
            )
        self.stdout.write(self.style.SUCCESS(
            f"Found user: {user.user_id} ({user.first_name} {user.last_name})"
        ))

        device, created = DeviceMaster.objects.get_or_create(
            device_serial_no=device_serial,
            defaults={
                "user": user,
                "device_type": "CGM_SENSOR",
                "status": "ACTIVE",
                "life_span_days": 14,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Paired new device: {device_serial}"))
        elif device.user_id != user.user_id:
            raise CommandError(
                f"Device '{device_serial}' already exists but belongs to a "
                f"different user ({device.user_id}). Use a different --device value."
            )
        else:
            self.stdout.write(f"Device already paired: {device_serial} (status={device.status})")

        if options["clear"]:
            start_dt = make_aware(datetime.combine(from_date, datetime.min.time()))
            end_dt   = make_aware(datetime.combine(to_date, datetime.max.time()))
            deleted, _ = LogEntry.objects.filter(
                user=user, deviceid=device_serial,
                timestamp__gte=start_dt, timestamp__lte=end_dt,
            ).delete()
            self.stdout.write(f"Cleared {deleted} existing log entries in range.")

        readings = self._build_readings(from_date, to_date, interval)
        self.stdout.write(
            f"Generating {len(readings)} readings ({interval}-min interval) "
            f"from {from_date} to {to_date}..."
        )

        log_count = 0
        alert_count = 0
        with transaction.atomic():
            for ts, gv in readings:
                aware_ts = make_aware(ts) if is_naive(ts) else ts
                log = LogEntry.objects.create(
                    user=user,
                    glucose_value=gv,
                    amp=self._simulate_amp(gv),
                    timestamp=aware_ts,
                    note="",
                    deviceid=device_serial,
                )
                log_count += 1

                if gv < LOW_GLUCOSE_THRESHOLD:
                    Alert.objects.create(
                        user=user, log=log, severity="LOW",
                        reason=f"Low glucose reading: {gv} mg/dL (below {LOW_GLUCOSE_THRESHOLD})",
                    )
                    alert_count += 1
                elif gv > HIGH_GLUCOSE_THRESHOLD:
                    Alert.objects.create(
                        user=user, log=log, severity="HIGH",
                        reason=f"High glucose reading: {gv} mg/dL (above {HIGH_GLUCOSE_THRESHOLD})",
                    )
                    alert_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Inserted {log_count} LogEntry rows, {alert_count} alerts."
        ))

        values = [gv for _, gv in readings]
        tir = sum(1 for v in values if 70 <= v <= 180) / len(values) * 100
        self.stdout.write(self.style.SUCCESS(
            f"\nSummary: avg={round(statistics.fmean(values), 1)} mg/dL  "
            f"min={min(values)}  max={max(values)}  TIR(70-180)={round(tir, 1)}%"
        ))

        self.stdout.write(self.style.SUCCESS(
            "\nNow try:\n"
            f"  /api/agp/agp-report-data/?user={user_id}&from_date={from_date}"
            f"&to_date={to_date}&device_serial_no={device_serial}"
        ))

    # ---- helpers ----------------------------------------------------

    def _simulate_amp(self, glucose_value):
        """Placeholder for the required `amp` FloatField — its real meaning
        isn't defined anywhere in the views/models shown, so this is just a
        plausible correlated value. Replace with your actual sensor formula
        if you have one."""
        return round(glucose_value * 0.1 + random.gauss(0, 0.5), 2)

    def _build_readings(self, from_date, to_date, interval_minutes):
        readings = []
        current_day = from_date
        while current_day <= to_date:
            t = datetime.combine(current_day, datetime.min.time())
            day_end = t + timedelta(days=1)
            while t < day_end:
                gv = self._simulate_glucose(t)
                readings.append((t, gv))
                t += timedelta(minutes=interval_minutes)
            current_day += timedelta(days=1)
        return readings

    def _simulate_glucose(self, t):
        """Realistic 'normal patient' curve: baseline ~95 mg/dL, overnight
        dip, gentle bumps around breakfast/lunch/dinner, mostly 70-180."""
        hour = t.hour + t.minute / 60.0

        baseline = 95.0
        if 0 <= hour < 6:
            baseline -= 10.0

        bump = 0.0
        for meal_center, amplitude, width in ((8, 40, 1.4), (13, 35, 1.4), (20, 45, 1.4)):
            bump += amplitude * math.exp(-((hour - meal_center) ** 2) / (2 * width ** 2))

        noise = random.gauss(0, 6)
        value = baseline + bump + noise
        value = max(65, min(195, value))
        return round(value)