from rest_framework import serializers
from .models import *
from django.contrib.auth.hashers import make_password
from rest_framework import serializers
from django.contrib.auth.hashers import make_password


class VersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Version
        fields = '__all__'


class LogEntrySerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField()  # shows user_id in output

    class Meta:
        model = LogEntry
        fields = '__all__'


class UserMasterSerializer(serializers.ModelSerializer):

    class Meta:
        model = UserMaster
        fields = '__all__'
        extra_kwargs = {
            'user_id': {'read_only': True},
            'password': {'write_only': True,
                         'required':False, #password optional for mobile login
                         'allow_null':True,
                         'allow_blank':True,}
        }

    def validate_email_id(self, value):
        return value.lower().strip()

    # Create user
    def create(self, validated_data):
        password = validated_data.pop('password', None)

        user = UserMaster(**validated_data)

        if password:
            user.password = make_password(password)

        user.save()
        return user

    #  Update user
    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.password = make_password(password)

        instance.save()
        return instance
    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')

        if instance.profile_picture:
            if request:
                data['profile_picture'] = request.build_absolute_uri(instance.profile_picture.url)
            else:
                data['profile_picture'] = instance.profile_picture.url
        else:
            data['profile_picture'] = None

        return data


class AlertSerializer(serializers.ModelSerializer):
    glucose_value = serializers.FloatField(source='log.glucose_value', read_only=True)
    timestamp     = serializers.DateTimeField(source='log.timestamp', read_only=True)

    class Meta:
        model  = Alert
        fields = '__all__'

class DeviceMasterSerializer(serializers.ModelSerializer):
    class Meta:
        model=DeviceMaster
        fields='__all__'

class PasswordResetTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = PasswordResetToken
        fields = '__all__'




class AppMediaSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()

    class Meta:
        model = AppMedia
        fields = ['order', 'file', 'type', 'uploaded_at']

    def get_file(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


class AppMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppMedia
        fields = ['id', 'order', 'file', 'type', 'duration', 'label', 'link']

    def validate_file(self, value):
        max_size = 10 * 1024 * 1024  # 10 MB
        if value and value.size > max_size:
            raise serializers.ValidationError("File size must not exceed 10 MB.")
        return value

    def validate_type(self, value):
        if value not in ['Image', 'Video']:
            raise serializers.ValidationError("Type must be 'Image' or 'Video'.")
        return value



###caregiver
class CaregiverMasterSerializer(serializers.ModelSerializer):
    class Meta:
        model = CaregiverMaster
        fields = ['id','user','full_name','email_id','relationship','mobile_number','status','can_view_glucose','can_view_alerts','can_view_reports','can_view_trends','invitation_token','created_at','updated_at']
        read_only_fields = ['id','status','invitation_token','created_at','updated_at']




class GoogleSignInSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserMaster
        fields = ['user_id','first_name','middle_name','last_name','email_id','mobile_number','isNewUser','profile_picture','google_profile_picture','firebase_token','created_at','updated_at' ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if instance.profile_picture:
            if request:
                data['profile_picture'] = request.build_absolute_uri(instance.profile_picture.url)
            else:
                data['profile_picture'] = instance.profile_picture.url
        else:
            data['profile_picture'] = None
        return data

####  Terms & conditions,IFU terms and acceptance #####
# serializers.py

class TermsAndConditionsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TermsAndConditions
        fields = '__all__'
        read_only_fields = ['id', 'version', 'created_at', 'updated_at']


class UserConsentSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserConsent
        fields = '__all__'
        read_only_fields = ['id', 'accepted_at', 'created_at', 'updated_at']


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = '__all__'
        read_only_fields = ['id', 'timestamp']

class UserPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model=UserPreference
        fields='__all__'
        read_only_fields=['user','created_at','updated_at']

        def validate(self, data):
            low = data.get('target_range_low', getattr(self.instance, 'target_range_low', None))
            high = data.get('glucose_high_alert', getattr(self.instance, 'glucose_high_alert', None))

            if low is not None and high is not None and low >= high:
                raise serializers.ValidationError(
                    "glucose_low_alert must be less than glucose_high_alert"
                )
            return data


class ProductMasterSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductMaster
        fields = '__all__'



#Faq serializer
class FAQItemSerializer(serializers.ModelSerializer):
    icon = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = FAQItem
        fields = ['id', 'faq', 'icon', 'title', 'subtext', 'order']


class FAQSerializer(serializers.ModelSerializer):
    items         = FAQItemSerializer(many=True, read_only=True)
    icon          = serializers.ImageField(required=False, allow_null=True)
    product_code  = serializers.CharField(source='product.product_code', read_only=True)
    product_name  = serializers.SerializerMethodField()

    class Meta:
        model  = FAQ
        fields = [
            'id', 'product', 'product_code', 'product_name',
            'icon', 'title', 'subtext', 'order', 'is_active',
            'items', 'created_at', 'updated_at',
        ]

    def get_product_name(self, obj):
        return obj.product.description or obj.product.product_code


#trends
class TrendSerializer(serializers.ModelSerializer):
    user = serializers.SlugRelatedField(slug_field='user_id', queryset=UserMaster.objects.all())
    class Meta:
        model = Trend
        fields ="__all__"
