"""Ministry administration (SRS 26)."""

from django.contrib import admin

from core.admin import SoftDeleteAdmin

from .models import Ministry, MinistryMembership


@admin.register(Ministry)
class MinistryAdmin(SoftDeleteAdmin):
    list_display = ('name', 'code', 'level', 'branch', 'leader', 'is_active')
    list_filter = ('level', 'branch', 'is_active')
    search_fields = ('name', 'code', 'description', 'objectives')
    autocomplete_fields = ('branch', 'leader', 'created_by')


@admin.register(MinistryMembership)
class MinistryMembershipAdmin(admin.ModelAdmin):
    list_display = ('ministry', 'member', 'role_in_ministry', 'joined_date', 'is_active')
    list_filter = ('role_in_ministry', 'is_active', 'ministry')
    search_fields = ('ministry__name', 'member__first_name', 'member__last_name', 'notes')
    autocomplete_fields = ('ministry', 'member')
