#Standard Library------------------------------
import json
import os
import re
import uuid
from datetime import timedelta
#django imports------------------
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from google.protobuf import timestamp
from proto.marshal.compat import message
from pyasn1.type.error import ValueConstraintError
from requests.packages import target

#DRF imports------------------
from rest_framework import status, viewsets,mixins
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
#local imports
import requests as http_requests
from django.db.models import Avg, Max, Min, Count, Q
from django.db.models.functions import Round
from django.db.models import FloatField
from rest_framework.status import HTTP_404_NOT_FOUND
from django.shortcuts import render, redirect
from .models import *
from .serializers import *

import math
import statistics
import datetime as dt

from django.utils import timezone
from django.utils.timezone import make_aware
from datetime import timedelta
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
import datetime as dt
from django.utils.timezone import make_aware
from .models import normalize_mobile_number
from django.db import IntegrityError
#Report module
import datetime as dt
from django.utils.timezone import make_aware
from .utils import generate_otp
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
import secrets

# Constants

MEDIA_ADMIN_ID           = "admin"
MEDIA_ADMIN_PASSWORD     = "admin123"
CAREGIVER_INVITE_EXPIRY_DAYS = 1
MAX_CAREGIVERS_PER_USER      = 4

#logger
import logging
logger = logging.getLogger(__name__)
#-----------------------------
from django.db.models import Q
from django.db.models.functions import ExtractHour

# Version------
LOW_GLUCOSE_THRESHOLD  = 70
HIGH_GLUCOSE_THRESHOLD = 180
EVENT_TYPES = ('LOW', 'HIGH')

def get_user_thresholds(user):
    pref = getattr(user, 'preference', None)   # related_name='preference'
    low  = pref.target_range_low  if pref else LOW_GLUCOSE_THRESHOLD
    high = pref.target_range_high if pref else HIGH_GLUCOSE_THRESHOLD
    return low, high


class VersionViewSet(viewsets.ModelViewSet):
    queryset         = Version.objects.all()
    serializer_class = VersionSerializer


def version_page(request):
    version = Version.objects.last()
    return render(request, 'version.html', {'version': version})



# # TEMP: test logger
# logger.debug("DEBUG log test")
# logger.info("INFO log test")
# logger.warning("WARNING log test")
# logger.error("ERROR log test")
# Log Entry
class LogEntryViewSet(viewsets.ModelViewSet):
    queryset         = LogEntry.objects.all()
    serializer_class = LogEntrySerializer

    def create(self, request, *args, **kwargs):
        user_id_str = request.data.get('user') or request.data.get('user_id')
        print("user_id",user_id_str)
        try:
            user_instance = UserMaster.objects.get(user_id=user_id_str)
        except UserMaster.DoesNotExist:
            logger.warning(f"LogEntry Created Failed:User not found user_id={user_id_str}")
            return Response(
                {"status": "error", "message": "User not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ---------- NEW: validate and convert input ----------
        try:
            glucose = float(request.data.get('glucose_value'))
        except (TypeError, ValueError):
            return Response(
                {"status": "error", "message": "glucose_value must be a number"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            amp = float(request.data.get('amp') or 0)      # amp is NOT NULL in the model
        except (TypeError, ValueError):
            return Response(
                {"status": "error", "message": "amp must be a number"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ts = parse_datetime(str(request.data.get('timestamp') or ''))
        if ts is None:
            return Response(
                {"status": "error", "message": "timestamp is required in ISO format, e.g. 2026-10-17T10:30:00Z"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if timezone.is_naive(ts):
            ts = timezone.make_aware(ts, timezone.get_current_timezone())
        # ------------------------------------------------------

        log = LogEntry(
            user          = user_instance,
            glucose_value = glucose,      # was request.data.get('glucose_value')
            amp           = amp,          # was request.data.get('amp')
            timestamp     = ts,           # was request.data.get('timestamp')
            note          = request.data.get('note', ''),
            deviceid      = request.data.get('deviceid', ''),
        )
        log.save()
        logger.info(f"LogEntry created: user_id={user_id_str},glucose={log.glucose_value},ts={log.timestamp}")

        # Auto-create an alert if the reading is out of range
        self._create_alert_if_out_of_range(user_instance, log)

        serializer = self.get_serializer(log, context={'request': request})
        return Response({"status": "success", "data": serializer.data})

    # _create_alert_if_out_of_range stays exactly as it is
    @staticmethod
    def _create_alert_if_out_of_range(user, log):
        glucose_value = log.glucose_value
        if glucose_value is None:
            return

        low, high = get_user_thresholds(user)

        if glucose_value < low:
            reason = f"Low glucose reading: {glucose_value} mg/dL (below {low})"
            severity = 'LOW'
        elif glucose_value > high:
            reason = f"High glucose reading: {glucose_value} mg/dL (above {high})"
            severity = 'HIGH'
        else:
            return

        Alert.objects.create(
            user=user, log=log, reason=reason, severity=severity,
            glucose_value=glucose_value,
            target_range_low=low, target_range_high=high,
        )
        logger.info(f"Alert created: user_id={user.user_id}, glucose={glucose_value}, reason={reason}")
class AlertViewSet(viewsets.ViewSet):
    def list(self, request):
        user_id = request.query_params.get('user')
        if not user_id:
            return Response({
                "status": "error",
                "message": "user parameter is required"
            }, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({
                "status": "error",
                "message": "User not found"
            }, status=status.HTTP_404_NOT_FOUND)

        alerts = Alert.objects.filter(user=user).select_related('log').order_by('-created_at')
        high_alerts = alerts.filter(severity="HIGH").count()
        low_alerts = alerts.filter(severity="LOW").count()

        # "today" = the glucose reading happened today, not when the Alert row was inserted
        today = timezone.now().date()
        today_alerts = alerts.filter(log__timestamp__date=today)
        today_count = today_alerts.count()
        today_high_count = today_alerts.filter(severity="HIGH").count()
        today_low_count = today_alerts.filter(severity="LOW").count()

        serializer = AlertSerializer(alerts, many=True)
        return Response({
            "status": "success",
            "count": alerts.count(),
            "high_count": high_alerts,
            "low_count": low_alerts,
            "today_count": today_count,
            "today_high_count": today_high_count,
            "today_low_count": today_low_count,
            "data": serializer.data,
        })
    def create(self, request):
        user_id = request.data.get('user')
        timestamp_str = request.data.get('timestamp')
        glucose_value = request.data.get('glucose_value')
        severity = request.data.get('severity')
        reason = request.data.get('reason')
        target_range_high = request.data.get('target_range_high')
        target_range_low = request.data.get('target_range_low')

        if not user_id:
            return Response({
                "status": "error",
                "message": "user is required"
            }, status=status.HTTP_400_BAD_REQUEST)

        if not timestamp_str:
            return Response({
                "status": "error",
                "message": "timestamp is required"
            }, status=status.HTTP_400_BAD_REQUEST)

        if glucose_value is None:
            return Response({
                "status": "error",
                "message": "glucose_value is required"
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            glucose_value = float(glucose_value)
        except (TypeError, ValueError):
            return Response({
                "status": "error",
                "message": "glucose_value must be a number"
            }, status=status.HTTP_400_BAD_REQUEST)

        if not reason:
            return Response({
                "status": "error",
                "message": "reason is required"
            }, status=status.HTTP_400_BAD_REQUEST)

        if target_range_high is not None:
            try:
                target_range_high = int(target_range_high)
            except (TypeError, ValueError):
                return Response({
                    "status": "error",
                    "message": "target_range_high must be an integer"
                }, status=status.HTTP_400_BAD_REQUEST)

        if target_range_low is not None:
            try:
                target_range_low = int(target_range_low)
            except (TypeError, ValueError):
                return Response({
                    "status": "error",
                    "message": "target_range_low must be an integer"
                }, status=status.HTTP_400_BAD_REQUEST)

        if severity and severity not in dict(Alert.SEVERITY_CHOICES):
            return Response({
                "status": "error",
                "message": f"severity must be one of {list(dict(Alert.SEVERITY_CHOICES).keys())}"
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({
                "status": "error",
                "message": "User Not Found"
            }, status=status.HTTP_404_NOT_FOUND)

        # parse the incoming timestamp and truncate to the minute
        dt_value = parse_datetime(timestamp_str)
        if dt_value is None:
            return Response({
                "status": "error",
                "message": "Invalid timestamp format"
            }, status=status.HTTP_400_BAD_REQUEST)

        if timezone.is_naive(dt_value):
            dt_value = timezone.make_aware(dt_value, timezone.get_current_timezone())

        minute_start = dt_value.replace(second=0, microsecond=0)
        minute_end = minute_start + timedelta(minutes=1)

        log = LogEntry.objects.filter(
            user=user,
            timestamp__gte=minute_start,
            timestamp__lt=minute_end
        ).order_by('timestamp').first()

        if not log:
            return Response({
                "status": "error",
                "message": "No log entry found for this user within that minute"
            }, status=status.HTTP_404_NOT_FOUND)

        target_high = target_range_high
        target_low = target_range_low
        if target_high is None or target_low is None:
            preference = getattr(user, 'preference', None)
            if target_high is None:
                target_high = preference.target_range_high if preference else None
            if target_low is None:
                target_low = preference.target_range_low if preference else None

        alert = Alert.objects.create(
            user=user,
            log=log,
            severity=severity,
            reason=reason,
            glucose_value=glucose_value,
            target_range_high=target_high,
            target_range_low=target_low,
        )
        serializer = AlertSerializer(alert)
        return Response({
            "status": "success",
            "message": "Alert created successfully",
            "data": serializer.data,
        }, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        return self._update_alert(request, pk, partial=False)

    def partial_update(self, request, pk=None):
        return self._update_alert(request, pk, partial=True)

    def _update_alert(self, request, pk, partial):
        try:
            alert = Alert.objects.get(pk=pk)
        except Alert.DoesNotExist:
            return Response({
                "status": "error",
                "message": "Alert not found"
            }, status=status.HTTP_404_NOT_FOUND)

        severity = request.data.get('severity')
        reason = request.data.get('reason')
        timestamp_str = request.data.get('timestamp')
        glucose_value = request.data.get('glucose_value')
        target_range_high = request.data.get('target_range_high')
        target_range_low = request.data.get('target_range_low')

        if not partial and not reason:
            return Response({
                "status": "error",
                "message": "reason is required"
            }, status=status.HTTP_400_BAD_REQUEST)

        if severity is not None:
            if severity and severity not in dict(Alert.SEVERITY_CHOICES):
                return Response({
                    "status": "error",
                    "message": f"severity must be one of {list(dict(Alert.SEVERITY_CHOICES).keys())}"
                }, status=status.HTTP_400_BAD_REQUEST)
            alert.severity = severity

        if reason is not None:
            alert.reason = reason

        if glucose_value is not None:
            try:
                alert.glucose_value = float(glucose_value)
            except (TypeError, ValueError):
                return Response({
                    "status": "error",
                    "message": "glucose_value must be a number"
                }, status=status.HTTP_400_BAD_REQUEST)

        if target_range_high is not None:
            try:
                alert.target_range_high = int(target_range_high)
            except (TypeError, ValueError):
                return Response({
                    "status": "error",
                    "message": "target_range_high must be an integer"
                }, status=status.HTTP_400_BAD_REQUEST)

        if target_range_low is not None:
            try:
                alert.target_range_low = int(target_range_low)
            except (TypeError, ValueError):
                return Response({
                    "status": "error",
                    "message": "target_range_low must be an integer"
                }, status=status.HTTP_400_BAD_REQUEST)

        if alert.target_range_high is not None and alert.target_range_low is not None:
            if alert.target_range_low >= alert.target_range_high:
                return Response({
                    "status": "error",
                    "message": "target_range_low must be less than target_range_high"
                }, status=status.HTTP_400_BAD_REQUEST)

        if timestamp_str is not None:
            dt_value = parse_datetime(timestamp_str)
            if dt_value is None:
                return Response({
                    "status": "error",
                    "message": "Invalid timestamp format"
                }, status=status.HTTP_400_BAD_REQUEST)

            if timezone.is_naive(dt_value):
                dt_value = timezone.make_aware(dt_value, timezone.get_current_timezone())

            minute_start = dt_value.replace(second=0, microsecond=0)
            minute_end = minute_start + timedelta(minutes=1)

            log = LogEntry.objects.filter(
                user=alert.user,
                timestamp__gte=minute_start,
                timestamp__lt=minute_end
            ).order_by('timestamp').first()

            if not log:
                return Response({
                    "status": "error",
                    "message": "No log entry found for this user within that minute"
                }, status=status.HTTP_404_NOT_FOUND)

            alert.log = log

        alert.save()
        logger.info(f"Alert updated: id={alert.id}, user_id={alert.user.user_id}")

        serializer = AlertSerializer(alert)
        return Response({
            "status": "success",
            "message": "Alert updated successfully",
            "data": serializer.data,
        })

    def retrieve(self,request,pk=None):
        try:
            alert =Alert.objects.select_related('log','user').get(pk=pk)
        except Alert.DoesNotExist:
            return Response({
                "status":"error",
                "message":"Alert Not Found"
            },status=HTTP_404_NOT_FOUND)
        serializer=AlertSerializer(alert)
        return Response({
            "status":"success",
            "data":serializer.data,

        })

class UserWiseLogEntryViewSet(viewsets.ViewSet):

    def list(self, request):
        user_id = request.query_params.get("user")

        if not user_id:
            return Response({"status": "error", "message": "user parameter required"})

        logs       = LogEntry.objects.filter(user__user_id=user_id).order_by('-id')
        last_log   = logs.first()
        serializer = LogEntrySerializer(logs, many=True)

        return Response({
            "status":       "success",
            "last_updated": last_log.timestamp if last_log else None,
            "data":         serializer.data,
        })

@csrf_exempt
def log_entries_page(request):
    logs_list   = LogEntry.objects.all().order_by('-id')
    paginator   = Paginator(logs_list, 150)
    logs        = paginator.get_page(request.GET.get('page'))
    return render(request, "log_list.html", {"logs": logs})


def user_wise_log_entries_page(request):
    user_id   = request.GET.get("user_id")
    logs_list = LogEntry.objects.all().order_by('-id')

    if user_id:
        logs_list = logs_list.filter(user__user_id=user_id)

    paginator = Paginator(logs_list, 150)
    logs      = paginator.get_page(request.GET.get('page'))

    return render(request, "user_wise_log_list.html", {"logs": logs, "user_id": user_id})


# User Master
# Add `mixins` to your existing DRF import at the top of views.py:
#   from rest_framework import status, viewsets, mixins


# User Master
class UserMasterViewSet(
    mixins.CreateModelMixin,      # POST /api/users/             (register)
    mixins.RetrieveModelMixin,    # GET  /api/users/<user_id>/   (one user)
    viewsets.GenericViewSet,
    mixins.DestroyModelMixin,
):
    queryset         = UserMaster.objects.all()
    serializer_class = UserMasterSerializer
    lookup_field     = 'user_id'


    def retrieve(self, request, *args, **kwargs):
        instance   = self.get_object()
        serializer = self.get_serializer(instance, context={'request': request})
        return Response({"status": "success", "data": serializer.data})
    def validate_emergency_contact_number(self, value):
        own_mobile = None
        if self.instance and self.instance.mobile_number:
            own_mobile = self.instance.mobile_number
        elif self.initial_data.get('mobile_number'):
            own_mobile = self.initial_data.get('mobile_number')

        try:
            return _validate_emergency(value, own_mobile=own_mobile)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
    def create(self, request, *args, **kwargs):
        email_id = request.data.get('email_id', '').lower().strip()
        if not email_id:
            return Response(
                {"status": "error", "message": "email_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if UserMaster.objects.filter(email_id__iexact=email_id).exists():
            logger.warning(f"User create failed:duplicated email={email_id}")
            return Response(
                {"status": "error", "message": "This email is already registered."},
                status=status.HTTP_409_CONFLICT,
            )

        mobile_number = (request.data.get('mobile_number') or '').strip()
        if mobile_number:
            normalized_mobile = normalize_mobile_number(mobile_number)
            if UserMaster.objects.filter(mobile_number=normalized_mobile).exists():
                logger.warning(f"User create failed: duplicated mobile_number={normalized_mobile}")
                return Response(
                    {"status": "error", "message": "This mobile number is already registered."},
                    status=status.HTTP_409_CONFLICT,
                )

        # --- Password validation ---
        # raw_password = request.data.get('password')
        # --- Password validation (optional, validated only if provided) ---
        raw_password = request.data.get('password')
        raw_password = raw_password if raw_password not in (None, '') else None

        if raw_password is not None:
            try:
                validate_password(raw_password)
            except DjangoValidationError as e:
                return Response(
                    {"status": "error", "message": "Weak password", "errors": list(e.messages)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        profile_picture = request.FILES.get('profile_picture')
        if profile_picture:
            allowed_formats = ['image/jpeg', 'image/png', 'image/gif', 'image/jpg']
            if profile_picture.content_type not in allowed_formats:
                return Response(
                    {"status": "error", "message": "Only JPG, PNG and GIF formats are allowed."},
                    status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                )

        data = request.data.copy()

        serializer = self.get_serializer(data=data, context={'request': request})
        if serializer.is_valid():
            try:
                user = serializer.save()
                if raw_password is not None:
                    user.password = make_password(raw_password)
                else:
                    user.password = None
                user.save(update_fields=['password'])
            except IntegrityError:
                logger.warning(f"User create failed: race-condition duplicate mobile_number={mobile_number}")
                return Response(
                    {"status": "error", "message": "This mobile number is already registered."},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response({
                "status": "success",
                "message": "User created successfully",
                "data": self.get_serializer(user, context={'request': request}).data,
            }, status=status.HTTP_201_CREATED)

        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='login')
    def login(self, request):
        email_id = (request.data.get('email_id') or '').lower().strip()
        password = request.data.get('password')

        if not email_id or not password:
            return Response(
                {"status": "error", "message": "email_id and password are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = UserMaster.objects.get(email_id__iexact=email_id)
        except UserMaster.DoesNotExist:
            logger.warning(f"Login Failed: email not found email={email_id}")
            return Response(
                {"status": "error", "message": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Account has no password (Google sign-in, phone sign-in, or registered without one)
        if not user.password:
            logger.warning(f"Login Failed: no password set for account email={email_id}")
            return Response(
                {
                    "status": "error",
                    "message": "Unable to sign in with a password.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not check_password(password, user.password):
            logger.warning(f"Login Failed: wrong password email={email_id}")
            return Response(
                {"status": "error", "message": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        logger.info(f"Login successful: user_id={user.user_id}, email={email_id}")
        serializer = self.get_serializer(user, context={'request': request})
        return Response({"status": "success", "message": "Login successful", "data": serializer.data})
    @action(detail=False, methods=['post'], url_path='validate_user')
    def validate_user(self, request):
        user_id = request.data.get('user_id')

        if not user_id:
            return Response({"status": "error", "message": "user_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = UserMaster.objects.get(user_id=user_id)
            return Response({
                "status":  "success",
                "message": "User exists",
                "data": {
                    "user_id":    user.user_id,
                    "first_name": user.first_name,
                    "last_name":  user.last_name,
                    "isNewUser":  user.isNewUser,
                },
            })
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['get'], url_path='check_user')
    def check_user(self, request):
        email_id = request.query_params.get('email_id')

        if not email_id:
            return Response({"status": "error", "message": "email_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = UserMaster.objects.get(email_id__iexact=email_id)
            return Response({
                "status":  "success",
                "message": "User exists",
                "data": {
                    "email_id":   user.email_id,
                    "first_name": user.first_name,
                    "user_id":    user.user_id,
                    "last_name":  user.last_name,
                    "isNewUser":  user.isNewUser,
                },
            })
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['get'], url_path='check_mobile/(?P<mobile_number>[^/.]+)')
    def check_mobile(self, request, mobile_number=None):
        if not mobile_number:
            return Response({"status": "error", "message": "mobile_number is required"}, status=status.HTTP_400_BAD_REQUEST)

        normalized = normalize_mobile_number(mobile_number)

        user = UserMaster.objects.filter(mobile_number=normalized).first()

        if not user:
            return Response({"status": "success", "message": "User not found", "exists": False})

        return Response({
            "status":  "success",
            "message": "User exists",
            "data": {
                "mobile_number": user.mobile_number,
                "user_id":       user.user_id,
                "first_name":    user.first_name,
                "last_name":     user.last_name,
                "isNewUser":     user.isNewUser,
            },
        })

    @action(detail=False, methods=['post'], url_path='validate_password')
    def validate_password(self, request):
        user_id  = request.data.get('user_id')
        password = request.data.get('password')

        if not user_id or not password:
            return Response(
                {"status": "error", "message": "user_id and password are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        if check_password(password, user.password):
            return Response({"status": "success", "message": "Password is valid"})

        return Response({"status": "error", "message": "Invalid password"}, status=status.HTTP_401_UNAUTHORIZED)

    @action(detail=False, methods=['post'], url_path='google_signin')
    def google_signin(self, request):
        def _clean_str(value):               # handles null-like values
            if value is None:
                return None
            value = str(value).strip()
            if value.lower() in ('', 'null', 'none', 'undefined'):
                return None
            return value

        email_id                = _clean_str(request.data.get('email_id'))
        first_name              = request.data.get('first_name', '') or ''
        middle_name             = _clean_str(request.data.get('middle_name'))
        last_name               = request.data.get('last_name', '') or ''
        firebase_token          = _clean_str(request.data.get('firebase_token'))
        google_profile_picture  = _clean_str(request.data.get('profile_picture'))
        mobile_number           = _clean_str(request.data.get('mobile_number'))

        if not email_id:
            return Response({"status": "error", "message": "email_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        email_id = email_id.lower()

        user = UserMaster.objects.filter(email_id__iexact=email_id).first()

        if user:
            if firebase_token:
                user.firebase_token = firebase_token
            if google_profile_picture:
                user.google_profile_picture = google_profile_picture
            if mobile_number and mobile_number != user.mobile_number:
                if UserMaster.objects.filter(mobile_number=mobile_number).exclude(user_id=user.user_id).exists():
                    return Response(
                        {"status": "error", "message": "This mobile number is already registered with another account."},
                        status=status.HTTP_409_CONFLICT,
                    )
                user.mobile_number = mobile_number
            user.save()
            logger.info(f"Google sign in existing user:user_id={user.user_id},email={email_id}")
            serializer = GoogleSignInSerializer(user, context={'request': request})
            return Response({
                "status":    "success",
                "message":   "Login successful",
                "isNewUser": user.isNewUser,
                "data":      serializer.data,
            })

        # New user path — check mobile_number uniqueness BEFORE attempting save
        if mobile_number and UserMaster.objects.filter(mobile_number=mobile_number).exists():
            return Response(
                {"status": "error", "message": "This mobile number is already registered with another account."},
                status=status.HTTP_409_CONFLICT,
            )

        data = {
            'first_name':     first_name,
            'middle_name':    middle_name,
            'last_name':      last_name,
            'email_id':       email_id,
            'firebase_token': firebase_token,
            'mobile_number':  mobile_number,
        }

        serializer = self.get_serializer(data=data, context={'request': request})
        if serializer.is_valid():
            user = serializer.save()
            logger.info(f"Google sign-in new user Created: user_id={user.user_id},email={email_id}")
            if google_profile_picture:
                user.google_profile_picture = google_profile_picture
                user.save()

            serializer = GoogleSignInSerializer(user, context={'request': request})
            return Response({
                "status":    "success",
                "message":   "User created successful",
                "isNewUser": True,
                "data":      serializer.data,
            }, status=status.HTTP_201_CREATED)

        if 'email_id' in serializer.errors:
            return Response(
                {"status": "error", "message": "This email is already registered."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['patch'], url_path='update_profile')
    def update_profile(self, request, user_id=None):
        instance = self.get_object()

        # 1. Email can never be changed
        incoming_email = request.data.get('email_id')
        if incoming_email is not None:
            if str(incoming_email).lower().strip() != (instance.email_id or '').lower():
                return Response(
                    {"status": "error", "message": "Registered email cannot be changed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # 2. Fields that are never editable through this endpoint
        restricted_fields = [
            'email_id', 'first_name', 'last_name', 'middle_name', 'password',
            'mobile_number', 'address', 'city', 'state', 'zip_code',
        ]
        data = request.data.copy()
        for field in restricted_fields:
            data.pop(field, None)

        # 3. Set-once fields: editable only while null/empty, locked after that
        LOCK_ONCE_SET = {'gender': 'Gender', 'dob': 'Date of birth'}
        for field, label in LOCK_ONCE_SET.items():
            current = getattr(instance, field)
            if current in (None, ''):
                continue  # not set yet -> user can update

            incoming = request.data.get(field)
            if incoming is not None:
                if field == 'dob':
                    same = str(incoming).strip()[:10] == str(current)
                else:
                    same = str(incoming).strip().lower() == str(current).lower()
                if not same:
                    return Response(
                        {"status": "error", "message": f"{label} cannot be changed."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            data.pop(field, None)  # same value or not sent: ignore

        # 4. Profile picture check
        profile_picture = request.FILES.get('profile_picture')
        if profile_picture:
            if profile_picture.content_type not in ['image/jpeg', 'image/png', 'image/gif']:
                return Response(
                    {"status": "error", "message": "Only JPG, PNG and GIF formats are allowed."},
                    status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                )

        # 5. Save
        serializer = self.get_serializer(instance, data=data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Profile updated: user_id={instance.user_id}")
            return Response({"status": "success", "message": "Profile updated successfully", "data": serializer.data})
        logger.warning(f"Profile update failed: user_id={instance.user_id}")
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        AuditLog.objects.create(user=user, device=None, action='USER_DELETED',
                                reason='Deleted via API')
        logger.info(f"User deleted: user_id={user.user_id}")
        user.delete()
        return Response({"status": "success", "message": "User deleted successfully"},
                        status=status.HTTP_200_OK)

# Delete Account  (web page flow)

@method_decorator(csrf_exempt, name='dispatch')
class DeleteAccountViewSet(viewsets.ViewSet):

    def list(self, request):
        user_id = request._request.GET.get('user_id', '')

        if not user_id:
            logger.warning(f"Account delete failed:user not found user_id={user_id}")
            return render(request._request, 'delete_account.html', {
                'error': 'Invalid link. user_id is missing.', 'user': None, 'email_id': '', 'success': False,
            })

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return render(request._request, 'delete_account.html', {
                'error': 'User not found.', 'user': None, 'email_id': '', 'success': False,
            })

        return render(request._request, 'delete_account.html', {
            'user':      user,
            'email_id':  user.email_id or '',
            'full_name': f"{user.first_name} {user.last_name}" if user.last_name else user.first_name,
            'error':     None,
            'success':   False,
        })

    def create(self, request):
        user_id  = request._request.POST.get('user_id')
        password = request._request.POST.get('password')
        reason   = request._request.POST.get('reason', '').strip() or 'User requested account deletion'

        if not user_id or not password:
            return render(request._request, 'delete_account.html', {
                'error': 'All fields are required.', 'user': None, 'email_id': '', 'success': False,
            })

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return render(request._request, 'delete_account.html', {
                'error': 'User not found.', 'user': None, 'email_id': '', 'success': False,
            })

        if not check_password(password, user.password):
            logger.warning(f"Account delete failed:wrong password user_id={user_id}")
            return render(request._request, 'delete_account.html', {
                'error':     'Incorrect password. Please try again.',
                'user':      user,
                'email_id':  user.email_id or '',
                'full_name': f"{user.first_name} {user.last_name}" if user.last_name else user.first_name,
                'success':   False,
            })

        AuditLog.objects.create(user=user, device=None, action='USER_DELETED', reason=reason)
        logger.info(f"Account deleted: user_id={user_id},reason={reason}")
        user.delete()

        return render(request._request, 'delete_account.html', {
            'user': None, 'email_id': '', 'error': None, 'success': True,
        })

# Glucose Reports

def _filter_logs_by_date(logs, from_date_str, to_date_str):
    if from_date_str:
        dtv = parse_datetime(from_date_str)
        if dtv is None:
            d = parse_date(from_date_str)
            dtv = make_aware(dt.datetime.combine(d, dt.time.min)) if d else None
        if dtv:
            logs = logs.filter(timestamp__gte=dtv)
    if to_date_str:
        dtv = parse_datetime(to_date_str)
        if dtv is not None:
            logs = logs.filter(timestamp__lte=dtv)
        else:
            d = parse_date(to_date_str)
            if d:
                logs = logs.filter(timestamp__lt=make_aware(
                    dt.datetime.combine(d + timedelta(days=1), dt.time.min)))
    return logs

def glucose_report_json(request, user_id):
    try:
        user = UserMaster.objects.get(user_id=user_id)
    except UserMaster.DoesNotExist:
        return Response({"status": "error", "message": "User not found"}, status=404)

    logs = _filter_logs_by_date(
        LogEntry.objects.filter(user=user).order_by('timestamp'),
        request.GET.get('from_date'),
        request.GET.get('to_date'),
    )

    return Response({
        "status": "success",
        "user": {
            "user_id":         user.user_id,
            "first_name":      user.first_name,
            "middle_name":     user.middle_name,
            "last_name":       user.last_name,
            "gender":          user.gender,
            "dob":             str(user.dob),
            "mobile_number":   user.mobile_number,
            "address":         user.address,
            "isNewUser":       user.isNewUser,
            "profile_picture": request.build_absolute_uri(user.profile_picture.url) if user.profile_picture else None,
        },
        "logs": [
            {"glucose_value": log.glucose_value, "timestamp": log.timestamp, "note": log.note}
            for log in logs
        ],
    })


def glucose_report_html(request, user_id):
    try:
        user = UserMaster.objects.get(user_id=user_id)
    except UserMaster.DoesNotExist:
        return render(request, "report_not_found.html", {"user_id": user_id})

    logs = _filter_logs_by_date(
        LogEntry.objects.filter(user=user).order_by('timestamp'),
        request.GET.get('from_date'),
        request.GET.get('to_date'),
    )

    report_data = {
        "user": {
            "user_id":         user.user_id,
            "first_name":      user.first_name,
            "middle_name":     user.middle_name,
            "last_name":       user.last_name,
            "gender":          user.gender,
            "dob":             str(user.dob),
            "mobile_number":   user.mobile_number,
            "address":         user.address,
            "isNewUser":       user.isNewUser,
            "profile_picture": request.build_absolute_uri(user.profile_picture.url) if user.profile_picture else None,
        },
        "logs": [
            {"glucose_value": log.glucose_value, "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S"), "note": log.note}
            for log in logs
        ],
    }

    return render(request, "glucose_report.html", {"report_json": json.dumps(report_data)})


def user_wise_view(request):
    return render(request, "user_wise_view.html", {"users": UserMaster.objects.all()})


# Device Master
class DeviceMasterViewSet(viewsets.ModelViewSet):
    queryset         = DeviceMaster.objects.all()
    serializer_class = DeviceMasterSerializer

    def create(self, request, *args, **kwargs):
        try:
            user = UserMaster.objects.get(user_id=request.data.get('user'))
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            device = serializer.save()
            logger.info(f"Device paired: device={device.device_serial_no}")
            user.isNewUser = False
            user.save()
            AuditLog.objects.create(user=user, device=device, action='DEVICE_ADDED', reason='Device paired successfully')

            data = serializer.data
            data['last_updated']   = None   #
            data['last_sync_date'] = None   # NEW data syncing date and timing.

            return Response({"status": "success", "message": "Device paired successfully", "data": data}, status=status.HTTP_201_CREATED)
        logger.warning(f"Device Pairing Failed:user_id={request.data.get('user')},errors={serializer.errors}")
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_409_CONFLICT)

    def list(self, request, *args, **kwargs):
        user_id = request.query_params.get('user')

        if not user_id:
            return Response({"status": "error", "message": "user parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        devices    = DeviceMaster.objects.filter(user=user)
        serializer = self.get_serializer(devices, many=True)
        data       = serializer.data

        for i, device in enumerate(devices):
            last_log = LogEntry.objects.filter(user=user, deviceid=device.device_serial_no).order_by('-id').first()
            data[i]['last_updated'] = timezone.localtime(device.updated_at) if last_log else None
            #data[i]['last_sync_date']= timezone.localtime(last_log.created_at) if last_log else None.    #need to check this
            data[i]['last_sync_date']= timezone.localtime(last_log.timestamp) if last_log else None

            if device.status == 'REMOVED':
                audit = AuditLog.objects.filter(device=device, action='DEVICE_REMOVED').order_by('-timestamp').first()
                data[i]['removed_reason']           = audit.reason           if audit else None
                data[i]['removed_at']               = timezone.localtime(audit.timestamp ) if audit else None
                data[i]['removed_additional_notes'] = audit.additional_notes if audit else None
            else:
                data[i]['removed_reason']           = None
                data[i]['removed_at']               = None
                data[i]['removed_additional_notes'] = None

        return Response({"status": "success", "data": data})

    @action(detail=False, methods=['get'], url_path='sensor-status')
    def sensor_status(self, request, *args, **kwargs):
        device_serial_no = request.query_params.get('device_serial_no')

        if not device_serial_no:
            return Response({"status": "error", "message": "device_serial_no is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            device = DeviceMaster.objects.get(device_serial_no=device_serial_no)
        except DeviceMaster.DoesNotExist:
            return Response({"status": "error", "message": "Device not found"}, status=status.HTTP_404_NOT_FOUND)

        removed_reason           = None
        removed_at               = None
        removed_additional_notes = None

        expiry_date    = device.assigned_at + timedelta(days=device.life_span_days)
        diff           = expiry_date - timezone.now()
        days_remaining = max(diff.days, 0)

        if device.status == 'REMOVED':
            device_status  = "REMOVED"
            days_remaining = 0
            audit = AuditLog.objects.filter(device=device, action='DEVICE_REMOVED').order_by('-timestamp').first()
            if audit:
                removed_reason           = audit.reason
                removed_at               = audit.timestamp
                removed_additional_notes = audit.additional_notes
        elif device.status == 'EXPIRED' or days_remaining <= 0:
            device_status  = "EXPIRED"
            days_remaining = 0
        elif days_remaining <= 3:
            device_status = "EXPIRING_SOON"
        else:
            device_status = "ACTIVE"

        return Response({
            "status": "success",
            "data": {
                "device_serial_no":          device.device_serial_no,
                "device_type":               device.device_type,
                "batch_number":              device.batch_number,
                "days_remaining":            days_remaining,
                "status":                    device_status,
                "life_span_days":            device.life_span_days,
                "assigned_at":               timezone.localtime(device.assigned_at),
                "expiry_date":               timezone.localtime(expiry_date),
                "removed_reason":            removed_reason,
                "removed_at":                timezone.localtime(removed_at) if removed_at else None,
                "removed_additional_notes":  removed_additional_notes,
            },
        })

    @action(detail=False, methods=['post'], url_path='remove')
    def remove(self, request, *args, **kwargs):
        device_serial_no = request.data.get('device_serial_no')
        user_id          = request.data.get('user')
        reason           = request.data.get('reason', '')
        additional_notes = request.data.get('additional_notes', '')

        if not device_serial_no or not user_id:
            return Response({"status": "error", "message": "device_serial_no and user are required"}, status=status.HTTP_400_BAD_REQUEST)

        if not reason:
            return Response({"status": "error", "message": "reason is required to remove a device"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            device = DeviceMaster.objects.get(device_serial_no=device_serial_no, user=user)
        except DeviceMaster.DoesNotExist:
            return Response({"status": "error", "message": "Device not found"}, status=status.HTTP_404_NOT_FOUND)

        if device.status == 'REMOVED':
            logger.warning(f"device remove attempt on already-removed device: serial={device_serial_no}")
            return Response({"status": "error", "message": "Device is already removed"}, status=status.HTTP_400_BAD_REQUEST)

        device.status = 'REMOVED'
        device.save()
        logger.info(f"Device removed: serial={device_serial_no},user_id={user_id},reason={reason}")
        AuditLog.objects.create(user=user, device=device, action='DEVICE_REMOVED', reason=reason, additional_notes=additional_notes)

        return Response({"status": "success", "message": "Device removed successfully"})


# Password Reset
import uuid
from django.core.exceptions import ValidationError
from .utils import generate_otp
from django.db import transaction


@method_decorator(csrf_exempt, name='dispatch')
class ResetPasswordViewSet(viewsets.ViewSet):
    MAX_OTP_ATTEMPTS = 5
    RESEND_COOLDOWN_SECONDS = 30

    def list(self, request):
        email_id = (request.query_params.get('email_id') or '').strip()

        if not email_id:
            return Response({'status': False, 'message': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = UserMaster.objects.get(email_id__iexact=email_id)
        except UserMaster.DoesNotExist:
            return Response({'status': False, 'message': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"reset_password list failed: email={email_id}, error={e}")
            return Response({'status': False, 'message': 'Something went wrong. Please try again.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({'status': True, 'message': 'User found.', 'user_id': user.user_id, 'email_id': user.email_id})

    def create(self, request):
        email_id = (request.data.get('email_id') or '').strip()
        user_id  = (request.data.get('user_id')  or '').strip()
        token    = (request.data.get('token')    or '').strip()
        password = request.data.get('password') or ''      # no .strip(), same as registration

        # ---------------- Step 1: send / resend OTP ----------------
        if email_id:
            try:
                user = UserMaster.objects.get(email_id__iexact=email_id)
            except UserMaster.DoesNotExist:
                return Response({'status': False, 'message': 'User not found.'},
                                status=status.HTTP_404_NOT_FOUND)
            except Exception as e:
                logger.error(f"reset_password lookup failed: email={email_id}, error={e}")
                return Response({'status': False, 'message': 'Something went wrong. Please try again.'},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            try:
                last_token = PasswordResetToken.objects.filter(user=user).order_by('-created_at').first()

                # Cooldown applies only if the last token is NOT locked.
                # A locked token (5 wrong attempts) may be resent immediately.
                if last_token and last_token.attempts < self.MAX_OTP_ATTEMPTS:
                    seconds_since_last = (timezone.now() - last_token.created_at).total_seconds()
                    if seconds_since_last < self.RESEND_COOLDOWN_SECONDS:
                        wait_remaining = int(self.RESEND_COOLDOWN_SECONDS - seconds_since_last)
                        logger.warning(f"OTP resend blocked: too soon user_id={user.user_id}, wait={wait_remaining}s")
                        return Response(
                            {'status': False,
                             'message': f'Please wait {wait_remaining} seconds before requesting another OTP.',
                             'retry_after_seconds': wait_remaining},
                            status=status.HTTP_429_TOO_MANY_REQUESTS,
                        )

                with transaction.atomic():
                    invalidated_count = PasswordResetToken.objects.select_for_update().filter(
                        user=user, is_used=False
                    ).update(is_used=True)

                    otp = generate_otp()
                    reset_token = PasswordResetToken.objects.create(
                        user       = user,
                        token      = uuid.uuid4(),
                        otp_code   = otp,
                        is_used    = False,
                        expires_at = timezone.now() + timedelta(minutes=10),
                    )

                logger.info(f"OTP token created: user_id={user.user_id}, invalidated_previous={invalidated_count}")
            except Exception as e:
                logger.error(f"OTP generation failed: email={email_id}, user_id={user.user_id}, error={e}")
                return Response({'status': False, 'message': 'Failed to generate OTP. Please try again.'},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            reset_link = f'{settings.BASE_URL}/api/reset-password/redirect/?userId={user.user_id}&token={reset_token.token}'
            try:
                email_html = render_to_string('reset_password_email.html', {
                    'user': user,
                    'otp': otp,
                    'reset_link': reset_link,
                    'expiry_minutes': 10,
                })
            except Exception as e:
                logger.error(f"reset password email template render failed: email={email_id}, error={e}")
                return Response({'status': False, 'message': 'Failed to prepare reset email.'},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            try:
                response = http_requests.post(
                    f"{settings.SMTP_SERVICE_URL}/smtp-kit/email/send/",
                    json={
                        "email":          [user.email_id],
                        "subject":        "Reset your password – CGM App",
                        "body":           "Click the link to reset your password.",
                        "template":       email_html,
                        "source_project": "CGM App",
                    },
                    timeout=10,
                )
                response.raise_for_status()
                logger.info(f"Password reset email sent: email={email_id}, user_id={user.user_id}")
            except Exception as e:
                logger.error(f"password reset SMTP failed: email={email_id}, error={e}")
                # If the email could not be sent, the new OTP is useless; invalidate it
                PasswordResetToken.objects.filter(pk=reset_token.pk).update(is_used=True)
                payload = {'status': False, 'message': 'Failed to send email. Please try again.'}
                if settings.DEBUG:
                    payload['error'] = str(e)          # visible only in dev
                return Response(payload, status=status.HTTP_502_BAD_GATEWAY)

            return Response({
                'status':  True,
                'message': 'Password reset email sent successfully.',
                'user_id': user.user_id,
                'token':   str(reset_token.token),
                'expires_in_seconds': 600,
                'resend_allowed_in_seconds': self.RESEND_COOLDOWN_SECONDS,
            })

        # ---------------- Step 2: apply new password ----------------
        if not all([user_id, token, password]):
            return Response(
                {'status': False, 'message': 'Provide either email_id or (user_id, token, password).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            uuid.UUID(token)
        except (ValueError, TypeError):
            logger.warning(f"password reset failed: malformed token user_id={user_id}")
            return Response({'status': False, 'message': 'Invalid or already used token.'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                # Row lock: a double-tap on "Reset password" cannot run twice
                try:
                    reset_token = (
                        PasswordResetToken.objects.select_for_update()
                        .select_related('user')
                        .get(user=user_id, token=token, is_used=False)
                    )
                except PasswordResetToken.DoesNotExist:
                    logger.warning(f"Password reset failed: invalid/used token user_id={user_id}")
                    return Response({'status': False, 'message': 'Invalid or already used token.'},
                                    status=status.HTTP_400_BAD_REQUEST)
                except (ValidationError, ValueError) as e:
                    logger.warning(f"password reset failed: bad token/user_id format user_id={user_id}, error={e}")
                    return Response({'status': False, 'message': 'Invalid or already used token.'},
                                    status=status.HTTP_400_BAD_REQUEST)

                if reset_token.expires_at and reset_token.expires_at < timezone.now():
                    logger.warning(f"password reset failed: expired token user_id={user_id}")
                    return Response({'status': False, 'message': 'Token has expired. Please request a new reset.'},
                                    status=status.HTTP_400_BAD_REQUEST)

                if not reset_token.otp_verified:
                    logger.warning(f"password reset failed: OTP not verified user_id={user_id}")
                    return Response({'status': False, 'message': 'Please verify the OTP before setting a new password.'},
                                    status=status.HTTP_400_BAD_REQUEST)

                # Validate with the user object so the similarity check works
                try:
                    validate_password(password, user=reset_token.user)
                except DjangoValidationError as e:
                    return Response(
                        {'status': False, 'message': 'Weak password.', 'errors': list(e.messages)},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                user = reset_token.user
                user.password = make_password(password)
                user.save(update_fields=['password', 'updated_at'])
                reset_token.is_used = True
                reset_token.save(update_fields=['is_used'])

        except Exception as e:
            logger.error(f"password reset failed: user_id={user_id}, error={e}")
            return Response({'status': False, 'message': 'Failed to reset password. Please try again.'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        logger.info(f"password reset successful: user_id={user_id}")
        return Response({'status': True, 'message': 'Password reset successfully.'})
    # verify OTP
    @action(detail=False, methods=['post'], url_path='verify_otp')
    def verify_otp(self, request):
        user_id  = (request.data.get('user_id')  or '').strip()
        otp_code = (request.data.get('otp_code') or '').strip()

        if not user_id or not otp_code:
            return Response(
                {'status': False, 'message': 'user_id and otp_code are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                # Row lock: parallel clicks are processed one after another
                reset_token = (
                    PasswordResetToken.objects.select_for_update()
                    .filter(user=user_id, is_used=False)
                    .order_by('-created_at')
                    .first()
                )

                if not reset_token:
                    logger.warning(f"OTP verify failed: no active token user_id={user_id}")
                    return Response(
                        {'status': False, 'message': 'No pending OTP request found. Please request a new OTP.'},
                        status=status.HTTP_404_NOT_FOUND,
                    )

                if reset_token.expires_at and reset_token.expires_at < timezone.now():
                    logger.warning(f"OTP verify failed: expired user_id={user_id}")
                    return Response(
                        {'status': False, 'message': 'OTP has expired. Please request a new one.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                code_matches = secrets.compare_digest(reset_token.otp_code or '', otp_code)

                success_response = Response({
                    'status':  True,
                    'message': 'OTP verified successfully. You may now reset your password.',
                    'user_id': reset_token.user.user_id,
                    'token':   str(reset_token.token),
                })

                # Already verified (double-click on the correct OTP) -> return success again
                if reset_token.otp_verified:
                    if code_matches:
                        return success_response
                    return Response(
                        {'status': False, 'message': 'Invalid OTP.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Locked from earlier wrong attempts
                if reset_token.attempts >= self.MAX_OTP_ATTEMPTS:
                    logger.warning(f"OTP verify failed: too many attempts user_id={user_id}")
                    return Response(
                        {'status': False,
                         'message': 'Too many incorrect attempts. Please request a new OTP.',
                         'locked': True},
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )

                # Wrong OTP
                if not code_matches:
                    reset_token.attempts += 1
                    reset_token.save(update_fields=['attempts'])
                    remaining = self.MAX_OTP_ATTEMPTS - reset_token.attempts
                    logger.warning(
                        f"OTP verify failed: wrong code user_id={user_id}, attempts={reset_token.attempts}"
                    )
                    if remaining <= 0:   # this was the 5th wrong attempt -> lock now
                        return Response(
                            {'status': False,
                             'message': 'Too many incorrect attempts. Please request a new OTP.',
                             'locked': True},
                            status=status.HTTP_429_TOO_MANY_REQUESTS,
                        )
                    return Response(
                        {'status': False,
                         'message': f'Invalid OTP. {remaining} attempt(s) remaining.',
                         'remaining_attempts': remaining,
                         'locked': False},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Correct OTP
                reset_token.otp_verified = True
                reset_token.save(update_fields=['otp_verified'])

            logger.info(f"OTP verified successfully: user_id={user_id}")
            return success_response

        except Exception as e:
            logger.error(f"OTP verify failed unexpectedly: user_id={user_id}, error={e}")
            return Response(
                {'status': False, 'message': 'Something went wrong. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

def reset_password_redirect_page(request):
    user_id = request.GET.get('userId')
    token = request.GET.get('token')
    try:
        reset_token = PasswordResetToken.objects.get(user_id=user_id, token=token)
    except (PasswordResetToken.DoesNotExist, ValueError, ValidationError):
        return render(request, 'reset_invalid.html', {
            'message': 'This reset link is invalid.'
        })

    if reset_token.is_used:
        return render(request, 'reset_invalid.html', {
            'message': 'This reset link has already been used. Please request a new one.'
        })

    if reset_token.expires_at and reset_token.expires_at < timezone.now():
        return render(request, 'reset_invalid.html', {
            'message': 'This reset link has expired. Please request a new one.'
        })
    deep_link = f'projectx://socialauth?userId={user_id}&token={token}'
    return render(request, 'reset_redirect.html', {'deep_link': deep_link})
# App Media
@method_decorator(csrf_exempt, name='dispatch')
class AppMediaViewSet(viewsets.ViewSet):
    def list(self, request):
        slots      = AppMedia.objects.all().order_by('order')
        serializer = AppMediaSerializer(slots, many=True, context={'request': request})
        return Response({"status": "success", "data": serializer.data})

    def create(self, request):
        file      = request.FILES.get('file')
        file_type = request.data.get('type')
        order     = request.data.get('order')
        label     = request.data.get('label', '')
        link      = request.data.get('link', '')

        # 1. Validate order
        try:
            order = int(order)
        except (TypeError, ValueError):
            return Response({
                "status": "error",
                "message": "order must be a valid integer"
            }, status=status.HTTP_400_BAD_REQUEST)

        # 2. Validate required fields
        if not file or not file_type:
            return Response({
                "status": "error",
                "message": "file and type are required"
            }, status=status.HTTP_400_BAD_REQUEST)

        # 3. Validate duration
        try:
            duration = int(request.data.get('duration', 5))
            if duration <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response({
                "status": "error",
                "message": "duration must be a positive integer"
            }, status=status.HTTP_400_BAD_REQUEST)

        # 4. Get or create slot
        slot, created = AppMedia.objects.get_or_create(order=order)

        # 5. Delete old file safely
        if slot.file:
            try:
                if os.path.isfile(slot.file.path):
                    os.remove(slot.file.path)
            except Exception:
                pass

        # 6. Update slot
        slot.file     = file
        slot.type     = file_type
        slot.duration = duration
        slot.label    = label
        slot.link     = link
        slot.save()

        serializer = AppMediaSerializer(slot, context={'request': request})
        return Response({
            "status":  "success",
            "message": "Slot created" if created else f"Slot {order} updated",
            "data":    serializer.data,
        }, status=status.HTTP_200_OK)


def app_media_login(request):
    if request.method == 'POST':
        admin_id = request.POST.get('admin_id', '').strip()
        password = request.POST.get('password', '').strip()

        if admin_id == MEDIA_ADMIN_ID and password == MEDIA_ADMIN_PASSWORD:
            request.session['media_admin_logged_in'] = True
            return redirect('/app-media/upload/')

        return render(request, 'app_media_login.html', {'error': 'Invalid credentials'})

    return render(request, 'app_media_login.html')


def app_media_upload(request):
    admin_id = request.GET.get('id')
    password = request.GET.get('password')

    if admin_id != MEDIA_ADMIN_ID or password != MEDIA_ADMIN_PASSWORD:
        return render(request, 'app_media_login.html', {'error': 'Invalid credentials'})

    if request.method == 'POST':
        file      = request.FILES.get('file')
        file_type = request.POST.get('type')
        order     = int(request.POST.get('order'))
        duration  = int(request.POST.get('duration', 5))
        label     = request.POST.get('label', '')
        link      = request.POST.get('link', '')

        slot, created = AppMedia.objects.get_or_create(order=order)
        if file:
            slot.file = file
        slot.type     = file_type
        slot.duration = duration
        slot.label    = label
        slot.link     = link
        slot.save()

    slots = AppMedia.objects.all().order_by('order')
    return render(request, 'app_media_upload.html', {'slots': slots})

# Caregiver
class CaregiverMasterViewSet(viewsets.ViewSet):

    def list(self, request):
        user_id = request.query_params.get('user')

        if not user_id:
            return Response({"status": "error", "message": "user parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        caregivers = CaregiverMaster.objects.filter(user=user).exclude(status='REMOVED').order_by('-created_at')
        serializer = CaregiverMasterSerializer(caregivers, many=True)
        return Response({"status": "success", "count": caregivers.count(), "data": serializer.data})

    def create(self, request):
        user_id          = request.data.get('user')
        full_name        = request.data.get('full_name')
        email_id         = request.data.get('email_id', '').lower().strip()
        relationship     = request.data.get('relationship')
        mobile_number    = request.data.get('mobile_number')
        can_view_glucose = request.data.get('can_view_glucose', True)
        can_view_alerts  = request.data.get('can_view_alerts',  True)
        can_view_reports = request.data.get('can_view_reports', True)
        can_view_trends  = request.data.get('can_view_trends',  True)

        if not all([user_id, full_name, email_id, relationship]):
            return Response(
                {"status": "error", "message": "user, full_name, email_id and relationship are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        if email_id == user.email_id:
            logger.warning(f"Caregiver invite failed: self-invite user_id={user_id}")
            return Response({"status": "error", "message": "You cannot add yourself as a caregiver"}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Lock the user row so parallel requests can't both pass the limit check
            UserMaster.objects.select_for_update().get(pk=user.pk)

            existing = CaregiverMaster.objects.filter(user=user, email_id=email_id).first()

            # FIX 1: guard against existing being None
            if existing and existing.status in ['PENDING', 'ACTIVE']:
                logger.warning(f"Caregiver invite failed: already exists user_id={user_id}")
                return Response({"status": "error", "message": "This caregiver has already been added"}, status=status.HTTP_409_CONFLICT)

            # FIX 2: .count() so we compare an int, not a queryset
            current_count = CaregiverMaster.objects.filter(
                user=user, status__in=['PENDING', 'ACTIVE']
            ).count()

            if current_count >= MAX_CAREGIVERS_PER_USER:
                logger.warning(f"Caregiver invite failed: limit reached user_id={user_id}, count={current_count}")
                return Response({
                    "status":         "error",
                    "message":        f"You can add a maximum of {MAX_CAREGIVERS_PER_USER} caregivers. Please remove an existing caregiver to add a new one.",
                    "max_caregivers": MAX_CAREGIVERS_PER_USER,   # FIX 3
                    "current_count":  current_count,
                }, status=status.HTTP_400_BAD_REQUEST)

            if existing:  # previously REMOVED -> re-invite
                existing.full_name        = full_name
                existing.relationship     = relationship
                existing.mobile_number    = mobile_number
                existing.status           = 'PENDING'
                existing.can_view_glucose = can_view_glucose
                existing.can_view_alerts  = can_view_alerts
                existing.can_view_reports = can_view_reports
                existing.can_view_trends  = can_view_trends
                existing.invitation_token = uuid.uuid4()
                existing.save()
                caregiver = existing
            else:
                caregiver = CaregiverMaster.objects.create(
                    user=user, full_name=full_name, email_id=email_id,
                    mobile_number=mobile_number, relationship=relationship, status='PENDING',
                    can_view_glucose=can_view_glucose, can_view_alerts=can_view_alerts,
                    can_view_reports=can_view_reports, can_view_trends=can_view_trends,
                )

        response = None
        email_error= None
        try:
            invite_link   = f"{settings.BASE_URL}/api/caregiver/accept/{caregiver.invitation_token}/"
            html_template = render_to_string('caregiver_invitation_email.html', {'caregiver': caregiver, 'user': user, 'invite_link': invite_link})
            response = http_requests.post(
                f"{settings.SMTP_SERVICE_URL}/smtp-kit/email/send/",
                json={
                    "source_project": "cgm-service",
                    "email":          [email_id],
                    "subject":        f"{user.first_name} {user.last_name} invited you as a caregiver",
                    "body":           f"Accept invitation: {invite_link}",
                    "template":       html_template,
                },
                timeout=10,
            )
            if response.ok:
                logger.info(f"Caregiver invite sent: user_id={user_id}, caregiver_email={email_id}, status={response.status_code}")
            else:
                email_error=f"SMTP service returned {response.status_code}:{response.text[:300]}"
                logger.error(
                    f"Caregiver invite SMTP returned failure: user_id={user_id}, "
                    f"caregiver_email={email_id}, status={response.status_code}, body={response.text}"
                )
        except Exception as e:
            email_error= f"{type(e).__name__}:{e}"
            logger.error(f"Caregiver invite SMTP failed: user_id={user_id}, error={e}")

        email_status = "sent" if (response is not None and response.ok) else "failed"
        serializer = CaregiverMasterSerializer(caregiver)
        resp = {
            "status":       "success",
            "message":      "Invitation sent successfully" if email_status == "sent" else "Caregiver added, but invitation email could not be sent",
            "email_status": email_status,
            "data":         serializer.data,
        }
        if settings.DEBUG and email_error:
            resp["email_error"] = email_error   # only visible in local/dev
        return Response(resp, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='accept_invitation')
    def accept_invitation(self, request):
        caregiver_id = request.data.get('caregiver_id')

        if not caregiver_id:
            return Response({"status": "error", "message": "caregiver_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            caregiver = CaregiverMaster.objects.get(id=caregiver_id)
        except CaregiverMaster.DoesNotExist:
            return Response({"status": "error", "message": "Caregiver not found"}, status=status.HTTP_404_NOT_FOUND)

        if caregiver.status == 'ACTIVE':
            return Response({"status": "info", "message": "Invitation already accepted"})

        if caregiver.status == 'REMOVED':
            return Response({"status": "error", "message": "This invitation is no longer valid"}, status=status.HTTP_400_BAD_REQUEST)

        caregiver.status = 'ACTIVE'
        caregiver.save()

        return Response({"status": "success", "message": "Invitation accepted. You are now a caregiver.", "data": CaregiverMasterSerializer(caregiver).data})

    @action(detail=False, methods=['post'], url_path='accept_by_token')
    def accept_by_token(self, request):
        token = request.data.get('token')

        if not token:
            logger.warning(f"Caregiver invite expired: token={token}")
            return Response({"status": "error", "message": "token is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            caregiver = CaregiverMaster.objects.select_related('user').get(invitation_token=token)
        except CaregiverMaster.DoesNotExist:
            return Response({"status": "error", "message": "Invalid token"}, status=status.HTTP_404_NOT_FOUND)

        if timezone.now() > caregiver.created_at + timedelta(days=CAREGIVER_INVITE_EXPIRY_DAYS):
            logger.warning(f"Caregiver invite expired: token{token},caregiver_id={caregiver.id}")
            return Response({"status": "error", "message": "Invitation has expired"}, status=status.HTTP_410_GONE)

        if caregiver.status == 'REMOVED':
            return Response({"status": "error", "message": "This invitation is no longer valid"}, status=status.HTTP_410_GONE)

        if caregiver.status == 'ACTIVE':
            logger.info(f"Caregiver invite already accepted:caregiver_id={caregiver.id}")
            return Response({"status": "info", "message": "Invitation already accepted"})

        caregiver.status = 'ACTIVE'
        caregiver.save()
        logger.info(f"")
        return Response({"status": "success", "message": "You are now a caregiver.", "data": CaregiverMasterSerializer(caregiver).data})

    @action(detail=False, methods=['post'], url_path='remove')
    def remove(self, request):
        user_id      = request.data.get('user')
        caregiver_id = request.data.get('caregiver_id')

        if not user_id or not caregiver_id:
            return Response({"status": "error", "message": "user and caregiver_id are required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            caregiver = CaregiverMaster.objects.get(id=caregiver_id, user__user_id=user_id)
        except CaregiverMaster.DoesNotExist:
            return Response({"status": "error", "message": "Caregiver not found"}, status=status.HTTP_404_NOT_FOUND)

        if caregiver.status == 'REMOVED':
            logger.info(f"Caregiver removed:caregiver_id={caregiver_id},user_id={user_id}")
            return Response({"status": "error", "message": "Caregiver already removed"}, status=status.HTTP_409_CONFLICT)

        caregiver.status = 'REMOVED'
        caregiver.save()
        AuditLog.objects.create(
            user=caregiver.user,
            device=None,
            action='CAREGIVER_REMOVED',
            reason=f"Caregiver {caregiver.full_name} removed by user {user_id}"
        )
        return Response({"status": "success", "message": "Caregiver removed successfully"})
    @action(detail=False,methods=['get'],url_path='caregiver-patients')
    def caregiver_patients(self,request):
        email_id = (request.query_params.get('email_id') or '').lower().strip()
        if not email_id:
            return Response(
                {"status":"error","message":"email id is required"},status=status.HTTP_400_BAD_REQUEST,
            )
        shares = (CaregiverMaster.objects.filter(email_id__iexact=email_id,status__in=["ACTIVE","PENDING"]).select_related('user').order_by('-created_at'))
        data=[
            {
            "caregiver_entry_id": entry.id,
            "user_id":            entry.user.user_id,
            "first_name":         entry.user.first_name,
            "last_name":          entry.user.last_name,
            "email_id":           entry.user.email_id,
            "mobile_number":      entry.user.mobile_number,
            "relationship":       entry.relationship,
            "status":             entry.status,
            "can_view_glucose":   entry.can_view_glucose,
            "can_view_alerts":    entry.can_view_alerts,
            "can_view_reports":   entry.can_view_reports,
            "can_view_trends":    entry.can_view_trends,
            "shared_since":       entry.created_at,

            }
            for entry in shares
        ]
        logger.info(f"Caregiver-patients fecthed: identifier={email_id}")
        return Response({"status":"success","count":len(data),"patients":data})
def caregiver_accept_page(request, token):
    try:
        caregiver = CaregiverMaster.objects.select_related('user').get(invitation_token=token)
    except CaregiverMaster.DoesNotExist:
        return render(request, "caregiver_invalid.html", {"message": "This invitation link is invalid."})

    if timezone.now() > caregiver.created_at + timedelta(days=CAREGIVER_INVITE_EXPIRY_DAYS):
        return render(request, "caregiver_invalid.html", {"message": "This invitation link has expired."})

    if caregiver.status == 'REMOVED':
        return render(request, "caregiver_invalid.html", {"message": "This invitation is no longer valid."})

    if caregiver.status == 'ACTIVE':
        return render(request, "caregiver_already_accepted.html", {"caregiver": caregiver})

    return render(request, "caregiver_accept.html", {
        "caregiver":      caregiver,
        "user":           caregiver.user,
        "token":          token,
        "app_deep_link":  f"innoiqcgm:/api/caregiver/accept/{token}",
        "play_store_url": "https://play.google.com/store/apps/details?id=com.innoiq.cgm",
        "app_store_url":  "https://apps.apple.com/app/innoiq-cgm/id123456",
    })


# Terms & Conditions / IFU

class TermsAndConditionsViewSet(viewsets.ViewSet):

    def list(self, request):
        try:
            terms = TermsAndConditions.objects.filter(is_active=True).latest('created_at')
        except TermsAndConditions.DoesNotExist:
            return Response({"status": "error", "message": "No active terms found"}, status=status.HTTP_404_NOT_FOUND)

        return Response({"status": "success", "data": TermsAndConditionsSerializer(terms).data})

    def create(self, request):
        if request.query_params.get('admin_id') != MEDIA_ADMIN_ID or request.query_params.get('password') != MEDIA_ADMIN_PASSWORD:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

        terms_content           = request.data.get('terms_content')
        ifu_content             = request.data.get('ifu_content')
        terms_confirmation_text = request.data.get('terms_confirmation_text')
        ifu_confirmation_text   = request.data.get('ifu_confirmation_text')

        if not terms_content and not ifu_content:
            return Response({"status": "error", "message": "At least one of terms_content or ifu_content is required"}, status=status.HTTP_400_BAD_REQUEST)

        if terms_content and not terms_confirmation_text:
            return Response({"status": "error", "message": "terms_confirmation_text is required when terms_content is provided"}, status=status.HTTP_400_BAD_REQUEST)

        if ifu_content and not ifu_confirmation_text:
            return Response({"status": "error", "message": "ifu_confirmation_text is required when ifu_content is provided"}, status=status.HTTP_400_BAD_REQUEST)

        doc_type = 'BOTH' if (terms_content and ifu_content) else ('TERMS' if terms_content else 'IFU')

        TermsAndConditions.objects.filter(is_active=True).update(is_active=False)
        terms = TermsAndConditions.objects.create(
            type=doc_type, terms_content=terms_content, ifu_content=ifu_content,
            terms_confirmation_text=terms_confirmation_text, ifu_confirmation_text=ifu_confirmation_text,
            is_active=True,
        )

        return Response({"status": "success", "message": f"Terms v{terms.version} created successfully", "data": TermsAndConditionsSerializer(terms).data}, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        if request.query_params.get('admin_id') != MEDIA_ADMIN_ID or request.query_params.get('password') != MEDIA_ADMIN_PASSWORD:
            return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            terms = TermsAndConditions.objects.get(pk=pk)
        except TermsAndConditions.DoesNotExist:
            return Response({"status": "error", "message": "Terms not found"}, status=status.HTTP_404_NOT_FOUND)

        terms.terms_content           = request.data.get('terms_content',           terms.terms_content)
        terms.ifu_content             = request.data.get('ifu_content',             terms.ifu_content)
        terms.terms_confirmation_text = request.data.get('terms_confirmation_text', terms.terms_confirmation_text)
        terms.ifu_confirmation_text   = request.data.get('ifu_confirmation_text',   terms.ifu_confirmation_text)
        terms.save()

        return Response({"status": "success", "message": f"Terms v{terms.version} updated successfully", "data": TermsAndConditionsSerializer(terms).data})


# User Consent

class UserConsentViewSet(viewsets.ViewSet):

    @action(detail=False, methods=['post'], url_path='accept')
    def accept(self, request):
        user_id           = request.data.get('user')
        is_terms_accepted = request.data.get('is_terms_accepted', False)
        is_ifu_accepted   = request.data.get('is_ifu_accepted',   False)

        if not user_id:
            return Response({"status": "error", "message": "user is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            active_terms = TermsAndConditions.objects.filter(is_active=True).latest('created_at')
        except TermsAndConditions.DoesNotExist:
            return Response({"status": "error", "message": "No active terms found"}, status=status.HTTP_404_NOT_FOUND)

        consent, created = UserConsent.objects.get_or_create(
            user=user, terms=active_terms,
            defaults={
                'is_terms_accepted': is_terms_accepted,
                'is_ifu_accepted':   is_ifu_accepted,
                'terms_accepted_at': timezone.now() if is_terms_accepted else None,
                'ifu_accepted_at':   timezone.now() if is_ifu_accepted   else None,
            },
        )

        if not created:
            if 'is_terms_accepted' in request.data:
                consent.is_terms_accepted = is_terms_accepted
                consent.terms_accepted_at = timezone.now() if is_terms_accepted else None
            if 'is_ifu_accepted' in request.data:
                consent.is_ifu_accepted = is_ifu_accepted
                consent.ifu_accepted_at = timezone.now() if is_ifu_accepted else None
            consent.save()

        return Response({"status": "success", "message": "Consent saved successfully", "data": UserConsentSerializer(consent).data})

    @action(detail=False, methods=['get'], url_path='status')
    def status(self, request):
        user_id = request.query_params.get('user')

        if not user_id:
            return Response({"status": "error", "message": "user is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            active_terms = TermsAndConditions.objects.filter(is_active=True).latest('created_at')
        except TermsAndConditions.DoesNotExist:
            return Response({"status": "error", "message": "No active terms found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            consent = UserConsent.objects.get(user=user, terms=active_terms)
            return Response({"status": "success", "data": UserConsentSerializer(consent).data})
        except UserConsent.DoesNotExist:
            return Response({
                "status": "success",
                "data": {
                    "is_terms_accepted": False,
                    "is_ifu_accepted":   False,
                    "terms_version":     active_terms.version,
                    "message":           "User has not accepted current terms",
                },
            })


# Audit Log
class AuditLogViewSet(viewsets.ViewSet):

    def list(self, request):
        logs      = AuditLog.objects.select_related('user', 'device').order_by('-timestamp')
        user_id   = request.query_params.get('user')
        action    = request.query_params.get('action')
        from_date = request.query_params.get('from_date')
        to_date   = request.query_params.get('to_date')

        if user_id:
            logs = logs.filter(user__user_id=user_id)
        if action:
            logs = logs.filter(action=action)                   # ← bug fixed
        if from_date:
            from_dt = parse_datetime(from_date) or parse_date(from_date)
            if from_dt:
                logs = logs.filter(timestamp__gte=from_dt)
        if to_date:
            to_dt = parse_datetime(to_date) or parse_date(to_date)
            if to_dt:
                logs = logs.filter(timestamp__lte=to_dt)

        page_size   = min(int(request.query_params.get('page_size', 50)), 200)
        paginator   = Paginator(logs, page_size)
        page_obj    = paginator.get_page(request.query_params.get('page', 1))

        data = [
            {
                "id":               log.id,
                "action":           log.action,
                "reason":           log.reason,
                "additional_notes": log.additional_notes,
                "timestamp":        timezone.localtime(log.timestamp),
                "user": {
                    "user_id":    log.user.user_id    if log.user else None,
                    "first_name": log.user.first_name if log.user else None,
                    "last_name":  log.user.last_name  if log.user else None,
                    "email_id":   log.user.email_id   if log.user else None,
                },
                "device": {
                    "device_serial_no": log.device.device_serial_no if log.device else None,
                    "device_type":      log.device.device_type      if log.device else None,
                } if log.device else None,
            }
            for log in page_obj
        ]

        return Response({
            "status":      "success",
            "total":       paginator.count,
            "total_pages": paginator.num_pages,
            "page":        page_obj.number,
            "page_size":   page_size,
            "data":        data,
        })


class ReportViewSet(viewsets.ViewSet):
    _GLUCOSE_STAT_METRIC_LABELS = [
        ("number_of_monitored_data", "Number of Monitored Data"),
        ("mean_mbg",                 "Mean (MBG, mg/dL)"),
        ("sd_sdbg",                  "Standard Deviation (SDBG, mg/dL)"),
        ("gv_cv_pct",                "GV (CV%)"),
        ("highest_glucose",          "The Highest Value of Glucose (mg/dL)"),
        ("lowest_glucose",           "The Lowest Value of Glucose (mg/dL)"),
        ("lage",                     "Largest Amplitude of Glycemic Excursion (LAGE, mg/dL)"),
        ("mage",                     "Mean Amplitude of Glycemic Excursion (MAGE, mg/dL)"),
        ("pct_very_high",            "% Time in Very High (>250 mg/dL)"),
        ("pct_high",                 "% Time in High (180-250 mg/dL)"),
        ("pct_target",               "% Time in Target Range (70-180 mg/dL)"),
        ("pct_low",                  "% Time in Low (54-70 mg/dL)"),
        ("pct_very_low",             "% Time in Very Low (<54 mg/dL)"),
        ("pct_tar",                  "% Time above Range (TAR)"),
        ("pct_tir",                  "% Time in Range (TIR)"),
        ("pct_tbr",                  "% Time below Range (TBR)"),
        ("low_bg_events",            "Low BG Events"),
        ("high_bg_events",           "High BG Events"),
    ]

    def list(self, request):
        return Response({
            "status": "success",
            "endpoints": {
                "data_check":                   "GET /api/reports/data-check/?user=&from_date=&to_date=",
                "avg_glucose":                  "GET /api/reports/avg-glucose/?user=&from_date=&to_date=",
                "time_in_range":                "GET /api/reports/time-in-range/?user=&from_date=&to_date=&low=70&high=180",
                "glucose_trends":               "GET /api/reports/glucose-trends/?user=&from_date=&to_date=",
                "weekly_breakdown":             "GET /api/reports/weekly-breakdown/?user=&from_date=&to_date=",
                "nocturnal_glucose_statistics": "GET /api/reports/nocturnal-glucose-statistics/?user=&from_date=&to_date=&night_start=22&night_end=6",
            }
        })

    def _get_user_and_logs(self,params):
        user_id=params.get('user')
        from_date=params.get('from_date')
        to_date=params.get('to_date')

        if not user_id:
            return None,None,Response(
                {"status":"error",
                 "message":"user parameter is required"
                 },status=status.HTTP_400_BAD_REQUEST
            )
        try:
            user=UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return None,None,Response(
                {"status":"error",
                 "message":"User not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        logs= _filter_logs_by_date(LogEntry.objects.filter(user=user).order_by('timestamp'),
                                   from_date,
                                   to_date,
                                   )
        return user,logs,None

    @staticmethod
    def _no_logs_response(message="No readings found for the give date range"):
        return Response({
            "status":"error",
            "message":message,
        },status=status.HTTP_404_NOT_FOUND)

    @staticmethod
    def _get_time_in_range(logs, total, low=70.0, high=180.0):
        in_range    = logs.filter(glucose_value__gte=low, glucose_value__lte=high).count()
        below_range = logs.filter(glucose_value__lt=low).count()
        above_range = logs.filter(glucose_value__gt=high).count()
        return {
            "time_in_range_pct": round((in_range    / total) * 100, 1),
            "below_range_pct":   round((below_range / total) * 100, 1),
            "above_range_pct":   round((above_range / total) * 100, 1),
            "in_range_count":    in_range,
            "below_range_count": below_range,
            "above_range_count": above_range,
        }

    @staticmethod
    def _get_estimated_hba1c(logs, avg_glucose, min_days=3):

        monitoring_days = logs.values('timestamp__date').distinct().count()
        hba1c_eligible  = monitoring_days >= min_days

        if hba1c_eligible:
            # eHbA1c estimated formula: (avg_glucose + 46.7) / 28.7
            estimated_hba1c = round((avg_glucose + 46.7) / 28.7, 1)
            hba1c_message   = None
        else:
            estimated_hba1c = None
            hba1c_message   = (
                f"At least {min_days} days of data are required to estimate eHbA1c. "
                f"Currently {monitoring_days} day(s) of data available."
            )

        return {
            "estimated_hba1c": estimated_hba1c,
            "hba1c_eligible":  hba1c_eligible,
            "hba1c_message":   hba1c_message,
            "monitoring_days": monitoring_days,
        }

    # Glucose Statistics table
    @staticmethod
    def _population_stdev(values):
        if len(values) < 2:
            return 0.0
        return round(statistics.pstdev(values), 1)

    @staticmethod
    def _compute_mage(values):
        if len(values) < 3:
            return 0.0

        sd = statistics.pstdev(values)
        if sd == 0:
            return 0.0

        # 1. Find turning points (local maxima / minima) in chronological order
        turning_points = [values[0]]
        for i in range(1, len(values) - 1):
            prev_v, curr_v, next_v = values[i - 1], values[i], values[i + 1]
            if (curr_v > prev_v and curr_v >= next_v) or (curr_v < prev_v and curr_v <= next_v):
                turning_points.append(curr_v)
        turning_points.append(values[-1])

        # 2. Amplitudes between consecutive turning points, keep those > 1 SD
        amplitudes = []
        for i in range(len(turning_points) - 1):
            diff = abs(turning_points[i + 1] - turning_points[i])
            if diff > sd:
                amplitudes.append(diff)

        if not amplitudes:
            return 0.0
        return round(statistics.fmean(amplitudes), 1)

    @staticmethod
    def _count_bg_events(readings, condition, min_duration_minutes=15, max_gap_minutes=20):
        events = 0
        run_start = None
        run_end = None

        def _close_run():
            nonlocal events
            if run_start is None:
                return
            duration = (run_end - run_start).total_seconds() / 60
            if duration >= min_duration_minutes or run_start == run_end:
                events += 1

        for ts, gv in readings:
            if condition(gv):
                if run_start is None:
                    run_start = ts
                    run_end = ts
                elif (ts - run_end).total_seconds() / 60 <= max_gap_minutes:
                    run_end = ts
                else:
                    _close_run()
                    run_start = ts
                    run_end = ts
            else:
                _close_run()
                run_start = None
                run_end = None

        _close_run()
        return events

    def _compute_glucose_statistics_for_period(self, period_logs):
        readings = list(period_logs.order_by('timestamp').values_list('timestamp', 'glucose_value'))
        total = len(readings)

        if total == 0:
            return None

        values = [gv for _, gv in readings]

        mean_bg = round(statistics.fmean(values), 1)
        sd_bg   = self._population_stdev(values)
        cv_pct  = round((sd_bg / mean_bg) * 100, 1) if mean_bg else 0.0
        highest = max(values)
        lowest  = min(values)
        lage    = round(highest - lowest, 1)
        mage    = self._compute_mage(values)

        very_high_count = sum(1 for v in values if v > 250)
        high_count      = sum(1 for v in values if 180 < v <= 250)
        target_count    = sum(1 for v in values if 70 <= v <= 180)
        low_count       = sum(1 for v in values if 54 <= v < 70)
        very_low_count  = sum(1 for v in values if v < 54)

        def _pct(c):
            return round((c / total) * 100, 1)

        low_events  = self._count_bg_events(readings, lambda v: v < 70)
        high_events = self._count_bg_events(readings, lambda v: v > 250)

        return {
            "number_of_monitored_data": total,
            "mean_mbg":                 mean_bg,
            "sd_sdbg":                  sd_bg,
            "gv_cv_pct":                cv_pct,
            "highest_glucose":         highest,
            "lowest_glucose":          lowest,
            "lage":                    lage,
            "mage":                    mage,
            "pct_very_high":           _pct(very_high_count),
            "pct_high":                _pct(high_count),
            "pct_target":              _pct(target_count),
            "pct_low":                 _pct(low_count),
            "pct_very_low":            _pct(very_low_count),
            "pct_tar":                 round(_pct(very_high_count) + _pct(high_count), 1),
            "pct_tir":                 _pct(target_count),
            "pct_tbr":                 round(_pct(low_count) + _pct(very_low_count), 1),
            "low_bg_events":           low_events,
            "high_bg_events":          high_events,
        }

    def _build_glucose_statistics_table(self, logs, from_date, to_date, night_start, night_end):
        columns = []
        current = from_date
        while current <= to_date:
            night_start_dt = make_aware(dt.datetime.combine(current, dt.time(hour=night_start)))
            night_end_dt   = make_aware(dt.datetime.combine(current + timedelta(days=1), dt.time(hour=night_end)))

            night_logs = logs.filter(timestamp__gte=night_start_dt, timestamp__lt=night_end_dt)
            day_stats  = self._compute_glucose_statistics_for_period(night_logs)

            columns.append({
                "date":  current.strftime("%Y-%m-%d"),   # full date, e.g. "2026-06-29"
                "stats": day_stats,   # None if no readings that night
            })
            current += timedelta(days=1)

        return columns

    #data validation check
    @action(detail=False,methods=['get'],url_path='data-check')
    def data_check(self,request):
        user,logs,err=self._get_user_and_logs(request.query_params)
        if err:
            return err
        total =logs.count()
        has_data=total>0
        response_data={
            "status":"success",
            "has_data":has_data,
            "total_readings":total,
        }
        if has_data:
            response_data["message"]="Data available"
        else:
            bounds=user.logentry_set.aggregate(
                earliest=Min('timestamp'),
                latest=Max('timestamp')
            )
            if bounds["earliest"]:
                earliest_str=bounds["earliest"].strftime('%b %d,%Y')
                response_data["message"]=(
                    f"Clinical data for your CGM is only available from {earliest_str}."
                    f"Please select a date within the supported range."
                )
                response_data["available_from"]=bounds["earliest"].date()
                response_data["available_to"]=bounds["latest"].date()
            else:
                response_data["message"]="No readings found for this user"
        return Response(response_data)

    #glucose avg
    @action(detail=False, methods=['get'], url_path='avg-glucose')
    def avg_glucose(self,request):
        user,logs,err=self._get_user_and_logs(request.query_params)
        if err:
            return err
        total=logs.count()
        if total == 0:
            return self._no_logs_response("No reading Found for the given date range")

        stats=logs.aggregate(
            avg=Avg('glucose_value'),
            max=Max('glucose_value'),
            min=Min('glucose_value'),
        )
        avg_glucose = round(stats['avg'], 1)

        # eHbA1c requires at least MIN_DAYS_FOR_HBA1C distinct days of readings
        hba1c_data      = self._get_estimated_hba1c(logs, avg_glucose)
        estimated_hba1c = hba1c_data["estimated_hba1c"]
        hba1c_eligible  = hba1c_data["hba1c_eligible"]
        hba1c_message   = hba1c_data["hba1c_message"]
        monitoring_days = hba1c_data["monitoring_days"]

        tir = self._get_time_in_range(logs, total)
        logger.info(f"Report avg-glucose: user_id={user.user_id}, avg={avg_glucose}")

        #alert
        total_alerts = 0
        alert_qs = Alert.objects.filter(user=user)  # no .count() here
        from_date_str = request.query_params.get('from_date')
        to_date_str   = request.query_params.get('to_date')
        if from_date_str:
            from_dt = parse_datetime(from_date_str) or parse_date(from_date_str)
            if from_dt:
                alert_qs = alert_qs.filter(created_at__gte=from_dt)
        if to_date_str:
            to_dt = parse_datetime(to_date_str) or parse_date(to_date_str)
            if to_dt:
                alert_qs = alert_qs.filter(created_at__lte=to_dt)
        total_alerts = alert_qs.count()
        high_alerts=alert_qs.filter(severity='HIGH').count()
        low_alerts=alert_qs.filter(severity='LOW').count()
        return Response({
            "status": "success",
            "data": {
                "avg_glucose":      avg_glucose,
                "max_glucose":      stats['max'],
                "min_glucose":      stats['min'],
                "estimated_hba1c":  estimated_hba1c,
                "hba1c_eligible":   hba1c_eligible,
                "hba1c_message":    hba1c_message,
                "monitoring_days":  monitoring_days,
                "total_readings":   total,
                "total_alerts":     total_alerts,
                "time_in_range_pct":tir["time_in_range_pct"],
                "below_range_pct":tir["below_range_pct"],
                "above_range_pct":tir["above_range_pct"],
                "in_range_count":tir["in_range_count"],
                "below_range_count":tir["below_range_count"],
                "above_range_count":tir["above_range_count"],
                "high_alerts":high_alerts,
                "low_alerts":low_alerts,
                "unit":             "mg/dL",
            },
        })

    #time range
    @action(detail=False, methods=['get'], url_path='time-in-range')
    def time_in_range(self, request):
        try:
            low  = float(request.query_params.get('low',  70))
            high = float(request.query_params.get('high', 180))
        except ValueError:
            return Response({"status": "error", "message": "low and high must be valid numbers"}, status=status.HTTP_400_BAD_REQUEST)

        user, logs, err = self._get_user_and_logs(request.query_params)
        if err:
            return err
        total = logs.count()
        if total == 0:
            return self._no_logs_response("No reading found for the given date range")


        tir = self._get_time_in_range(logs, total, low, high)  # ← reusing same method

        logger.info(f"Report time-in-range: user_id={user.user_id}, TIR={tir['time_in_range_pct']}%")
        return Response({
            "status": "success",
            "data": {
                "range":             f"{low}--{high} mg/dL",
                "total_readings":    total,
                **tir,              # ← unpacks all tir fields directly
            },
        })

    @action(detail=False, methods=['get'], url_path='glucose-trends')
    def glucose_trends(self, request):
        user, logs, err = self._get_user_and_logs(request.query_params)
        if err:
            return err

        total = logs.count()
        if total == 0:
            return self._no_logs_response()
        data = [
            {
                "id":            log.id,
                "timestamp":     log.timestamp,
                "glucose_value": log.glucose_value,
                "note":          log.note,
                "deviceid":      log.deviceid,
            }
            for log in logs
        ]

        logger.info(f"Glucose trends: user_id={user.user_id}, count={total}")

        return Response({
            "status": "success",
            "data": {
                "total_readings": total,
                "low_threshold":  70,
                "high_threshold": 180,
                "readings":       data,
            },
        })

    #weekly breakdown
    @action(detail=False, methods=['get'], url_path='weekly-breakdown')
    def weekly_breakdown(self, request):
        user, logs, err = self._get_user_and_logs(request.query_params)
        if err:
            return err

        from_date_str = request.query_params.get('from_date')
        to_date_str = request.query_params.get('to_date')

        start = self._parse_flexible_date(from_date_str) if from_date_str else (timezone.now() - timedelta(days=30)).date()
        if from_date_str and start is None:
            return Response({"status": "error", "message": f"Invalid from_date: {from_date_str}"}, status=400)

        end = self._parse_flexible_date(to_date_str) if to_date_str else timezone.now().date()
        if to_date_str and end is None:
            return Response({"status": "error", "message": f"Invalid to_date: {to_date_str}"}, status=400)

        if start > end:
            return Response({"status": "error", "message": "from_date must be before to_date"}, status=400)

        range_start_dt = make_aware(dt.datetime.combine(start, dt.time.min))
        range_end_dt = make_aware(dt.datetime.combine(end, dt.time.max))
        logs = logs.filter(timestamp__gte=range_start_dt, timestamp__lte=range_end_dt)

        total = logs.count()
        if total == 0:
            return self._no_logs_response()

        weeks = []
        week_num = 1
        week_start = start

        while week_start <= end:
            week_end = min(week_start + timedelta(days=6), end)

            week_start_dt = make_aware(dt.datetime.combine(week_start, dt.time.min))
            week_end_dt = make_aware(dt.datetime.combine(week_end, dt.time.max))

            week_logs = logs.filter(timestamp__gte=week_start_dt, timestamp__lte=week_end_dt)

            stats = week_logs.aggregate(
                total=Count('id'),
                avg=Avg('glucose_value'),
                max=Max('glucose_value'),
                min=Min('glucose_value'),
                in_range=Count('id', filter=Q(glucose_value__gte=70, glucose_value__lte=180)),
                below_range=Count('id', filter=Q(glucose_value__lt=70)),
                above_range=Count('id', filter=Q(glucose_value__gt=180)),
            )
            week_total = stats['total']

            if week_total > 0:
                weeks.append({
                    "week":              week_num,
                    "from_date":         week_start.strftime("%b %d"),
                    "to_date":           week_end.strftime("%b %d"),
                    "days":              (week_end - week_start).days + 1,
                    "total_readings":    week_total,
                    "avg_glucose":       round(stats['avg'], 1),
                    "max_glucose":       stats['max'],
                    "min_glucose":       stats['min'],
                    "time_in_range_pct": round((stats['in_range']    / week_total) * 100, 1),
                    "below_range_pct":   round((stats['below_range'] / week_total) * 100, 1),
                    "above_range_pct":   round((stats['above_range'] / week_total) * 100, 1),
                    "in_range_count":    stats['in_range'],
                    "below_range_count": stats['below_range'],
                    "above_range_count": stats['above_range'],
                })
            else:
                weeks.append({
                    "week":           week_num,
                    "from_date":      week_start.strftime("%b %d"),
                    "to_date":        week_end.strftime("%b %d"),
                    "days":           (week_end - week_start).days + 1,
                    "total_readings": 0,
                    "message":        "No readings this week",
                })

            week_start += timedelta(days=7)
            week_num += 1

        logger.info(f"weekly breakdown: user_id={user.user_id}, weeks={len(weeks)}")
        return Response({
            "status": "success",
            "data": {
                "from_date":     start.strftime("%b %d, %Y"),
                "to_date":       end.strftime("%b %d, %Y"),
                "total_weeks":   len(weeks),
                "total_readings": total,
                "weeks":         weeks,
            },
        })

    @staticmethod
    def _parse_flexible_date(date_str):
        """Parse a date string as either a date or datetime; return None if invalid."""
        parsed = parse_date(date_str)
        if parsed is not None:
            return parsed
        parsed_dt = parse_datetime(date_str)
        return parsed_dt.date() if parsed_dt is not None else None

    @action(detail=False, methods=['get'], url_path='daily-breakdown')
    def daily_breakdown(self, request):
        user, logs, err = self._get_user_and_logs(request.query_params)
        if err:
            return err

        from_date_str = request.query_params.get('from_date')
        to_date_str   = request.query_params.get('to_date')
        try:
            days          = int(request.query_params.get('days', 7))
            if days<=0:
                raise  ValueConstraintError
        except(TypeError,ValueError):
            return Response({"status":"error","message":"days must be a positive integer"},status=400)


        if from_date_str:
            start = parse_date(from_date_str) or parse_datetime(from_date_str).date()
        else:
            start = (timezone.now() - timedelta(days=days)).date()

        if to_date_str:
            end = parse_date(to_date_str) or parse_datetime(to_date_str).date()
        else:
            end = timezone.now().date()

        total = logs.count()
        if total == 0:
            return self._no_logs_response()
        daily = []
        current = start

        while current <= end:
            day_start = make_aware(dt.datetime.combine(current, dt.time.min))
            day_end   = make_aware(dt.datetime.combine(current, dt.time.max))

            day_logs  = logs.filter(timestamp__gte=day_start, timestamp__lte=day_end)
            day_total = day_logs.count()

            if day_total > 0:
                stats       = day_logs.aggregate(avg=Avg('glucose_value'), max=Max('glucose_value'), min=Min('glucose_value'))
                in_range    = day_logs.filter(glucose_value__gte=70, glucose_value__lte=180).count()
                below_range = day_logs.filter(glucose_value__lt=70).count()
                above_range = day_logs.filter(glucose_value__gt=180).count()

                daily.append({
                    "date":              current.strftime("%Y-%m-%d"),
                    "day":               current.strftime("%a"),   # Sun, Mon, Tue...
                    "total_readings":    day_total,
                    "avg_glucose":       round(stats['avg'], 1),
                    "max_glucose":       stats['max'],
                    "min_glucose":       stats['min'],
                    "time_in_range_pct": round((in_range    / day_total) * 100, 1),
                    "below_range_pct":   round((below_range / day_total) * 100, 1),
                    "above_range_pct":   round((above_range / day_total) * 100, 1),
                    "in_range_count":    in_range,
                    "below_range_count": below_range,
                    "above_range_count": above_range,
                })
            else:
                daily.append({
                    "date":           current.strftime("%Y-%m-%d"),
                    "day":            current.strftime("%a"),
                    "total_readings": 0,
                    "message":        "No readings this day",
                })

            current += timedelta(days=1)

        logger.info(f"Daily breakdown: user_id={user.user_id}, days={len(daily)}")

        return Response({
            "status": "success",
            "data": {
                "from_date":      start.strftime("%b %d, %Y"),
                "to_date":        end.strftime("%b %d, %Y"),
                "total_days":     len(daily),
                "total_readings": total,
                "days":           daily,
            },
        })

    #daily breakdown api in details
    @action(detail=False, methods=['get'], url_path='daily-detail')
    def daily_detail(self,request):
        user_id =request.query_params.get('user')
        date_str= request.query_params.get('date')

        if not user_id or not date_str:
            return Response({
                "status":"error",
                "message":"user and date are required"
            },status=status.HTTP_400_BAD_REQUEST)
        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({
                "status":"error",
                "message":"Invalid Date Format. use YYYY-MM-DD"
            },status=status.HTTP_400_BAD_REQUEST)

        target_date=parse_date(date_str)
        if not target_date:
            return Response({
                "status":"error",
                "message":"Invalid Date Format. Use YYYY-MM-DD"
            },status=status.HTTP_400_BAD_REQUEST)
        day_start = make_aware(dt.datetime.combine(target_date, dt.time.min))
        day_end   = make_aware(dt.datetime.combine(target_date, dt.time.max))

        logs  = LogEntry.objects.filter(user=user, timestamp__gte=day_start, timestamp__lte=day_end).order_by('timestamp')
        total = logs.count()

        if total==0:
            return Response({
                "status":"error",
                "message":"No reading found for this range"
            },status=status.HTTP_404_NOT_FOUND)
        stats = logs.aggregate(avg=Avg('glucose_value'), max=Max('glucose_value'), min=Min('glucose_value'))
        #glucose Zone
        very_low  = logs.filter(glucose_value__lt=54).count()
        low       = logs.filter(glucose_value__gte=54,  glucose_value__lt=70).count()
        target    = logs.filter(glucose_value__gte=70,  glucose_value__lte=180).count()
        high      = logs.filter(glucose_value__gt=180,  glucose_value__lte=250).count()
        very_high = logs.filter(glucose_value__gt=250).count()

        readings = [
            {
                "timestamp":     log.timestamp,
                "glucose_value": log.glucose_value,
                "note":          log.note,
            }
            for log in logs
        ]
        last_log = logs.last()
        logger.info(f"Daily detail: user_id={user.user_id}, date={date_str}, readings={total}")
        return Response({
            "status":"success",
            "data":{
                "date": target_date.strftime("%a, %b %d"),
                "year":target_date.year,
                "avg_glucose":round(stats['avg'], 1),
                "max_glucose":stats['max'],
                "min_glucose":stats['min'],
                "time_in_range_pct":round((target/total)*100,1),
                "latest_reading":{
                    "glucose_value":last_log.glucose_value,
                    "timestamp":last_log.timestamp,
                },
                "zones": {
                    "very_low":  {"count": very_low,  "pct": round((very_low  / total) * 100, 1), "range": "<54"},
                    "low":       {"count": low,       "pct": round((low       / total) * 100, 1), "range": "54-70"},
                    "target":    {"count": target,    "pct": round((target    / total) * 100, 1), "range": "70-180"},
                    "high":      {"count": high,      "pct": round((high      / total) * 100, 1), "range": "180-250"},
                    "very_high": {"count": very_high, "pct": round((very_high / total) * 100, 1), "range": ">250"},
                },
                "total_readings": total,
                "readings":       readings,
            },
        })

    # Nocturnal Glucose Statistics (standalone, AGP-style daily table)
    @action(detail=False, methods=['get'], url_path='nocturnal-glucose-statistics')
    def nocturnal_glucose_statistics(self, request):

        user, logs, err = self._get_user_and_logs(request.query_params)
        if err:
            return err

        from_date_str = request.query_params.get('from_date')
        to_date_str   = request.query_params.get('to_date')
        night_start   = int(request.query_params.get('night_start', 22))
        night_end     = int(request.query_params.get('night_end', 6))

        start = self._parse_flexible_date(from_date_str) if from_date_str else (timezone.now() - timedelta(days=14)).date()
        if from_date_str and start is None:
            return Response({"status": "error", "message": f"Invalid from_date: {from_date_str}"}, status=400)

        end = self._parse_flexible_date(to_date_str) if to_date_str else timezone.now().date()
        if to_date_str and end is None:
            return Response({"status": "error", "message": f"Invalid to_date: {to_date_str}"}, status=400)

        if start > end:
            return Response({"status": "error", "message": "from_date must be before to_date"}, status=400)

        days = self._build_glucose_statistics_table(logs, start, end, night_start, night_end)

        if not any(d["stats"] for d in days):
            return self._no_logs_response("No nocturnal readings found for the given date range")

        logger.info(
            f"Nocturnal glucose statistics: user_id={user.user_id}, "
            f"from={start}, to={end}, night_window={night_start:02d}:00-{night_end:02d}:00, "
            f"nights={len(days)}"
        )
        return Response({
            "status": "success",
            "data": {
                "night_window": f"{night_start:02d}:00 – {night_end:02d}:00 (+1 day)",
                "days":         days,
            },
        })

    #Combined PDF Report Data
    @action(detail=False, methods=['get'], url_path='pdf-report-data')
    def pdf_report_data(self, request):
        user, logs, err = self._get_user_and_logs(request.query_params)
        if err:
            return err
        from_date_str = request.query_params.get('from_date')
        to_date_str   = request.query_params.get('to_date')

        total = logs.count()
        if total == 0:
            return self._no_logs_response()

        # Patient Info
        device = DeviceMaster.objects.filter(user=user, status='ACTIVE').order_by('-id').first()

        dob = user.dob
        age = None
        if dob:
            today = timezone.now().date()
            age   = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

        patient_info = {
            "user_id":        user.user_id,
            "first_name":     user.first_name,
            "middle_name":    user.middle_name,
            "last_name":      user.last_name,
            "age":            age,
            "gender":         user.gender,
            "dob":            str(dob) if dob else None,
            "mobile_number":  user.mobile_number,
            "address":        user.address,
            "profile_picture": request.build_absolute_uri(user.profile_picture.url)
            if user.profile_picture else None,
            "device": {
                "device_serial_no": device.device_serial_no if device else None,
                "device_type":      device.device_type      if device else None,
                "assigned_at":      device.assigned_at      if device else None,
                "status":           device.status           if device else None,
            },
            "report_period": {
                "from_date": from_date_str,
                "to_date":   to_date_str,
            },
        }

        # Resolve the actual report date range early — needed for the
        # Weekly Breakdown and Nocturnal Glucose Statistics sections further down.
        from_date = parse_date(from_date_str) if from_date_str else (timezone.now() - timedelta(days=30)).date()
        to_date   = parse_date(to_date_str)   if to_date_str   else timezone.now().date()

        # 2. Executive Summary
        stats = logs.aggregate(
            avg=Avg('glucose_value'),
            max=Max('glucose_value'),
            min=Min('glucose_value'),
        )

        avg_glucose = round(stats['avg'], 1)

        # eHbA1c — same shared logic used by avg_glucose
        hba1c_data      = self._get_estimated_hba1c(logs, avg_glucose)
        estimated_hba1c = hba1c_data["estimated_hba1c"]
        hba1c_eligible  = hba1c_data["hba1c_eligible"]
        hba1c_message   = hba1c_data["hba1c_message"]
        monitoring_days = hba1c_data["monitoring_days"]

        in_range    = logs.filter(glucose_value__gte=70, glucose_value__lte=180).count()
        below_range = logs.filter(glucose_value__lt=70).count()
        above_range = logs.filter(glucose_value__gt=180).count()
        hypo_count  = logs.filter(glucose_value__lt=54).count()
        hyper_count = logs.filter(glucose_value__gt=250).count()

        last_log = logs.order_by('-timestamp').first()

        executive_summary = {
            "last_reading": {
                "glucose_value": last_log.glucose_value,
                "timestamp":    timezone.localtime(last_log.timestamp),
            },
            "avg_glucose":        avg_glucose,
            "max_glucose":        stats['max'],
            "min_glucose":        stats['min'],
            "estimated_hba1c":    estimated_hba1c,
            "hba1c_eligible":     hba1c_eligible,
            "hba1c_message":      hba1c_message,
            "time_in_range_pct":  round(in_range    / total * 100, 1),
            "below_range_pct":    round(below_range / total * 100, 1),
            "above_range_pct":    round(above_range / total * 100, 1),
            "hypo_events_count":  hypo_count,
            "hyper_events_count": hyper_count,
            "total_readings":     total,
            "monitoring_days":    monitoring_days,
            "unit":               "mg/dL",
        }

        # 3. Glucose Trends (all readings for line chart)
        glucose_trends = [
            {
                "timestamp":   timezone.localtime(log.timestamp),
                "glucose_value": log.glucose_value,
                "note":          log.note,
                "deviceid":      log.deviceid,
            }
            for log in logs
        ]

        # 4. Time in Range
        low  = float(request.query_params.get('low',  70))
        high = float(request.query_params.get('high', 180))

        tir_in_range    = logs.filter(glucose_value__gte=low,  glucose_value__lte=high).count()
        tir_below_range = logs.filter(glucose_value__lt=low).count()
        tir_above_range = logs.filter(glucose_value__gt=high).count()

        time_in_range = {
            "range":              f"{low}–{high} mg/dL",
            "low_threshold":      low,
            "high_threshold":     high,
            "time_in_range_pct":  round(tir_in_range    / total * 100, 1),
            "below_range_pct":    round(tir_below_range / total * 100, 1),
            "above_range_pct":    round(tir_above_range / total * 100, 1),
            "in_range_count":     tir_in_range,
            "below_range_count":  tir_below_range,
            "above_range_count":  tir_above_range,
            "total_readings":     total,
        }

        # 5. Weekly Breakdown
        weeks      = []
        week_num   = 1
        week_start = from_date

        while week_start <= to_date:
            week_end      = min(week_start + timedelta(days=6), to_date)
            week_start_dt = make_aware(dt.datetime.combine(week_start, dt.time.min))
            week_end_dt   = make_aware(dt.datetime.combine(week_end,   dt.time.max))
            week_logs  = logs.filter(timestamp__gte=week_start_dt, timestamp__lte=week_end_dt)
            week_total = week_logs.count()

            if week_total > 0:
                wstats  = week_logs.aggregate(avg=Avg('glucose_value'), max=Max('glucose_value'), min=Min('glucose_value'))
                w_in    = week_logs.filter(glucose_value__gte=70, glucose_value__lte=180).count()
                w_below = week_logs.filter(glucose_value__lt=70).count()
                w_above = week_logs.filter(glucose_value__gt=180).count()

                weeks.append({
                    "week":              week_num,
                    "from_date":         week_start.strftime("%b %d"),
                    "to_date":           week_end.strftime("%b %d"),
                    "days":              (week_end - week_start).days + 1,
                    "total_readings":    week_total,
                    "avg_glucose":       round(wstats['avg'], 1),
                    "max_glucose":       wstats['max'],
                    "min_glucose":       wstats['min'],
                    "time_in_range_pct": round(w_in    / week_total * 100, 1),
                    "below_range_pct":   round(w_below / week_total * 100, 1),
                    "above_range_pct":   round(w_above / week_total * 100, 1),
                    "in_range_count":    w_in,
                    "below_range_count": w_below,
                    "above_range_count": w_above,
                })
            else:
                weeks.append({
                    "week":           week_num,
                    "from_date":      week_start.strftime("%b %d"),
                    "to_date":        week_end.strftime("%b %d"),
                    "days":           (week_end - week_start).days + 1,
                    "total_readings": 0,
                    "message":        "No readings this week",
                })

            week_start += timedelta(days=7)
            week_num   += 1

        weekly_breakdown = {
            "from_date":      from_date.strftime("%b %d, %Y"),
            "to_date":        to_date.strftime("%b %d, %Y"),
            "total_weeks":    len(weeks),
            "total_readings": total,
            "weeks":          weeks,
        }

        # 6. Nocturnal Readings (22:00 – 06:00) — single aggregate summary
        try:
            night_start = int(request.query_params.get('night_start', 22))
            night_end   = int(request.query_params.get('night_end', 6))
            if not (0 <= night_start <= 23) or not (0 <= night_end <= 23):
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"status": "error", "message": "night_start and night_end must be integers between 0 and 23"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        nocturnal_logs = logs.annotate(
            hour=ExtractHour('timestamp')
        ).filter(
            Q(hour__gte=night_start) | Q(hour__lt=night_end)
        ).order_by('timestamp')

        nocturnal_total = nocturnal_logs.count()

        if nocturnal_total > 0:
            nstats  = nocturnal_logs.aggregate(avg=Avg('glucose_value'), max=Max('glucose_value'), min=Min('glucose_value'))
            n_in    = nocturnal_logs.filter(glucose_value__gte=70, glucose_value__lte=180).count()
            n_hypo  = nocturnal_logs.filter(glucose_value__lt=54).count()
            n_hyper = nocturnal_logs.filter(glucose_value__gt=250).count()

            nocturnal = {
                "night_window":       f"{night_start:02d}:00 – {night_end:02d}:00",
                "total_readings":     nocturnal_total,
                "avg_glucose":        round(nstats['avg'], 1),
                "max_glucose":        nstats['max'],
                "min_glucose":        nstats['min'],
                "time_in_range_pct":  round(n_in    / nocturnal_total * 100, 1),
                "hypo_events_count":  n_hypo,
                "hyper_events_count": n_hyper,
                "unit":               "mg/dL",
                "readings": [
                    {
                        "timestamp":    timezone.localtime(log.timestamp),
                        "glucose_value": log.glucose_value,
                        "note":          log.note,
                    }
                    for log in nocturnal_logs
                ],
            }
        else:
            nocturnal = {
                "night_window":   f"{night_start:02d}:00 – {night_end:02d}:00",
                "total_readings": 0,
                "message":        "No nocturnal readings found for this period",
            }

        noct_days = self._build_glucose_statistics_table(
            logs, from_date, to_date, night_start, night_end
        )
        nocturnal_glucose_statistics = {
            "night_window": f"{night_start:02d}:00 – {night_end:02d}:00 (+1 day)",
            "days":         noct_days,
        }

        # 7. Notable Events (out-of-range readings)
        def _zone_label(gv):
            if gv < 54:          return "Very Low (<54)"
            if 54 <= gv < 70:    return "Low (54–69)"
            if 181 <= gv <= 250: return "High (181–250)"
            if gv > 250:         return "Very High (>250)"
            return "In Range"

        event_logs = logs.filter(
            Q(glucose_value__lt=70) | Q(glucose_value__gt=180)
        ).order_by('timestamp')

        notable_events = {
            "summary": {
                "very_low_count":  logs.filter(glucose_value__lt=54).count(),
                "low_count":       logs.filter(glucose_value__gte=54, glucose_value__lt=70).count(),
                "high_count":      logs.filter(glucose_value__gt=180, glucose_value__lte=250).count(),
                "very_high_count": logs.filter(glucose_value__gt=250).count(),
                "total_events":    event_logs.count(),
            },
            "events": [
                {
                    "date":          log.timestamp.strftime('%Y-%m-%d'),
                    "time":          log.timestamp.strftime('%H:%M'),
                    "timestamp":     timezone.localtime(log.timestamp),
                    "glucose_value": log.glucose_value,
                    "zone":          _zone_label(log.glucose_value),
                    "note":          log.note or "",
                    "deviceid":      log.deviceid or "",
                }
                for log in event_logs
            ],
        }

        # Assemble response data once, reuse for both logging and the Response
        response_data = {
            "patient_info":                 patient_info,
            "executive_summary":            executive_summary,
            "glucose_trends":               glucose_trends,
            "time_in_range":                time_in_range,
            "weekly_breakdown":             weekly_breakdown,
            "nocturnal":                    nocturnal,
            "nocturnal_glucose_statistics": nocturnal_glucose_statistics,
            "notable_events":               notable_events,
        }

        response_keys = list(response_data.keys())

        logger.info(
            "Report pdf-report-data: user_id=%s, total=%s, from=%s, to=%s",
            user.user_id, total, from_date_str, to_date_str
        )
        logger.info("Response keys: %s", response_keys)

        # Final Response
        return Response({
            "status": "success",
            "data": response_data,
        })

########## AGP Report
# --- AGP constants (mg/dL) -- international CGM consensus zones,
AGP_VERY_LOW_MAX = 54
AGP_LOW_MAX      = 70
AGP_TARGET_MIN   = 70
AGP_TARGET_MAX   = 180
AGP_HIGH_MAX     = 250

MGDL_PER_MMOL = 18.0182

AGP_READING_INTERVAL_MINUTES = 5
AGP_BUCKETS_PER_DAY = (24 * 60) // AGP_READING_INTERVAL_MINUTES  # 288

AGP_MIN_DAYS = 5
AGP_MAX_DAYS = 14

AGP_CURVE_INTERVAL_MINUTES = 30
AGP_CURVE_POINTS = (24 * 60) // AGP_CURVE_INTERVAL_MINUTES   # 48
AGP_CURVE_MIN_SAMPLES = 3   # minimum readings in a slot to calculate percentiles

def _agp_slot_index(timestamp):
    ts = timezone.localtime(timestamp)          # IST, not UTC
    return (ts.hour * 60 + ts.minute)
def _agp_percentile(sorted_values, pct):
    if not sorted_values:
        return None
    n = len(sorted_values)
    if n == 1:
        return round(sorted_values[0], 1)
    k = (n - 1) * (pct / 100.0)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return round(sorted_values[int(k)], 1)
    d0 = sorted_values[int(f)] * (c - k)
    d1 = sorted_values[int(c)] * (k - f)
    return round(d0 + d1, 1)


def _agp_minutes_to_hm(total_minutes):
    total_minutes = int(round(total_minutes))
    h, m = divmod(total_minutes, 60)
    if h and m:
        return f"{h}h {m}min"
    if h:
        return f"{h}h"
    return f"{m}min"


def _agp_mgdl_to_mmol(value):
    return round(value / MGDL_PER_MMOL, 1) if value is not None else None


def _agp_gmi(avg_glucose_mgdl):
    return round(3.31 + 0.02392 * avg_glucose_mgdl, 1)


def _agp_cv_pct(values):
    if len(values) < 2:
        return 0.0
    mean = statistics.fmean(values)
    if mean == 0:
        return 0.0
    return round(statistics.pstdev(values) / mean * 100, 1)


def _agp_zone_label(gv):
    if gv < AGP_VERY_LOW_MAX:
        return "very_low"
    if gv < AGP_LOW_MAX:
        return "low"
    if gv <= AGP_TARGET_MAX:
        return "target"
    if gv <= AGP_HIGH_MAX:
        return "high"
    return "very_high"


def _agp_bucket_key(timestamp):
    minute_of_day = timestamp.hour * 60 + timestamp.minute
    bucket_start = (minute_of_day // AGP_READING_INTERVAL_MINUTES) * AGP_READING_INTERVAL_MINUTES
    h, m = divmod(bucket_start, 60)
    return f"{h:02d}:{m:02d}"


def _agp_device_dict(device):
    if not device:
        return None
    return {
        "device_serial_no": device.device_serial_no,
        "device_type":      device.device_type,
        "status":           device.status,
        "assigned_at":      timezone.localtime(device.assigned_at),
    }

from rest_framework.exceptions import MethodNotAllowed

class AGPReportViewSet(ReportViewSet):

    def list(self, request,*args,**kwargs):
        raise MethodNotAllowed(request.method)

    # return Response({
        #     "status": "success",
        #     "endpoints": {
        #         "agp_statistics":     "GET /api/agp/agp-statistics/?user=&from_date=&to_date=&device_serial_no=",
        #         "agp_time_in_ranges": "GET /api/agp/agp-time-in-ranges/?user=&from_date=&to_date=&device_serial_no=",
        #         "agp_curve":          "GET /api/agp/agp-curve/?user=&from_date=&to_date=&device_serial_no=",
        #         "agp_daily_profiles": "GET /api/agp/agp-daily-profiles/?user=&from_date=&to_date=&device_serial_no=",
        #         "agp_report_data":    "GET /api/agp/agp-report-data/?user=&from_date=&to_date=&device_serial_no=",
        #         "agp_devices":        "GET /api/agp/agp-devices/?user=&from_date=&to_date=",
        #     },
        #     "notes": {
        #         "reading_interval_minutes": AGP_READING_INTERVAL_MINUTES,
        #         "min_days_required":        AGP_MIN_DAYS,
        #         "max_days_supported":       AGP_MAX_DAYS,
        #         "device_filter":            "Pass device_serial_no (or device) on any endpoint to scope to one sensor.",
        #     },
        # })

    # device lookup / validation
    def _get_device(self, user, device_serial_no):
        if not device_serial_no:
            return None, None
        try:
            device = DeviceMaster.objects.get(device_serial_no=device_serial_no, user=user)
        except DeviceMaster.DoesNotExist:
            return None, Response(
                {"status": "error", "message": f"Device '{device_serial_no}' not found for this user."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return device, None

    # shared period resolution
    def _resolve_agp_period(self, params):
        """Returns (user, logs, from_date, to_date, device, error_response)."""
        user, logs, err = self._get_user_and_logs(params)
        if err:
            return None, None, None, None, None, err

        device_serial_no = params.get('device_serial_no') or params.get('device')
        device, device_err = self._get_device(user, device_serial_no)
        if device_err:
            return None, None, None, None, None, device_err
        if device:
            logs = logs.filter(deviceid=device.device_serial_no)

        from_date_str = params.get('from_date')
        to_date_str   = params.get('to_date')

        to_date = self._parse_flexible_date(to_date_str) if to_date_str else timezone.now().date()
        if to_date_str and to_date is None:
            return None, None, None, None, None, Response(
                {"status": "error", "message": f"Invalid to_date: {to_date_str}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from_date = (
            self._parse_flexible_date(from_date_str)
            if from_date_str else (to_date - timedelta(days=AGP_MAX_DAYS - 1))
        )
        if from_date_str and from_date is None:
            return None, None, None, None, None, Response(
                {"status": "error", "message": f"Invalid from_date: {from_date_str}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if from_date > to_date:
            return None, None, None, None, None, Response(
                {"status": "error", "message": "from_date must be before to_date"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        span_days = (to_date - from_date).days + 1
        if span_days > AGP_MAX_DAYS:
            return None, None, None, None, None, Response({
                "status": "error",
                "message": f"AGP report supports a maximum of {AGP_MAX_DAYS} days. "
                           f"Requested range is {span_days} days -- please narrow it.",
            }, status=status.HTTP_400_BAD_REQUEST)

        range_start = make_aware(dt.datetime.combine(from_date, dt.time.min))
        range_end   = make_aware(dt.datetime.combine(to_date, dt.time.max))
        logs = logs.filter(timestamp__gte=range_start, timestamp__lte=range_end)

        distinct_days = logs.values('timestamp__date').distinct().count()
        if distinct_days < AGP_MIN_DAYS:
            return None, None, None, None, None, Response({
                "status": "error",
                "message": f"AGP report requires at least {AGP_MIN_DAYS} days of sensor data. "
                           f"Only {distinct_days} day(s) available for this range"
                           + (f" on device {device.device_serial_no}." if device else "."),
                "days_available": distinct_days,
                "days_required":  AGP_MIN_DAYS,
            }, status=status.HTTP_400_BAD_REQUEST)

        return user, logs, from_date, to_date, device, None

    # Section 0: Devices
    @action(detail=False, methods=['get'], url_path='agp-devices')
    def agp_devices(self, request):
        user, logs, from_date, to_date, device, err = self._resolve_agp_period(request.query_params)
        if err:
            return err

        rows = (
            logs.exclude(deviceid__isnull=True).exclude(deviceid='')
            .values('deviceid')
            .annotate(total_readings=Count('id'))
            .order_by('-total_readings')
        )

        devices = []
        for row in rows:
            serial = row['deviceid']
            dm = DeviceMaster.objects.filter(device_serial_no=serial, user=user).first()
            devices.append({
                "device_serial_no": serial,
                "device_type":      dm.device_type if dm else None,
                "status":           dm.status if dm else None,
                "total_readings":   row['total_readings'],
            })

        logger.info(f"AGP devices: user_id={user.user_id}, devices_found={len(devices)}")
        return Response({
            "status": "success",
            "data": {
                "from_date":    from_date.strftime("%Y-%m-%d"),
                "to_date":      to_date.strftime("%Y-%m-%d"),
                "total_devices": len(devices),
                "devices":      devices,
            },
        })

    # Glucose Statistics and Targets
    def _compute_agp_statistics(self, logs, from_date, to_date, device=None):
        total  = logs.count()
        values = list(logs.values_list('glucose_value', flat=True))
        avg_glucose = round(statistics.fmean(values), 1)

        period_days       = (to_date - from_date).days + 1
        expected_readings = (period_days * 24 * 60) // AGP_READING_INTERVAL_MINUTES
        pct_cgm_active    = min(round(total / expected_readings * 100), 100) if expected_readings else 0

        return {
            "report_period": {
                "from_date": f"{from_date:%B} {from_date.day}, {from_date.year}",
                "to_date":   f"{to_date:%B} {to_date.day}, {to_date.year}",
                "days":      period_days,
            },
            "device":                 _agp_device_dict(device),
            "pct_cgm_active":         pct_cgm_active,
            "total_readings":         total,
            "avg_glucose_mgdl":       avg_glucose,
            "avg_glucose_mmol":       _agp_mgdl_to_mmol(avg_glucose),
            "gmi_pct":                _agp_gmi(avg_glucose),
            "glucose_variability_cv": _agp_cv_pct(values),
        }

    @action(detail=False, methods=['get'], url_path='agp-statistics')
    def agp_statistics(self, request):
        user, logs, from_date, to_date, device, err = self._resolve_agp_period(request.query_params)
        if err:
            return err
        data = self._compute_agp_statistics(logs, from_date, to_date, device)
        logger.info(f"AGP statistics: user_id={user.user_id}, device={device.device_serial_no if device else None}, "
                    f"avg={data['avg_glucose_mgdl']}, gmi={data['gmi_pct']}")
        return Response({"status": "success", "data": data})

    # Section 2: Time in Ranges
    def _compute_agp_time_in_ranges(self, logs, total):
        very_low  = logs.filter(glucose_value__lt=AGP_VERY_LOW_MAX).count()
        low       = logs.filter(glucose_value__gte=AGP_VERY_LOW_MAX, glucose_value__lt=AGP_LOW_MAX).count()
        target    = logs.filter(glucose_value__gte=AGP_TARGET_MIN, glucose_value__lte=AGP_TARGET_MAX).count()
        high      = logs.filter(glucose_value__gt=AGP_TARGET_MAX, glucose_value__lte=AGP_HIGH_MAX).count()
        very_high = logs.filter(glucose_value__gt=AGP_HIGH_MAX).count()

        def zone(count, label, low_thresh, high_thresh):
            minutes = count * AGP_READING_INTERVAL_MINUTES
            return {
                "label":  label,
                "count":  count,
                "pct":    round(count / total * 100, 1) if total else 0,
                "time":   _agp_minutes_to_hm(minutes),
                "range_mgdl": f"{low_thresh}-{high_thresh}" if high_thresh else f">{low_thresh}",
                "range_mmol": (f"{_agp_mgdl_to_mmol(low_thresh)}-{_agp_mgdl_to_mmol(high_thresh)}"
                               if high_thresh else f">{_agp_mgdl_to_mmol(low_thresh)}"),
            }

        return {
            "very_high": zone(very_high, "Very High",    AGP_HIGH_MAX, None),
            "high":      zone(high,      "High",         AGP_TARGET_MAX, AGP_HIGH_MAX),
            "target":    zone(target,    "Target Range", AGP_TARGET_MIN, AGP_TARGET_MAX),
            "low":       zone(low,       "Low",          AGP_VERY_LOW_MAX, AGP_LOW_MAX),
            "very_low":  zone(very_low,  "Very Low",     0, AGP_VERY_LOW_MAX),
            "total_readings": total,
        }

    @action(detail=False, methods=['get'], url_path='agp-time-in-ranges')
    def agp_time_in_ranges(self, request):
        user, logs, from_date, to_date, device, err = self._resolve_agp_period(request.query_params)
        if err:
            return err
        total = logs.count()
        data = self._compute_agp_time_in_ranges(logs, total)
        data["device"] = _agp_device_dict(device)
        logger.info(f"AGP time-in-ranges: user_id={user.user_id}, device={device.device_serial_no if device else None}, "
                    f"target_pct={data['target']['pct']}")
        return Response({"status": "success", "data": data})

    # Section 3: percentile curve (5/25/50/75/95th)
    def _compute_agp_curve(self, logs):
        interval = AGP_CURVE_INTERVAL_MINUTES          # 30
        n_slots = (24 * 60) // interval                # 48
        slots = [[] for _ in range(n_slots)]

        for ts, gv in logs.values_list('timestamp', 'glucose_value'):
            if ts is None or gv is None:
                continue
            local_ts = timezone.localtime(ts)
            idx = (local_ts.hour * 60 + local_ts.minute) // interval
            if 0 <= idx < n_slots:                     # safety guard
                slots[idx].append(float(gv))

        points, filled = [], 0
        for i, values in enumerate(slots):
            h, m = divmod(i * interval, 60)
            values.sort()
            has_data = len(values) >= AGP_CURVE_MIN_SAMPLES
            if has_data:
                filled += 1

            def p(pct):
                return _agp_percentile(values, pct) if has_data else None

            p5, p25, med, p75, p95 = p(5), p(25), p(50), p(75), p(95)
            points.append({
                "time":        f"{h:02d}:{m:02d}",
                "has_data":    has_data,
                "n":           len(values),
                "p5_mgdl":     p5,
                "p25_mgdl":    p25,
                "median_mgdl": med,
                "p75_mgdl":    p75,
                "p95_mgdl":    p95,
                "p5_mmol":     _agp_mgdl_to_mmol(p5),
                "p25_mmol":    _agp_mgdl_to_mmol(p25),
                "median_mmol": _agp_mgdl_to_mmol(med),
                "p75_mmol":    _agp_mgdl_to_mmol(p75),
                "p95_mmol":    _agp_mgdl_to_mmol(p95),
            })

        return {
            "interval_minutes": interval,
            "expected_points":  n_slots,
            "filled_points":    filled,
            "coverage_pct":     round(filled / n_slots * 100, 1),
            "points":           points,
        }

    @action(detail=False, methods=['get'], url_path='agp-curve')
    def agp_curve(self, request):
        user, logs, from_date, to_date, device, err = self._resolve_agp_period(request.query_params)
        if err:
            return err
        curve = self._compute_agp_curve(logs)
        logger.info(f"AGP curve: user_id={user.user_id}, device={device.device_serial_no if device else None}, "
                    f"filled={curve['filled_points']}/{curve['expected_points']}")
        return Response({
            "status": "success",
            "data": {
                "device":            _agp_device_dict(device),
                "target_range_mgdl": [AGP_TARGET_MIN, AGP_TARGET_MAX],
                "target_range_mmol": [_agp_mgdl_to_mmol(AGP_TARGET_MIN), _agp_mgdl_to_mmol(AGP_TARGET_MAX)],
                **curve,
            },
        })

    # Section 4: Daily Glucose Profiles
    def _compute_agp_daily_profiles(self, logs, from_date, to_date):
        days = []
        current = from_date
        while current <= to_date:
            day_start = make_aware(dt.datetime.combine(current, dt.time.min))
            day_end   = make_aware(dt.datetime.combine(current, dt.time.max))
            day_logs  = logs.filter(timestamp__gte=day_start, timestamp__lte=day_end).order_by('timestamp')
            day_total = day_logs.count()

            readings = [
                {
                    "time":               log.timestamp.strftime("%H:%M"),
                    "timestamp":          log.timestamp,
                    "glucose_value_mgdl": log.glucose_value,
                    "glucose_value_mmol": _agp_mgdl_to_mmol(log.glucose_value),
                    "zone":               _agp_zone_label(log.glucose_value),
                    "deviceid":           log.deviceid,
                }
                for log in day_logs
            ]

            days.append({
                "date":           current.strftime("%Y-%m-%d"),
                "day_label":      current.strftime("%A"),
                "total_readings": day_total,
                "readings":       readings if day_total else [],
                "message":        None if day_total else "No readings this day",
            })
            current += timedelta(days=1)
        return days

    @action(detail=False, methods=['get'], url_path='agp-daily-profiles')
    def agp_daily_profiles(self, request):
        user, logs, from_date, to_date, device, err = self._resolve_agp_period(request.query_params)
        if err:
            return err
        days = self._compute_agp_daily_profiles(logs, from_date, to_date)
        logger.info(f"AGP daily-profiles: user_id={user.user_id}, device={device.device_serial_no if device else None}, "
                    f"days={len(days)}")
        return Response({
            "status": "success",
            "data": {
                "device":            _agp_device_dict(device),
                "target_range_mgdl": [AGP_TARGET_MIN, AGP_TARGET_MAX],
                "total_days":        len(days),
                "days":              days,
            },
        })

    # ---- Section 5: combined payload -----------------------------
    @action(detail=False, methods=['get'], url_path='agp-report-data')
    def agp_report_data(self, request):
        user, logs, from_date, to_date, device, err = self._resolve_agp_period(request.query_params)
        if err:
            return err

        total = logs.count()
        response_data = {
            "device":          _agp_device_dict(device),
            "statistics":      self._compute_agp_statistics(logs, from_date, to_date, device),
            "time_in_ranges":  self._compute_agp_time_in_ranges(logs, total),
            "agp_curve":       self._compute_agp_curve(logs),
            "daily_profiles":  self._compute_agp_daily_profiles(logs, from_date, to_date),
        }
        logger.info(f"AGP report-data: user_id={user.user_id}, device={device.device_serial_no if device else None}, "
                    f"total={total}, from={from_date}, to={to_date}")
        return Response({"status": "success", "data": response_data})




#######   UserPreference
# User Preference
class UserPreferenceViewSet(viewsets.ViewSet):

    def get_user_master(self, user_id):
        try:
            return UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return None

    def list(self, request):
        user_id = request.query_params.get('user')
        if not user_id:
            return Response({"status": "error", "message": "user parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        user_master = self.get_user_master(user_id)
        if not user_master:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        preference, created = UserPreference.objects.get_or_create(user=user_master)
        serializer = UserPreferenceSerializer(preference)
        return Response({"status": "success", "data": serializer.data})

    def create(self, request):
        user_id = request.data.get('user') or request.query_params.get('user')
        if not user_id:
            return Response({"status": "error", "message": "user is required"}, status=status.HTTP_400_BAD_REQUEST)

        user_master = self.get_user_master(user_id)
        if not user_master:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        preference, created = UserPreference.objects.get_or_create(user=user_master)
        serializer = UserPreferenceSerializer(preference, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Preference {'created' if created else 'updated'}: user_id={user_id}")
            return Response({
                "status":  "success",
                "message": "Preference created successfully" if created else "Preference updated successfully",
                "data":    serializer.data,
            }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

        logger.warning(f"Preference create failed: user_id={user_id}, errors={serializer.errors}")
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, pk=None):
        return self._update_preference(request, pk, partial=False)

    def partial_update(self, request, pk=None):
        return self._update_preference(request, pk, partial=True)

    def _update_preference(self, request, pk, partial):
        user_id = pk
        if not user_id:
            return Response({"status": "error", "message": "user is required"}, status=status.HTTP_400_BAD_REQUEST)

        user_master = self.get_user_master(user_id)
        if not user_master:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            preference = UserPreference.objects.get(user=user_master)
        except UserPreference.DoesNotExist:
            return Response({"status": "error", "message": "Preference not found for this user"}, status=status.HTTP_404_NOT_FOUND)

        serializer = UserPreferenceSerializer(preference, data=request.data, partial=partial)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Preference updated: user_id={user_id}")
            return Response({
                "status":  "success",
                "message": "Preference updated successfully",
                "data":    serializer.data,
            })

        logger.warning(f"Preference update failed: user_id={user_id}, errors={serializer.errors}")
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)




# Product Master
class ProductMasterViewSet(viewsets.ViewSet):

    def list(self, request):
        status_filter = request.query_params.get('status')

        products = ProductMaster.objects.all().order_by('-created_at')

        if status_filter:
            products = products.filter(status=status_filter.upper())

        serializer = ProductMasterSerializer(products, many=True)
        return Response({
            "status": "success",
            "count": products.count(),
            "data": serializer.data,
        })

    def create(self, request):
        product_code    = request.data.get('product_code', '').strip()
        description     = request.data.get('description', '')
        product_status  = request.data.get('status', 'ACTIVE')
        warm_up_minutes = request.data.get('warm_up_minutes', 45)
        life_span_days  = request.data.get('life_span_days', 14)

        if not product_code:
            return Response(
                {"status": "error", "message": "product_code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if life_span_days is None:
            return Response(
                {"status": "error", "message": "life_span_days is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if ProductMaster.objects.filter(product_code__iexact=product_code).exists():
            logger.warning(f"Product create failed: duplicate product_code={product_code}")
            return Response(
                {"status": "error", "message": "This product_code already exists."},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            warm_up_minutes = int(warm_up_minutes)
            if warm_up_minutes <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"status": "error", "message": "warm_up_minutes must be a positive integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        life_span_days = request.data.get('life_span_days')
        if life_span_days is not None:
            try:
                life_span_days = int(life_span_days)
                if life_span_days <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return Response(
                    {"status": "error", "message": "life_span_days must be a positive integer"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        serializer = ProductMasterSerializer(data={
            "product_code": product_code,
            "description": description,
            "status": product_status,
            "warm_up_minutes": warm_up_minutes,
            "life_span_days": life_span_days,

        })

        if serializer.is_valid():
            product = serializer.save()
            logger.info(f"Product created: product_code={product.product_code}")
            return Response({
                "status": "success",
                "message": "Product created successfully",
                "data": serializer.data,
            }, status=status.HTTP_201_CREATED)

        logger.warning(f"Product create validation failed: errors={serializer.errors}")
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, pk=None):
        try:
            product = ProductMaster.objects.get(pk=pk)
        except ProductMaster.DoesNotExist:
            return Response({"status": "error", "message": "Product not found"}, status=status.HTTP_404_NOT_FOUND)

        new_product_code = request.data.get('product_code')
        if new_product_code and new_product_code.strip().lower() != product.product_code.lower():
            if ProductMaster.objects.filter(product_code__iexact=new_product_code.strip()).exclude(pk=product.pk).exists():
                return Response(
                    {"status": "error", "message": "This product_code already exists."},
                    status=status.HTTP_409_CONFLICT,
                )

        warm_up_minutes = request.data.get('warm_up_minutes')
        if warm_up_minutes is not None:
            try:
                warm_up_minutes = int(warm_up_minutes)
                if warm_up_minutes <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return Response(
                    {"status": "error", "message": "warm_up_minutes must be a positive integer"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        life_span_days = request.data.get('life_span_days')
        if life_span_days is not None:
            try:
                life_span_days = int(life_span_days)
                if life_span_days <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return Response(
                    {"status": "error", "message": "life_span_days must be a positive integer"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        serializer = ProductMasterSerializer(product, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Product updated: product_code={product.product_code}")
            return Response({
                "status": "success",
                "message": "Product updated successfully",
                "data": serializer.data,
            })

        logger.warning(f"Product update failed: product_code={product.product_code}, errors={serializer.errors}")
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get', 'patch'], url_path='product-wise/(?P<product_code>[^/.]+)')
    def product_wise(self, request, product_code=None):
        try:
            product = ProductMaster.objects.get(product_code__iexact=product_code)
        except ProductMaster.DoesNotExist:
            return Response({"status": "error", "message": "Product not found"}, status=status.HTTP_404_NOT_FOUND)

        # GET: return product details
        if request.method == 'GET':
            serializer = ProductMasterSerializer(product)
            return Response({"status": "success", "data": serializer.data})

        # PATCH: update product
        new_product_code = request.data.get('product_code')
        if new_product_code and new_product_code.strip().lower() != product.product_code.lower():
            if ProductMaster.objects.filter(product_code__iexact=new_product_code.strip()).exclude(pk=product.pk).exists():
                return Response(
                    {"status": "error", "message": "This product_code already exists."},
                    status=status.HTTP_409_CONFLICT,
                )

        warm_up_minutes = request.data.get('warm_up_minutes')
        if warm_up_minutes is not None:
            try:
                warm_up_minutes = int(warm_up_minutes)
                if warm_up_minutes <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return Response(
                    {"status": "error", "message": "warm_up_minutes must be a positive integer"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        life_span_days = request.data.get('life_span_days')
        if life_span_days is not None:
            try:
                life_span_days = int(life_span_days)
                if life_span_days <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return Response(
                    {"status": "error", "message": "life_span_days must be a positive integer"},
                    status=status.HTTP_400_BAD_REQUEST,
                )


        serializer = ProductMasterSerializer(product, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info(f"Product updated: product_code={product.product_code}")
            return Response({
                "status": "success",
                "message": "Product updated successfully",
                "data": serializer.data,
            })

        logger.warning(f"Product update failed: product_code={product.product_code}, errors={serializer.errors}")
        return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)




# FAQ
class FAQViewSet(viewsets.ViewSet):

    def list(self, request):
        try:
            product_code = request.query_params.get('product_code') or request.query_params.get('product')

            faqs = (
                FAQ.objects.filter(is_active=True)
                .select_related('product')
                .prefetch_related('items')
                .order_by('order')
            )
            if product_code:
                faqs = faqs.filter(product__product_code__iexact=product_code)

            serializer = FAQSerializer(faqs, many=True, context={'request': request})
            return Response({"status": "success", "count": faqs.count(), "data": serializer.data})
        except Exception as e:
            logger.error(f"FAQ list failed : error={str(e)}")
            return Response({"status": "error", "message":"Failed to fetch FAQs"},status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def retrieve(self, request, pk=None):
        try:
            faq = FAQ.objects.select_related('product').prefetch_related('items').get(pk=pk)
        except FAQ.DoesNotExist:
            logger.warning(f"FAQ retrieve Failed : not found id={pk}")
            return Response({"status": "error", "message": "FAQ not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = FAQSerializer(faq, context={'request': request})
        logger.info(f"FAQ retrieved: id={pk}")
        return Response({"status": "success", "data": serializer.data})

    def create(self, request):
        try:
            if request.query_params.get('admin_id') != MEDIA_ADMIN_ID or request.query_params.get('password') != MEDIA_ADMIN_PASSWORD:
                return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

            product_code = request.data.get('product_code') or request.data.get('product')
            title        = (request.data.get('title') or '').strip()

            if not product_code or not title:
                return Response(
                    {"status": "error", "message": "product_code and title are required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                product = ProductMaster.objects.get(product_code__iexact=product_code)
            except ProductMaster.DoesNotExist:
                return Response({"status": "error", "message": "Product not found"}, status=status.HTTP_404_NOT_FOUND)

            if FAQ.objects.filter(product=product, title__iexact=title).exists():
                logger.warning(f"FAQ create failed: duplicate title for product={product.product_code}, title={title}")
                return Response(
                    {"status": "error", "message": "An FAQ with this title already exists for this product"},
                    status=status.HTTP_409_CONFLICT,
                )

            data = request.data.copy()
            data['product'] = product.pk

            serializer = FAQSerializer(data=data, context={'request': request})
            if serializer.is_valid():
                faq = serializer.save()
                logger.info(f"FAQ created: product={product.product_code}, title={faq.title}")
                return Response({
                    "status":  "success",
                    "message": "FAQ created successfully",
                    "data":    FAQSerializer(faq, context={'request': request}).data,
                }, status=status.HTTP_201_CREATED)

            logger.warning(f"FAQ create validation failed: errors={serializer.errors}")
            return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"FAQ create failed: error={str(e)}")
            return Response({"status": "error", "message": "Failed to create FAQ"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update(self, request, pk=None):
        try:
            if request.query_params.get('admin_id') != MEDIA_ADMIN_ID or request.query_params.get('password') != MEDIA_ADMIN_PASSWORD:
                return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

            try:
                faq = FAQ.objects.get(pk=pk)
            except FAQ.DoesNotExist:
                return Response({"status": "error", "message": "FAQ not found"}, status=status.HTTP_404_NOT_FOUND)

            data = request.data.copy()
            product_code = data.get('product_code') or data.get('product')
            if product_code:
                try:
                    product = ProductMaster.objects.get(product_code__iexact=product_code)
                    data['product'] = product.pk
                except ProductMaster.DoesNotExist:
                    return Response({"status": "error", "message": "Product not found"}, status=status.HTTP_404_NOT_FOUND)

            serializer = FAQSerializer(faq, data=data, partial=True, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                logger.info(f"FAQ updated: id={faq.id}")
                return Response({"status": "success", "message": "FAQ updated successfully", "data": serializer.data})

            logger.warning(f"FAQ update failed: id={faq.id}, errors={serializer.errors}")
            return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"FAQ Update failed: error={str(e)}")
            return Response({"status": "error", "message": "Failed to Updated FAQ"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def destroy(self, request, pk=None):
        try:
            if request.query_params.get('admin_id') != MEDIA_ADMIN_ID or request.query_params.get('password') != MEDIA_ADMIN_PASSWORD:
                return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

            try:
                faq = FAQ.objects.get(pk=pk)
            except FAQ.DoesNotExist:
                return Response({"status": "error", "message": "FAQ not found"}, status=status.HTTP_404_NOT_FOUND)

            faq.delete()
            logger.info(f"FAQ deleted: id={pk}")
            return Response({"status": "success", "message": "FAQ deleted successfully"}, status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            logger.error(f"FAQItem delete failed: id={pk}, error={str(e)}")
            return Response({"status": "error", "message": "Failed to delete FAQ"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

#  FAQItem
class FAQItemViewSet(viewsets.ViewSet):

    def list(self, request):
        try:
            faq_id = request.query_params.get('faq')
            if not faq_id:
                return Response({"status": "error", "message": "faq parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

            items = FAQItem.objects.filter(faq_id=faq_id).order_by('order')
            serializer = FAQItemSerializer(items, many=True, context={'request': request})
            logger.info(f"FAQItem list fetched: faq_id={faq_id}, count={items.count()}")
            return Response({"status": "success", "count": items.count(), "data": serializer.data})
        except Exception as e:
            logger.error(f"FAQItem list failed: error={str(e)}")
            return Response({"status": "error", "message": "Failed to fetch FAQ items"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def create(self, request):
        try:
            if request.query_params.get('admin_id') != MEDIA_ADMIN_ID or request.query_params.get('password') != MEDIA_ADMIN_PASSWORD:
                logger.warning("FAQItem create failed: unauthorized attempt")
                return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

            faq_id = request.data.get('faq')
            if not faq_id:
                return Response({"status": "error", "message": "faq is required"}, status=status.HTTP_400_BAD_REQUEST)

            try:
                FAQ.objects.get(pk=faq_id)
            except FAQ.DoesNotExist:
                logger.warning(f"FAQItem create failed: FAQ not found faq_id={faq_id}")
                return Response({"status": "error", "message": "FAQ not found"}, status=status.HTTP_404_NOT_FOUND)

            serializer = FAQItemSerializer(data=request.data, context={'request': request})
            if serializer.is_valid():
                item = serializer.save()
                logger.info(f"FAQItem created: faq_id={faq_id}, id={item.id}")
                return Response({
                    "status": "success", "message": "FAQ item created successfully", "data": serializer.data,
                }, status=status.HTTP_201_CREATED)

            logger.warning(f"FAQItem create validation failed: errors={serializer.errors}")
            return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"FAQItem create failed: error={str(e)}")
            return Response({"status": "error", "message": "Failed to create FAQ item"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def update(self, request, pk=None):
        try:
            if request.query_params.get('admin_id') != MEDIA_ADMIN_ID or request.query_params.get('password') != MEDIA_ADMIN_PASSWORD:
                logger.warning(f"FAQItem update failed: unauthorized attempt id={pk}")
                return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

            try:
                item = FAQItem.objects.get(pk=pk)
            except FAQItem.DoesNotExist:
                logger.warning(f"FAQItem update failed: not found id={pk}")
                return Response({"status": "error", "message": "FAQ item not found"}, status=status.HTTP_404_NOT_FOUND)

            serializer = FAQItemSerializer(item, data=request.data, partial=True, context={'request': request})
            if serializer.is_valid():
                serializer.save()
                logger.info(f"FAQItem updated: id={item.id}")
                return Response({"status": "success", "message": "FAQ item updated successfully", "data": serializer.data})

            logger.warning(f"FAQItem update failed: id={item.id}, errors={serializer.errors}")
            return Response({"status": "error", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"FAQItem update failed: id={pk}, error={str(e)}")
            return Response({"status": "error", "message": "Failed to update FAQ item"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def destroy(self, request, pk=None):
        try:
            if request.query_params.get('admin_id') != MEDIA_ADMIN_ID or request.query_params.get('password') != MEDIA_ADMIN_PASSWORD:
                logger.warning(f"FAQItem update failed: unauthorized attempt id={pk}")
                return Response({"status": "error", "message": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)
            try:
                item = FAQItem.objects.get(pk=pk)
            except FAQItem.DoesNotExist:
                return Response({"status": "error", "message": "FAQ item not found"}, status=status.HTTP_404_NOT_FOUND)
            item.delete()
            logger.info(f"FAQItem deleted: id={pk}")
            return Response({"status": "success", "message": "FAQ item deleted successfully"}, status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            logger.error(f"FAQItem Delete failed: id={pk}, error={str(e)}")
            return Response({"status": "error", "message": "Failed to Delete FAQ item"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class StaticDeviceValidationViewSet(viewsets.ViewSet):
    def _handle(self, request, params):
        device_serial_no = params.get('device_serial_no') or params.get('device_number')
        if not device_serial_no:
            return Response(
                {"status": "error", "message": "device_serial_no (or device_number) is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        device_serial_no = str(device_serial_no).strip()
        expiry_date_str = params.get('expiry_date')
        expiry_date = None
        if expiry_date_str:
            expiry_date = parse_date(expiry_date_str) or parse_datetime(expiry_date_str)
            if not expiry_date:
                return Response(
                    {"status": "error", "message": "Invalid expiry_date format. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        logger.info(f"Static device validation OK: serial={device_serial_no}")

        return Response({
            "status": "success",
            "message": "Device is valid",
            "data": {
                "device_serial_no": device_serial_no,
                "device_status":    "ACTIVE",
                "is_valid":         True,
                "expiry_date":      expiry_date,   # null if not provided
                "note":             "This is a static/temporary validation response for testing purposes.",
            },
        })

    def list(self, request):
        return self._handle(request, request.query_params)

    def create(self, request):
        return self._handle(request, request.data)



#Trends
class TrendViewSet(viewsets.ViewSet):

    def list(self, request):
        user_id = request.query_params.get('user')
        if not user_id:
            return Response({"status": "error", "message": "user parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        trends = Trend.objects.filter(user=user).order_by('-start_time')

        from_date_str = request.query_params.get('from_date')
        to_date_str   = request.query_params.get('to_date')
        if from_date_str:
            from_dt = parse_datetime(from_date_str) or parse_date(from_date_str)
            if from_dt:
                trends = trends.filter(start_time__gte=from_dt)
        if to_date_str:
            to_dt = parse_datetime(to_date_str) or parse_date(to_date_str)
            if to_dt:
                trends = trends.filter(end_time__lte=to_dt)

        serializer = TrendSerializer(trends, many=True)
        return Response({"status": "success", "count": trends.count(), "data": serializer.data})

    def create(self, request):
        user_id       = request.data.get('user')
        start_time    = request.data.get('start_time')
        end_time      = request.data.get('end_time')
        trend_type_in = request.data.get('trend_type')
        glucose_min   = request.data.get('glucose_min')
        glucose_max   = request.data.get('glucose_max')
        glucose_start = request.data.get('glucose_start')
        glucose_end   = request.data.get('glucose_end')

        # user, start_time, end_time, trend_type are mandatory
        required = {
            'user': user_id, 'start_time': start_time,
            'end_time': end_time, 'trend_type': trend_type_in,
        }
        missing = [k for k, v in required.items() if v in (None, '')]
        if missing:
            return Response(
                {"status": "error", "message": f"Missing required field(s): {', '.join(missing)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # trend_type must be one of the defined choices
        valid_types = dict(Trend.TREND_TYPE_CHOICES)
        if trend_type_in not in valid_types:
            return Response(
                {"status": "error", "message": f"trend_type must be one of {list(valid_types.keys())}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        trend_type = trend_type_in

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            logger.warning(f"Trend create failed: user not found user_id={user_id}")
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_400_BAD_REQUEST)

        start_dt = parse_datetime(start_time)
        end_dt   = parse_datetime(end_time)
        if not start_dt or not end_dt:
            return Response({"status": "error", "message": "start_time/end_time must be valid datetimes"}, status=status.HTTP_400_BAD_REQUEST)
        if end_dt <= start_dt:
            return Response({"status": "error", "message": "end_time must be after start_time"}, status=status.HTTP_400_BAD_REQUEST)

        # glucose_start / glucose_end: optional, default 0
        try:
            glucose_start = int(glucose_start) if glucose_start not in (None, '') else 0
        except (TypeError, ValueError):
            return Response({"status": "error", "message": "glucose_start must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            glucose_end = int(glucose_end) if glucose_end not in (None, '') else 0
        except (TypeError, ValueError):
            return Response({"status": "error", "message": "glucose_end must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        # glucose_min / glucose_max: optional, derive from start/end if not sent
        try:
            glucose_min = int(glucose_min) if glucose_min not in (None, '') else min(glucose_start, glucose_end)
        except (TypeError, ValueError):
            return Response({"status": "error", "message": "glucose_min must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            glucose_max = int(glucose_max) if glucose_max not in (None, '') else max(glucose_start, glucose_end)
        except (TypeError, ValueError):
            return Response({"status": "error", "message": "glucose_max must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        if Trend.objects.filter(user=user, start_time=start_dt, end_time=end_dt).exists():
            return Response(
                {"status": "error", "message": "A trend for this user with the same start_time and end_time already exists"},
                status=status.HTTP_409_CONFLICT,
            )

        trend = Trend.objects.create(
            user=user,
            start_time=start_dt,
            end_time=end_dt,
            glucose_min=glucose_min,
            glucose_max=glucose_max,
            glucose_start=glucose_start,
            glucose_end=glucose_end,
            trend_duration=end_dt - start_dt,
            trend_type=trend_type,
        )

        logger.info(f"Trend created: user_id={user.user_id}, type={trend_type}, {start_dt} -> {end_dt}")

        serializer = TrendSerializer(trend)
        return Response({
            "status":  "success",
            "message": "Trend created successfully",
            "data":    serializer.data,
        }, status=status.HTTP_201_CREATED)
    def update(self, request, pk=None):
        return self._update_trend(request, pk, partial=False)

    def partial_update(self, request, pk=None):
        return self._update_trend(request, pk, partial=True)

    def _update_trend(self, request, pk, partial):
        try:
            trend = Trend.objects.get(pk=pk)
        except Trend.DoesNotExist:
            return Response({"status": "error", "message": "Trend not found"}, status=status.HTTP_404_NOT_FOUND)

        user_id       = request.data.get('user')
        start_time    = request.data.get('start_time')
        end_time      = request.data.get('end_time')
        trend_type_in = request.data.get('trend_type')
        glucose_min   = request.data.get('glucose_min')
        glucose_max   = request.data.get('glucose_max')
        glucose_start = request.data.get('glucose_start')
        glucose_end   = request.data.get('glucose_end')

        # For a full update (PUT), user/start_time/end_time/trend_type stay mandatory
        if not partial:
            required = {
                'user': user_id, 'start_time': start_time,
                'end_time': end_time, 'trend_type': trend_type_in,
            }
            missing = [k for k, v in required.items() if v in (None, '')]
            if missing:
                return Response(
                    {"status": "error", "message": f"Missing required field(s): {', '.join(missing)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # user: change owner only if explicitly provided
        if user_id not in (None, ''):
            try:
                user = UserMaster.objects.get(user_id=user_id)
            except UserMaster.DoesNotExist:
                logger.warning(f"Trend update failed: user not found user_id={user_id}")
                return Response({"status": "error", "message": "User not found"}, status=status.HTTP_400_BAD_REQUEST)
            trend.user = user

        # trend_type: validate against choices if provided
        if trend_type_in not in (None, ''):
            valid_types = dict(Trend.TREND_TYPE_CHOICES)
            if trend_type_in not in valid_types:
                return Response(
                    {"status": "error", "message": f"trend_type must be one of {list(valid_types.keys())}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            trend.trend_type = trend_type_in

        # start_time / end_time: parse if provided, else keep existing
        new_start_dt = trend.start_time
        new_end_dt   = trend.end_time

        if start_time not in (None, ''):
            new_start_dt = parse_datetime(start_time)
            if not new_start_dt:
                return Response({"status": "error", "message": "start_time must be a valid datetime"}, status=status.HTTP_400_BAD_REQUEST)

        if end_time not in (None, ''):
            new_end_dt = parse_datetime(end_time)
            if not new_end_dt:
                return Response({"status": "error", "message": "end_time must be a valid datetime"}, status=status.HTTP_400_BAD_REQUEST)

        if new_end_dt <= new_start_dt:
            return Response({"status": "error", "message": "end_time must be after start_time"}, status=status.HTTP_400_BAD_REQUEST)

        # glucose_start / glucose_end: update if provided
        if glucose_start not in (None, ''):
            try:
                trend.glucose_start = int(glucose_start)
            except (TypeError, ValueError):
                return Response({"status": "error", "message": "glucose_start must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        if glucose_end not in (None, ''):
            try:
                trend.glucose_end = int(glucose_end)
            except (TypeError, ValueError):
                return Response({"status": "error", "message": "glucose_end must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        # glucose_min / glucose_max: update if provided, else leave as-is
        if glucose_min not in (None, ''):
            try:
                trend.glucose_min = int(glucose_min)
            except (TypeError, ValueError):
                return Response({"status": "error", "message": "glucose_min must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        if glucose_max not in (None, ''):
            try:
                trend.glucose_max = int(glucose_max)
            except (TypeError, ValueError):
                return Response({"status": "error", "message": "glucose_max must be an integer"}, status=status.HTTP_400_BAD_REQUEST)

        # Check duplicate (user, start_time, end_time) excluding this trend itself
        if Trend.objects.filter(
                user=trend.user, start_time=new_start_dt, end_time=new_end_dt
        ).exclude(pk=trend.pk).exists():
            return Response(
                {"status": "error", "message": "Another trend for this user with the same start_time and end_time already exists"},
                status=status.HTTP_409_CONFLICT,
            )

        trend.start_time = new_start_dt
        trend.end_time   = new_end_dt
        trend.trend_duration = new_end_dt - new_start_dt
        trend.save()

        logger.info(f"Trend updated: id={trend.id}, user_id={trend.user.user_id}")

        serializer = TrendSerializer(trend)
        return Response({
            "status":  "success",
            "message": "Trend updated successfully",
            "data":    serializer.data,
        })


#Spiking Features (High and Low)

def _error(message, http_status=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({"status": "error", "message": message, **extra}, status=http_status)


def event_type_for_log(log):
    """Same thresholds as LogEntryViewSet._create_alert_if_out_of_range."""
    gv = log.glucose_value
    if gv is None:
        return None
    if gv < LOW_GLUCOSE_THRESHOLD:
        return 'LOW'
    if gv > HIGH_GLUCOSE_THRESHOLD:
        return 'HIGH'
    return None
def _find_log(user, timestamp_str, glucose_value=None):
    """Find a reading by user + timestamp (same minute) + optional glucose_value."""
    if not timestamp_str:
        return None
    dt_value = parse_datetime(str(timestamp_str))
    if dt_value is None:
        return None
    if timezone.is_naive(dt_value):
        dt_value = timezone.make_aware(dt_value, timezone.get_current_timezone())

    minute_start = dt_value.replace(second=0, microsecond=0)
    qs = LogEntry.objects.filter(
        user=user,
        timestamp__gte=minute_start,
        timestamp__lt=minute_start + timedelta(minutes=1),
    )

    if glucose_value not in (None, ''):
        try:
            gv = float(glucose_value)
        except (TypeError, ValueError):
            return None
        qs = qs.filter(glucose_value__gte=gv - 0.01, glucose_value__lte=gv + 0.01)

    return qs.order_by('-id').first()


def _successors(question):
    nxt = [o.next_question_id for o in question.options.all() if o.next_question_id]
    if question.next_question_id:
        nxt.append(question.next_question_id)
    return set(nxt)


def _compute_que_counts(questions_by_pk):
    """
    queCount = number of questions on the LONGEST remaining path, including this one.
    Lets mobile draw a progress bar even though branches have different lengths.
    Raises ValueError on a loop in the question tree.
    """
    memo, visiting = {}, set()

    def depth(pk):
        if pk in memo:
            return memo[pk]
        if pk in visiting:
            raise ValueError(f"Loop detected at question {questions_by_pk[pk].question_id}")
        visiting.add(pk)
        best = 0
        for nxt in _successors(questions_by_pk[pk]):
            if nxt in questions_by_pk:            # inactive targets are ignored
                best = max(best, depth(nxt))
        visiting.discard(pk)
        memo[pk] = best + 1
        return memo[pk]

    for pk in questions_by_pk:
        depth(pk)
    return memo


def _serialize_response(resp):
    return {
        "response_id":   resp.id,
        "log_id":        resp.log_id,
        "user":          resp.user_id,
        "event_type":    resp.event_type,
        "glucose_value": resp.log.glucose_value,
        "timestamp":     timezone.localtime(resp.log.timestamp),
        "created_at":    timezone.localtime(resp.created_at),
        "answers": [
            {
                "step":        a.step,
                "question_id": a.question.question_id,
                "question":    a.question_text,
                "option_ids":  [o.option_id for o in a.selected_options.all()],
                "labels":      a.option_labels,
                "text":        a.text_answer or "",
            }
            for a in resp.answers.all()
        ],
    }


#questions
class SpikeQuestionViewSet(viewsets.ViewSet):
    def list(self, request):
        event_type = (request.query_params.get('event_type') or '').upper()
        if event_type not in EVENT_TYPES:
            return _error("event_type must be LOW or HIGH")

        questions = list(
            SpikeQuestion.objects
            .filter(event_type=event_type, is_active=True)
            .select_related('next_question')
            .prefetch_related('options__next_question')
        )
        start = next((q for q in questions if q.is_start), None)
        if not start:
            logger.error(f"Spike questions: no start question for event_type={event_type}")
            return _error(f"No start question configured for {event_type}",
                          status.HTTP_500_INTERNAL_SERVER_ERROR)

        by_pk = {q.pk: q for q in questions}
        try:
            que_counts = _compute_que_counts(by_pk)
        except ValueError as e:
            logger.error(f"Spike questions: {e}")
            return _error("Questionnaire is misconfigured (loop)", status.HTTP_500_INTERNAL_SERVER_ERROR)

        def _next_id(q):
            return q.question_id if (q and q.pk in by_pk) else None

        data = {}
        for q in questions:
            data[q.question_id] = {
                "id":                   q.question_id,
                "question":             q.question,
                "desc":                 q.desc,
                "queCount":             que_counts[q.pk],
                "isTextAllow":          q.is_text_allow,
                "isMultipleChoiceAllow": q.is_multiple_choice_allow,
                "isFollowUp":           q.is_follow_up,                 # NEW
                "nextQuestionId":       _next_id(q.next_question),
                "options": [
                    {
                        "id":             o.option_id,
                        "label":          o.label,
                        "desc":           o.desc,
                        "iconUrl":        o.icon_url or None,           # NEW
                        "nextQuestionId": _next_id(o.next_question),
                    }
                    for o in q.options.all()
                ],
            }

        return Response({"status": "success", "data": {
            "event_type":      event_type,
            "startQuestionId": start.question_id,
            "totalQuestions":  que_counts[start.pk],
            "questions":       data,
        }})


# user responses  #

class SpikeResponseViewSet(viewsets.ViewSet):

    def list(self, request):
        user_id = request.query_params.get('user')
        ts      = request.query_params.get('timestamp')

        qs = (SpikeResponse.objects
              .select_related('log')
              .prefetch_related('answers__question', 'answers__selected_options'))

        if not user_id:
            return _error("user parameter is required")
        user = UserMaster.objects.filter(user_id=user_id).first()
        if not user:
            return _error("User not found", status.HTTP_404_NOT_FOUND)

        # one specific reading: is it answered?
        if ts:
            log = _find_log(user, ts, request.query_params.get('glucose_value'))
            if not log:
                return _error("Reading not found", status.HTTP_404_NOT_FOUND)
            resp = qs.filter(log=log).first()
            if not resp:
                return Response({"status": "success", "answered": False, "data": None})
            return Response({"status": "success", "answered": True, "data": _serialize_response(resp)})

        # history
        qs = qs.filter(user_id=user_id)
        event_type = (request.query_params.get('event_type') or '').upper()
        if event_type in EVENT_TYPES:
            qs = qs.filter(event_type=event_type)

        log_ids = _filter_logs_by_date(
            LogEntry.objects.filter(user_id=user_id),
            request.query_params.get('from_date'),
            request.query_params.get('to_date'),
        ).values('id')
        qs = qs.filter(log_id__in=log_ids)

        data = [_serialize_response(r) for r in qs]
        return Response({"status": "success", "count": len(data), "data": data})

    def create(self, request):
        user_id = request.data.get('user')
        answers = request.data.get('answers') or []

        if not user_id:
            return _error("user is required")
        if not isinstance(answers, list) or not answers:
            return _error("answers must be a non-empty list")

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return _error("User not found", status.HTTP_404_NOT_FOUND)

        # ---------------- CHANGED: find reading by timestamp + glucose_value ----------------
        if not request.data.get('timestamp'):
            return _error("timestamp is required")
        if request.data.get('glucose_value') in (None, ''):
            return _error("glucose_value is required")

        log = _find_log(user, request.data.get('timestamp'), request.data.get('glucose_value'))
        if not log:
            return _error("No reading found for this user with that timestamp and glucose value",
                          status.HTTP_404_NOT_FOUND)
        # ------------------------------------------------------------------------------------

        event_type = event_type_for_log(log)          # derived from glucose_value, never from mobile
        if not event_type:
            return _error(f"Reading {log.glucose_value} mg/dL is within range")

        if SpikeResponse.objects.filter(log=log).exists():
            return _error("A response for this reading already exists", status.HTTP_409_CONFLICT)

        # ---- walk the path the user actually took ----
        current = (SpikeQuestion.objects
                   .filter(event_type=event_type, is_start=True, is_active=True)
                   .prefetch_related('options').first())
        if not current:
            return _error("Questionnaire not configured", status.HTTP_500_INTERNAL_SERVER_ERROR)

        validated = []
        for step, ans in enumerate(answers, start=1):
            if not isinstance(ans, dict):
                return _error(f"Step {step}: each answer must be an object")
            if current is None:
                return _error(f"Unexpected extra answer at step {step}")

            qid = ans.get('question_id')
            if qid != current.question_id:
                return _error(f"Step {step}: expected question '{current.question_id}', got '{qid}'")

            option_ids = ans.get('option_ids') or []
            if not isinstance(option_ids, list):
                return _error(f"'{qid}': option_ids must be a list")
            text = (ans.get('text') or '').strip()

            all_options = {o.option_id: o for o in current.options.all()}
            unknown = [oid for oid in option_ids if oid not in all_options]
            if unknown:
                return _error(f"'{qid}': invalid option(s) {unknown}")
            options = [all_options[oid] for oid in dict.fromkeys(option_ids)]   # de-dup, keep order

            if len(options) > 1 and not current.is_multiple_choice_allow:
                return _error(f"'{qid}' allows only one option")
            if text and not current.is_text_allow:
                return _error(f"'{qid}' does not accept text")
            if not options and not text:
                return _error(f"'{qid}' needs an answer")
            if all_options and not options and not current.is_text_allow:
                return _error(f"'{qid}' needs an option")

            validated.append((step, current, options, text))

            # Branching: single-choice -> option.next ; multi-select / text -> question.next
            if len(options) == 1 and not current.is_multiple_choice_allow:
                nxt = options[0].next_question
            else:
                nxt = current.next_question
            current = (SpikeQuestion.objects.prefetch_related('options')
                       .filter(pk=nxt.pk, is_active=True).first()) if nxt else None

        if current is not None:
            return _error(f"Questionnaire incomplete; next question is '{current.question_id}'",
                          next_question_id=current.question_id)

        # ---- save ----
        try:
            with transaction.atomic():
                resp = SpikeResponse.objects.create(log=log, user=user, event_type=event_type)
                for step, question, options, text in validated:
                    answer = SpikeAnswer.objects.create(
                        response=resp,
                        question=question,
                        text_answer=text or None,
                        question_text=question.question,
                        option_labels=[o.label for o in options],
                        step=step,
                    )
                    if options:
                        answer.selected_options.set(options)
        except IntegrityError:
            return _error("A response for this reading already exists", status.HTTP_409_CONFLICT)

        logger.info(f"Spike response saved: user_id={user.user_id}, log_id={log.id}, "
                    f"event={event_type}, glucose={log.glucose_value}, steps={len(validated)}")

        resp = (SpikeResponse.objects.select_related('log')
                .prefetch_related('answers__question', 'answers__selected_options').get(pk=resp.pk))
        return Response({
            "status":  "success",
            "message": "Response saved",
            "data":    _serialize_response(resp),
        }, status=status.HTTP_201_CREATED)











