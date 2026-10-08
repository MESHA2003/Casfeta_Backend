"""
Django admin configuration for the core platform models (SRS 37, 52, 85, 86).

Administrators manage the Jimbo profile, the configurable catalogues and the
financial policy here. ``SoftDeleteAdmin`` implements the platform rule that
records are deactivated instead of deleted (SRS 18, 68).
"""

from django.contrib import admin, messages

from .models import (
    AcademicYear,
    ContactMessage,
    District,
    FinancialPolicy,
    Institution,
    Organization,
    SystemSetting,
)


class SoftDeleteAdmin(admin.ModelAdmin):
    """
    Base admin for records that are deactivated, never deleted (SRS 18, 68).

    Hard deletion is disabled so history and the audit trail stay intact;
    administrators use the deactivate / reactivate actions instead.
    """

    actions = ('deactivate_selected', 'reactivate_selected')

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        for name in ('deactivated_at', 'deactivated_by'):
            if name not in readonly:
                readonly.append(name)
        return readonly

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Deactivate selected records (history is kept)')
    def deactivate_selected(self, request, queryset):
        count = 0
        for instance in queryset.filter(is_active=True):
            instance.deactivate(request.user, 'Deactivated from the Django admin.')
            count += 1
        self.message_user(request, f'{count} record(s) deactivated.', messages.SUCCESS)

    @admin.action(description='Reactivate selected records')
    def reactivate_selected(self, request, queryset):
        count = 0
        for instance in queryset.filter(is_active=False):
            instance.reactivate(request.user)
            count += 1
        self.message_user(request, f'{count} record(s) reactivated.', messages.SUCCESS)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ['name', 'short_name', 'region_scope', 'contact_email', 'currency', 'is_active']
    list_filter = ['is_active', 'default_language']
    search_fields = ['name', 'short_name', 'contact_email', 'contact_phone', 'address']


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ['key', 'group', 'value_type', 'value_preview', 'is_public']
    list_filter = ['group', 'value_type', 'is_public']
    search_fields = ['key', 'label', 'description']

    @admin.display(description='Value')
    def value_preview(self, obj):
        return (obj.value or '')[:60]


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'region', 'parent', 'is_active']
    list_filter = ['region', 'is_active']
    search_fields = ['name', 'code', 'region']


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'institution_type', 'district', 'is_active']
    list_filter = ['institution_type', 'district', 'is_active']
    search_fields = ['name', 'code', 'location']


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ['name', 'start_date', 'end_date', 'is_current', 'is_membership_year', 'is_active']
    list_filter = ['is_current', 'is_membership_year', 'is_active']
    search_fields = ['name']


@admin.register(FinancialPolicy)
class FinancialPolicyAdmin(admin.ModelAdmin):
    """The contribution percentage is data, never code (SRS 85)."""

    list_display = ['name', 'contribution_percentage', 'effective_date', 'status', 'approved_by']
    list_filter = ['status', 'effective_date']
    search_fields = ['name', 'description']
    date_hierarchy = 'effective_date'


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'subject', 'status', 'handled_by', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['full_name', 'email', 'phone', 'subject', 'message']
    readonly_fields = ['created_at', 'updated_at']
