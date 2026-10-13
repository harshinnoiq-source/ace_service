import statistics
import datetime as dt
import logging

from django.utils import timezone
from django.utils.timezone import make_aware
from datetime import timedelta

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response

from google.api_core.exceptions import ClientError

from api.models import UserMaster, LogEntry, UserPreference   # <-- adjust 'api' to your actual app name if different
from api.views import ReportViewSet, AGPReportViewSet          # <-- same here
from .services.ai_insights import generate_insights

logger = logging.getLogger(__name__)
INSIGHTS_MIN_DAYS = 5
INSIGHTS_MAX_DAYS = 14

class InsightsViewSet(viewsets.ViewSet):

    def _get_metrics(self, user, days):
        to_date   = timezone.now().date()
        from_date = to_date - timedelta(days=days - 1)

        range_start = make_aware(dt.datetime.combine(from_date, dt.time.min))
        range_end   = make_aware(dt.datetime.combine(to_date, dt.time.max))

        logs = LogEntry.objects.filter(user=user, timestamp__gte=range_start, timestamp__lte=range_end)
        total         = logs.count()
        distinct_days = logs.values('timestamp__date').distinct().count()

        if distinct_days < INSIGHTS_MIN_DAYS:
            return None, distinct_days

        report_vs = ReportViewSet()
        agp_vs    = AGPReportViewSet()

        avg_glucose = round(statistics.fmean(logs.values_list('glucose_value', flat=True)), 1)
        hba1c_data  = report_vs._get_estimated_hba1c(logs, avg_glucose)

        metrics = {
            "period": {
                "from_date":      str(from_date),
                "to_date":        str(to_date),
                "days_available": distinct_days,
            },
            "statistics":      agp_vs._compute_agp_statistics(logs, from_date, to_date),
            "time_in_ranges":  agp_vs._compute_agp_time_in_ranges(logs, total),
            "estimated_hba1c": hba1c_data["estimated_hba1c"],
            "hba1c_eligible":  hba1c_data["hba1c_eligible"],
            "total_readings":  total,
        }
        return metrics, distinct_days

    @action(detail=False, methods=['get'], url_path='metrics')
    def metrics(self, request):
        user_id = request.query_params.get('user')
        if not user_id:
            return Response({"status": "error", "message": "user parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            days = int(request.query_params.get('days', INSIGHTS_MAX_DAYS))
        except (TypeError, ValueError):
            days = INSIGHTS_MAX_DAYS
        days = max(INSIGHTS_MIN_DAYS, min(days, INSIGHTS_MAX_DAYS))

        metrics_data, distinct_days = self._get_metrics(user, days)
        if metrics_data is None:
            return Response({
                "status": "error",
                "message": f"At least {INSIGHTS_MIN_DAYS} days of data are required. Currently {distinct_days} day(s) available.",
                "days_available": distinct_days,
                "days_required":  INSIGHTS_MIN_DAYS,
            }, status=status.HTTP_400_BAD_REQUEST)

        return Response({"status": "success", "data": metrics_data})

    def create(self, request):
        user_id = request.data.get('user')
        if not user_id:
            return Response({"status": "error", "message": "user is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = UserMaster.objects.get(user_id=user_id)
        except UserMaster.DoesNotExist:
            return Response({"status": "error", "message": "User not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            days = int(request.data.get('days', INSIGHTS_MAX_DAYS))
        except (TypeError, ValueError):
            days = INSIGHTS_MAX_DAYS
        days = max(INSIGHTS_MIN_DAYS, min(days, INSIGHTS_MAX_DAYS))

        metrics_data, distinct_days = self._get_metrics(user, days)
        if metrics_data is None:
            return Response({
                "status": "error",
                "message": f"At least {INSIGHTS_MIN_DAYS} days of data are required to generate insights. Currently {distinct_days} day(s) available.",
                "days_available": distinct_days,
                "days_required":  INSIGHTS_MIN_DAYS,
            }, status=status.HTTP_400_BAD_REQUEST)

        user_answers = {}
        for field in ('diet_type', 'activity_level', 'sleep_hours', 'stress_level'):
            value = request.data.get(field)
            if value:
                user_answers[field] = value

        user_profile = {
            "user_id":    user.user_id,
            "first_name": user.first_name,
            "gender":     user.gender,
            "dob":        str(user.dob) if user.dob else None,
        }
        try:
            preference = UserPreference.objects.get(user=user)
            user_profile["target_range_low"]  = preference.target_range_low
            user_profile["target_range_high"] = preference.target_range_high
            user_profile["glucose_unit"]      = preference.glucose_unit
        except UserPreference.DoesNotExist:
            pass

        try:
            result = generate_insights(
                metrics=metrics_data,
                user_answers=user_answers,
                user_profile=user_profile,
            )
        except ClientError as e:
            if getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e):
                logger.warning(f"Gemini rate limit hit: user_id={user_id}, error={e}")
                return Response(
                    {"status": "error", "message": "We're getting a lot of requests right now. Please try again in a few seconds."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            logger.error(f"Insight generation failed: user_id={user_id}, error={e}")
            return Response({"status": "error", "message": "Failed to generate insights. Please try again."}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception as e:
            logger.error(f"Insight generation failed: user_id={user_id}, error={e}")
            return Response({"status": "error", "message": "Failed to generate insights. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        logger.info(f"Insights generated: user_id={user_id}, days={days}")
        return Response({
            "status":  "success",
            "message": "Insights generated successfully",
            "data": {
                "insights": result,
                "period":   metrics_data["period"],
            },
        })