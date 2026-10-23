from django.contrib import admin
from .models import *


admin.site.register(LogEntry)
admin.site.register(UserMaster)
admin.site.register(Trend)
admin.site.register(DeviceMaster)
admin.site.register(Alert)
admin.site.register(AlertResponse)
admin.site.register(PasswordResetToken)
admin.site.register(AppMedia)
admin.site.register(CaregiverMaster)
admin.site.register(UserConsent)
admin.site.register(TermsAndConditions)
admin.site.register(AuditLog)
admin.site.register(ProductMaster)
admin.site.register(FAQ)
admin.site.register(FAQItem)
admin.site.register(SpikeQuestion)
admin.site.register(SpikeOption)
admin.site.register(SpikeResponse)
admin.site.register(SpikeAnswer)
