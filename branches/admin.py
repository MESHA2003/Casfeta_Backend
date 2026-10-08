"""Branch (Tawi) administration (SRS 22, 41)."""

from django.contrib import admin

from core.admin import SoftDeleteAdmin

from .models import Branch, BranchStatistics


@admin.register(Branch)
class BranchAdmin(SoftDeleteAdmin):
    list_display = ['name', 'code', 'status', 'district', 'institution', 'member_count', 'is_active']
    list_filter = ['status', 'district', 'is_active', 'meeting_day']
    search_fields = ['name', 'code', 'location', 'description']
    readonly_fields = ['code', 'slug', 'created_at', 'updated_at']
    autocomplete_fields = ['organization', 'district', 'institution', 'created_by']

    def member_count(self, obj):
        return obj.member_count


@admin.register(BranchStatistics)
class BranchStatisticsAdmin(admin.ModelAdmin):
    list_display = [
        'branch', 'period_year', 'period_month', 'total_members', 'new_members',
        'attendance_rate', 'report_submitted',
    ]
    list_filter = ['period_year', 'period_month', 'report_submitted', 'branch']
    search_fields = ['branch__name', 'branch__code']
    autocomplete_fields = ['branch']
