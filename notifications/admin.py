"""Notification, announcement and preference administration (SRS 31, 46)."""

from django.contrib import admin

from core.admin import SoftDeleteAdmin

from .models import Announcement, Notification, NotificationPreference, NotificationTemplate


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'channel', 'language', 'is_active')
    list_filter = ('channel', 'language', 'is_active')
    search_fields = ('code', 'name', 'subject', 'description')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """
    Notifications are written by the platform (SRS 31) - read only.

    Old notifications may be purged (delete stays allowed), but they can never
    be created or edited by hand.
    """

    list_display = ('created_at', 'recipient', 'title', 'category', 'priority', 'is_read')
    list_filter = ('category', 'priority', 'is_read', 'channel')
    search_fields = ('title', 'body', 'recipient__username', 'recipient__email')
    date_hierarchy = 'created_at'
    readonly_fields = [field.name for field in Notification._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Announcement)
class AnnouncementAdmin(SoftDeleteAdmin):
    list_display = (
        'title', 'audience', 'branch', 'status', 'is_public', 'publish_at', 'views_count',
    )
    list_filter = ('status', 'audience', 'branch', 'is_public', 'is_active')
    search_fields = ('title', 'summary', 'body', 'posted_by_name')
    readonly_fields = ('views_count', 'created_at', 'updated_at')
    autocomplete_fields = ('branch', 'ministry', 'posted_by')


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'in_system', 'email', 'sms', 'whatsapp', 'announcements')
    list_filter = ('in_system', 'email', 'sms', 'whatsapp')
    search_fields = ('user__username', 'user__email')
    autocomplete_fields = ('user',)
