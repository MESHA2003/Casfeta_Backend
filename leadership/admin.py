"""Leadership positions and terms administration (SRS 24)."""

from django.contrib import admin

from core.admin import SoftDeleteAdmin

from .models import LeadershipPosition, LeadershipTerm


@admin.register(LeadershipPosition)
class LeadershipPositionAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'code', 'level', 'rank', 'is_hod', 'is_finance_position', 'is_public', 'is_active',
    )
    list_filter = ('level', 'is_hod', 'is_finance_position', 'is_public', 'is_active')
    search_fields = ('title', 'title_sw', 'code', 'description')


@admin.register(LeadershipTerm)
class LeadershipTermAdmin(SoftDeleteAdmin):
    list_display = (
        'user', 'position', 'branch', 'ministry', 'term_name', 'term_start', 'term_end', 'status',
    )
    list_filter = ('status', 'appointment_status', 'position', 'branch', 'is_active')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'term_name')
    autocomplete_fields = ('position', 'user', 'branch', 'ministry', 'appointed_by')
