from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import *
from django.conf.urls.static import static
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from insights.views import InsightsViewSet



router = DefaultRouter()
router.register(r'versions', VersionViewSet)
router.register(r'logentries', LogEntryViewSet)   #  NEW API endpoint
router.register(r'users', UserMasterViewSet, basename='users')
router.register(r'logentries-userwise', UserWiseLogEntryViewSet, basename='logentries-userwise')
router.register(r'devices', DeviceMasterViewSet, basename='devices')
# router.register(r'reset-password', ResetPasswordViewSet, basename='reset-password')
router.register(r'app-media',AppMediaViewSet, basename='app-media')
router.register(r'caregivers', CaregiverMasterViewSet, basename='caregivers')  # caregiver
router.register(r'terms', TermsAndConditionsViewSet, basename='terms') #terms and conditions
router.register(r'consents', UserConsentViewSet, basename='consents')  #saving data in the user acceptance
router.register(r'audit-logs',AuditLogViewSet,basename='audit-logs')
router.register(r'reports',ReportViewSet,basename='reports')
router.register(r'alerts',AlertViewSet,basename='alerts')
router.register(r'user-preference',UserPreferenceViewSet,basename='user-preference')
router.register(r'products', ProductMasterViewSet, basename='product-master') ##product master
router.register(r'agp', AGPReportViewSet, basename='agp') #AGP.
router.register(r"FAQ",FAQViewSet,basename='FAQ')
router.register(r'faq-items', FAQItemViewSet, basename='faq-items')  #faq items
router.register(r'device-validate', StaticDeviceValidationViewSet, basename='device-static-validate')
router.register(r'trends', TrendViewSet, basename='trend')
router.register(r'insights', InsightsViewSet, basename='insights')
router.register(r'spike/questions', SpikeQuestionViewSet, basename='spike-questions')   #spiking features
router.register(r'spike/responses', SpikeResponseViewSet, basename='spike-responses')
urlpatterns = [
    path('', include(router.urls)),
    path('version/', version_page, name='version-page'),
    path('logs/', log_entries_page, name='logs-page'),
    path('userwiselogs/', user_wise_log_entries_page, name='user_wise_logs-page'),
    path('report/json/<str:user_id>/', glucose_report_json, name='glucose-report-json'),
    path('report/html/<str:user_id>/', glucose_report_html, name='glucose-report-html'),
    path('logs/user-wise/', user_wise_view, name='user-wise-view'),
    path('reset-password/', ResetPasswordViewSet.as_view({'get': 'list', 'post': 'create'}), name='reset-password'),
    #path('app-media/login/', app_media_login, name='app-media-login'),
    path('reset-password/verify_otp/', ResetPasswordViewSet.as_view({'post': 'verify_otp'}), name='reset-password-verify-otp'),
    path('reset-password/redirect/', reset_password_redirect_page, name='reset-password-redirect'),
    path('app-media/upload/', app_media_upload, name='app-media-upload'),
    path("caregiver/accept/<uuid:token>/", caregiver_accept_page, name="caregiver_accept"),
    path('delete-account/', DeleteAccountViewSet.as_view({'get': 'list', 'post': 'create'}), name='delete-account'),
    path('api/user-preference/<str:pk>/', UserPreferenceViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update'}), name='user-preference-detail'),
             
              ] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)