from django.db import models
import re
import uuid
from api.validators import validate_phone_number


def normalize_mobile_number(value):
    if not value:
        return value

    value = value.strip()
    has_plus = value.startswith('+')
    digits = re.sub(r'\D', '', value)

    if not digits:
        return value

    return f"+{digits}" if has_plus else digits
class Version(models.Model):
    version = models.CharField(max_length=50)   # e.g. "v1.2.0"
    description = models.TextField()            # e.g. "Initial public release"

    def __str__(self):
        return self.version

class LogEntry(models.Model):
    user = models.ForeignKey("UserMaster", on_delete=models.CASCADE)  # <--- Use string reference
    glucose_value = models.FloatField()
    amp = models.FloatField()
    timestamp = models.DateTimeField()
    note = models.TextField(null=True, blank=True)
    deviceid = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)  #automatically save date and time
    def __str__(self):
            return f"{self.user.user_id} - {self.glucose_value} mg/dL"

class UserMaster(models.Model):
    user_id = models.CharField(
        max_length=20,
        primary_key=True,
        editable=True,
        unique=True
    )
    first_name = models.CharField(max_length=100,)
    middle_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100,null=True, blank=True)
    email_id=models.EmailField(unique=True,null=True, blank=False)
    password = models.CharField(max_length=255,null=True, blank=True)
    GENDER_CHOICES = [
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other'),
    ]
    gender = models.CharField(max_length=10,choices=GENDER_CHOICES,null=True, blank=True)
    dob = models.DateField(null=True, blank=True)
    mobile_number = models.CharField(max_length=20,null=True, blank=True,unique=True,validators=[validate_phone_number])
    address = models.TextField(null=True, blank=True)
    city = models.CharField(max_length=100,null=True, blank=True)
    state = models.CharField(max_length=100,null=True, blank=True)
    zip_code = models.CharField(max_length=20,null=True, blank=True)
    isNewUser = models.BooleanField(default=True) #for new user
    profile_picture = models.ImageField(
        upload_to='profile_pics/',
        null=True,
        blank=True
    )
    google_profile_picture = models.URLField(null=True, blank=True)  # URL string from Google
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    #emergency Details user
    emergency_contact_number = models.CharField(max_length=20, null=True, blank=True)
    emergency_contact_name = models.CharField(max_length=100, null=True, blank=True,validators=[validate_phone_number])
    emergency_contact_relation = models.CharField(max_length=50, null=True, blank=True)
    #firebase token
    firebase_token = models.TextField(null=True, blank=True)
    def __str__(self):
        return f"{self.user_id} - {self.first_name} {self.last_name}"


    def save(self, *args, **kwargs):
        if self.email_id:
            self.email_id = self.email_id.lower().strip()

        if self.mobile_number:
            self.mobile_number = normalize_mobile_number(self.mobile_number)
        else:
            self.mobile_number= None

        if not self.user_id:
            prefix = "INNOIQCGM"
            last_user = UserMaster.objects.order_by('-user_id').first()
            if last_user:
                match = re.search(r'(\d+)$', last_user.user_id)
                last_number = int(match.group(1)) if match else 0
                new_number = last_number + 1
            else:
                new_number = 1
            self.user_id = f"{prefix}{new_number:05d}"

        super().save(*args, **kwargs)

#trend
class Trend(models.Model):
    user=models.ForeignKey("UserMaster",on_delete=models.CASCADE)
    start_time=models.DateTimeField()
    end_time=models.DateTimeField()

    glucose_min=models.IntegerField()
    glucose_max=models.IntegerField()

    glucose_start=models.IntegerField()
    glucose_end=models.IntegerField()

    trend_duration=models.DurationField()
    TREND_TYPE_CHOICES = [
        ('RISING_FAST',  'Rising fast'),     # Very High, >250
        ('RISING',       'Rising'),          # High, 180-250
        ('STABLE',       'Stable'),          # Target, 70-180
        ('FALLING',      'Falling'),         # Low, 54-70
        ('FALLING_FAST', 'Falling fast'),    # Very Low, <54
    ]
    trend_type = models.CharField(max_length=15, choices=TREND_TYPE_CHOICES)
    create_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[
            models.UniqueConstraint(
                fields=['user','start_time','end_time'],
                name='unique_user_trend_time'
            )
        ]
    def __str__(self):
        return f"{self.user.user_id} | {self.trend_type} | {self.start_time} - {self.end_time}"


##device master
class DeviceMaster(models.Model):
    user = models.ForeignKey("UserMaster", on_delete=models.CASCADE)
    device_serial_no = models.CharField(max_length=100, unique=True)
    device_type = models.CharField(max_length=50)
    batch_number = models.CharField(max_length=100, null=True, blank=True)  # updated field
    STATUS_CHOICES = [
            ('ACTIVE', 'Active'),
            ('EXPIRED', 'Expired'),
            ('REMOVED', 'Removed'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    life_span_days = models.IntegerField()
    assigned_at = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)
    def __str__(self):
        return f"{self.device_serial_no} - {self.status}"

##alert table
class Alert(models.Model):
    SEVERITY_CHOICES = [('LOW', 'Low'), ('HIGH', 'High')]
    user = models.ForeignKey("UserMaster", on_delete=models.CASCADE)
    log = models.ForeignKey("LogEntry", on_delete=models.CASCADE)
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, null=True, blank=True)
    reason = models.TextField()
    glucose_value = models.FloatField(null=True,blank=True)
    target_range_high = models.IntegerField(null=True,blank=True)
    target_range_low=models.IntegerField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    def __str__(self):
        return f"Alert for {self.user.user_id} - {self.reason[:20]}"


#alert response
class AlertResponse(models.Model):
    alert = models.ForeignKey("Alert", on_delete=models.CASCADE, related_name='responses')

    question_key = models.CharField(max_length=100)
    answer = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.question_key} - {self.answer}"

import uuid
####reset password or forgot password #####
class PasswordResetToken(models.Model):
    user = models.ForeignKey("UserMaster", on_delete=models.CASCADE)
    token= models.UUIDField(default=uuid.uuid4, unique=True,blank=True,null=True)
    otp_code=models.CharField(max_length=6,null=True,blank=True)
    otp_verified=models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_used = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.user_id} - {self.token}"



#for uploading images and slidshow
class AppMedia(models.Model):
    TYPE_CHOICES = [
        ('Image', 'Image'),
        ('Video', 'Video'),
    ]
    order = models.IntegerField(unique=True)
    file = models.FileField(upload_to='app_media/', null=True, blank=True)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    duration = models.PositiveIntegerField(default=5)  # seconds
    label = models.CharField(max_length=255, blank=True, default='')
    link = models.URLField(max_length=500, blank=True, default='')
    def __str__(self):
        return f"Slot {self.order} - {self.type or 'Empty'}"


class CaregiverMaster(models.Model):
    user = models.ForeignKey("UserMaster", on_delete=models.CASCADE, related_name='caregivers')
    full_name = models.CharField(max_length=100)
    email_id = models.EmailField()
    RELATIONSHIP_CHOICES = [
        ('Parent', 'Parent'),
        ('Spouse', 'Spouse'),
        ('Child', 'Child'),
        ('Sibling', 'Sibling'),
        ('Grandparent', 'Grandparent'),
        ('Guardian', 'Guardian'),
        ('Friend', 'Friend'),
        ('Caregiver', 'Caregiver'),
        ('Doctor', 'Doctor'),
        ('Nurse', 'Nurse'),
        ('Other', 'Other'),
    ]
    relationship = models.CharField(max_length=50, choices=RELATIONSHIP_CHOICES)
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('PENDING', 'Pending'),
        ('REMOVED', 'Removed'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')

    # Access permissions
    can_view_glucose = models.BooleanField(default=True)   # Real-time glucose
    can_view_alerts = models.BooleanField(default=True)    # Alerts
    can_view_reports = models.BooleanField(default=True)   # Reports
    can_view_trends = models.BooleanField(default=True)    # Trends
    #new field added mobile_number
    mobile_number = models.CharField(max_length=20, null=True, blank=True)
    invitation_token = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'email_id'],
                name='unique_user_caregiver_email'
            )
        ]

    def __str__(self):
        return f"{self.user.user_id} - {self.full_name} ({self.relationship})"

#terms & Conditions,IFU
class TermsAndConditions(models.Model):
    TYPE_CHOICES = [
        ('TERMS', 'Terms & Privacy Policy'),
        ('IFU',   'Instructions for Use'),
        ('BOTH',  'Both')
    ]
    type                       = models.CharField(max_length=10, choices=TYPE_CHOICES, default='BOTH')
    terms_content              = models.JSONField(null=True, blank=True)
    ifu_content                = models.JSONField(null=True, blank=True)
    terms_confirmation_text    = models.TextField(null=True, blank=True)  # ← terms checkbox text
    ifu_confirmation_text      = models.TextField(null=True, blank=True)  # ← IFU checkbox text
    version                    = models.IntegerField(default=1)
    is_active                  = models.BooleanField(default=True)
    created_at                 = models.DateTimeField(auto_now_add=True)
    updated_at                 = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'terms_and_conditions'


class UserConsent(models.Model):
    user                    = models.ForeignKey(UserMaster, on_delete=models.CASCADE, related_name='consents')
    terms                   = models.ForeignKey(TermsAndConditions, on_delete=models.CASCADE)
    is_terms_accepted       = models.BooleanField(default=False)  # ← terms checkbox
    is_ifu_accepted         = models.BooleanField(default=False)  # ← IFU checkbox
    terms_accepted_at       = models.DateTimeField(null=True, blank=True)
    ifu_accepted_at         = models.DateTimeField(null=True, blank=True)
    created_at              = models.DateTimeField(auto_now_add=True)
    updated_at              = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_consents'
        unique_together = ['user', 'terms']

class AuditLog(models.Model):
    user    = models.ForeignKey(UserMaster, on_delete=models.SET_NULL, null=True)
    device  = models.ForeignKey(DeviceMaster, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50)
    reason = models.TextField(null=True, blank=True)
    additional_notes = models.TextField(null=True, blank=True)  # optional extra notes
    timestamp =models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='audit_logs'
        ordering=['-timestamp']

    def __str__(self):
        return f"{self.user.user_id} | {self.action} | {self.timestamp}"
#changes
class UserPreference(models.Model):
    user=models.OneToOneField("UserMaster",on_delete=models.CASCADE,related_name='preference')
    target_range_high=models.IntegerField(default=180)
    target_range_low=models.IntegerField(default=70)

    language_code=models.CharField(max_length=10,default='en')
    UNIT_CHOICES=[
        ('mg/dL', 'mg/dL'),
        ('mmol/L', 'mmol/L'),
    ]
    glucose_unit = models.CharField(max_length=10, choices=UNIT_CHOICES, default='mg/dL')
    expiry_alert_days_before = models.IntegerField(default=7)
    # pdf_export_format = models.CharField(default='A4',null=True,blank=True)
    YESNO_CHOICES = [
        ('Y', 'Yes'),
        ('N', 'No'),
    ]
    personalized_health_suggestions = models.CharField(
        max_length=1,
        choices=YESNO_CHOICES,
        default='Y'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        db_table = 'user_preferences'

    def __str__(self):
        return f"{self.user.user_id} - Preferences"


#product master
class ProductMaster(models.Model):
    product_code = models.CharField(max_length=50, unique=True)
    description  = models.TextField(null=True, blank=True)

    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ACTIVE')

    # warm-up time(default 45 min)
    warm_up_minutes = models.PositiveIntegerField(default=45)
    life_span_days = models.PositiveIntegerField(default=14)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'product_master'

    def __str__(self):
        return f"{self.product_code} - {self.status}"


class FAQ(models.Model):
    product = models.ForeignKey("ProductMaster", on_delete=models.CASCADE, related_name="faqs")
    icon = models.ImageField(
        upload_to='FAQ_icons/',
        null=True,
        blank=True
    )
    title = models.CharField(max_length=255)
    subtext = models.TextField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "faq"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "title"],
                name="unique_product_faq_title"
            )
        ]

    def __str__(self):
        return f"{self.product.product_code}-{self.title}"


class FAQItem(models.Model):
    faq = models.ForeignKey(FAQ, on_delete=models.CASCADE, related_name="items")
    icon = models.ImageField(
        upload_to='FAQ_Item/',
        null=True,
        blank=True
    )
    title = models.CharField(max_length=255, null=True, blank=True)
    subtext = models.TextField(null=True, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "faq_item"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.faq.title} -> {self.title or self.subtext[:20]}"

