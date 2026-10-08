from rest_framework import serializers

from core import access
from core.serializers import BranchMiniSerializer, DistrictMiniSerializer, InstitutionMiniSerializer
from .models import Branch, BranchStatistics


class BranchStatisticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchStatistics
        fields = [
            'id', 'branch', 'period_year', 'period_month', 'total_members', 'new_members',
            'inactive_members', 'events_conducted', 'attendance_rate', 'report_submitted',
            'financial_report_compliance', 'label',
        ]
        read_only_fields = ['id', 'label']


class BranchSerializer(serializers.ModelSerializer):
    district_detail = DistrictMiniSerializer(source='district', read_only=True)
    institution_detail = InstitutionMiniSerializer(source='institution', read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    active_member_count = serializers.IntegerField(read_only=True)
    leader_names = serializers.SerializerMethodField()

    class Meta:
        model = Branch
        fields = [
            'id', 'name', 'code', 'slug', 'organization', 'district', 'district_detail',
            'institution', 'institution_detail', 'location', 'status', 'founded_year',
            'meeting_day', 'meeting_time', 'meeting_venue', 'contact_email', 'contact_phone',
            'description', 'is_active', 'member_count', 'active_member_count', 'leader_names',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['code', 'slug', 'created_at', 'updated_at', 'member_count', 'active_member_count']

    def get_leader_names(self, obj):
        return [
            {
                'name': term.user.get_full_name() or term.user.username,
                'position': term.position.title,
            }
            for term in obj.assigned_leaders()
        ]

    def validate_name(self, value):
        queryset = Branch.objects.filter(name__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError('A branch with this name already exists.')
        return value


class BranchPublicSerializer(serializers.ModelSerializer):
    """Public directory listing (SRS 37, 66) - no sensitive contact data."""

    district_name = serializers.CharField(source='district.name', read_only=True, default=None)
    institution_name = serializers.CharField(source='institution.name', read_only=True, default=None)

    class Meta:
        model = Branch
        fields = [
            'id', 'name', 'code', 'slug', 'district_name', 'institution_name',
            'location', 'status', 'founded_year', 'meeting_day', 'meeting_venue', 'description',
        ]


class BranchSummarySerializer(BranchMiniSerializer):
    """Compact branch payload used by selects and dashboards."""

    class Meta(BranchMiniSerializer.Meta):
        pass


class BranchPerformanceSerializer(serializers.Serializer):
    """Computed branch performance indicators (SRS 41)."""

    branch = serializers.IntegerField()
    branch_name = serializers.CharField()
    branch_code = serializers.CharField()
    total_members = serializers.IntegerField()
    active_members = serializers.IntegerField()
    new_members_this_month = serializers.IntegerField()
    events_conducted = serializers.IntegerField()
    attendance_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    report_compliance = serializers.DecimalField(max_digits=5, decimal_places=2)
    financial_reporting_compliance = serializers.DecimalField(max_digits=5, decimal_places=2)
    total_income = serializers.DecimalField(max_digits=16, decimal_places=2)
    jimbo_contribution = serializers.DecimalField(max_digits=16, decimal_places=2)
    pending_contribution = serializers.DecimalField(max_digits=16, decimal_places=2)
