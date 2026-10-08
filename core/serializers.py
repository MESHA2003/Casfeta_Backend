"""Shared serializers reused across CZDMP modules (SRS 54)."""

from django.contrib.auth.models import User
from rest_framework import serializers

from .models import AcademicYear, ContactMessage, District, FinancialPolicy, Institution, Organization, SystemSetting


class UserMiniSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'full_name']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username


class UserNameSerializer(serializers.ModelSerializer):
    """Minimal, privacy friendly representation (SRS 46)."""

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'full_name']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username


class DistrictMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = District
        fields = ['id', 'name', 'code', 'region']


class DistrictSerializer(serializers.ModelSerializer):
    """Full district record used by the configuration screens (SRS 52, 86)."""

    parent_name = serializers.CharField(source='parent.name', read_only=True, default=None)
    institution_count = serializers.SerializerMethodField()

    class Meta:
        model = District
        fields = [
            'id', 'name', 'code', 'region', 'parent', 'parent_name', 'is_active',
            'institution_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_institution_count(self, obj):
        return obj.institutions.count()



class InstitutionMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Institution
        fields = ['id', 'name', 'code', 'institution_type']


class InstitutionSerializer(serializers.ModelSerializer):
    district_detail = DistrictMiniSerializer(source='district', read_only=True)
    branch_count = serializers.SerializerMethodField()

    class Meta:
        model = Institution
        fields = [
            'id', 'name', 'code', 'institution_type', 'district', 'district_detail',
            'location', 'is_active', 'branch_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_branch_count(self, obj):
        return obj.branches.count()


class BranchMiniSerializer(serializers.ModelSerializer):
    class Meta:
        from branches.models import Branch

        model = Branch
        fields = ['id', 'name', 'code', 'status']


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        exclude = []
        read_only_fields = ['created_at', 'updated_at']


class OrganizationPublicSerializer(serializers.ModelSerializer):
    """Public website configuration (SRS 37, 38)."""

    class Meta:
        model = Organization
        fields = [
            'name', 'short_name', 'motto', 'vision', 'mission', 'about', 'core_values',
            'logo', 'address', 'contact_email', 'contact_phone', 'whatsapp', 'website',
            'facebook', 'instagram', 'youtube', 'currency', 'default_language', 'region_scope',
        ]


class SystemSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSetting
        fields = [
            'id', 'key', 'value', 'value_type', 'group', 'label', 'description',
            'is_public', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class AcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = [
            'id', 'name', 'start_date', 'end_date', 'is_current', 'is_membership_year',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class FinancialPolicySerializer(serializers.ModelSerializer):
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True, default=None)

    class Meta:
        model = FinancialPolicy
        fields = [
            'id', 'name', 'contribution_percentage', 'effective_date', 'status',
            'description', 'approved_by', 'approved_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['approved_by', 'created_at', 'updated_at']

    def validate_contribution_percentage(self, value):
        if value is None or value < 0 or value > 100:
            raise serializers.ValidationError('Percentage must be between 0 and 100.')
        return value


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = [
            'id', 'full_name', 'email', 'phone', 'subject', 'message', 'status',
            'handled_by', 'response_notes', 'created_at',
        ]
        read_only_fields = ['status', 'handled_by', 'response_notes', 'created_at']


class MoneySerializer(serializers.Serializer):
    """Currency aware money representation (SRS 87 - TZS 100,000)."""

    amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    currency = serializers.CharField(default='TZS')
    formatted = serializers.CharField()
