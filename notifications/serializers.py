"""Notification and announcement serializers (SRS 35, 36, 69)."""

from rest_framework import serializers

from .models import Announcement, Notification, NotificationPreference, NotificationTemplate


class NotificationSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)

    class Meta:
        model = Notification
        fields = [
            'id', 'title', 'body', 'category', 'category_display', 'priority',
            'priority_display', 'branch', 'branch_name', 'related_entity', 'related_object_id',
            'action_url', 'payload', 'is_read', 'read_at', 'created_at',
        ]
        read_only_fields = fields


class NotificationTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationTemplate
        fields = [
            'id', 'code', 'name', 'channel', 'language', 'subject', 'body', 'description',
            'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            'id', 'in_system', 'email', 'sms', 'whatsapp', 'event_reminders',
            'finance_alerts', 'report_reminders', 'announcements',
        ]


class AnnouncementSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    ministry_name = serializers.CharField(source='ministry.name', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    audience_display = serializers.CharField(source='get_audience_display', read_only=True)
    is_live = serializers.BooleanField(read_only=True)
    # Legacy field names kept so the existing frontend keeps working (SRS 54).
    content = serializers.CharField(source='body', read_only=True)
    posted_by_name = serializers.CharField(
        source='posted_by.username', read_only=True, default=None,
    )

    class Meta:
        model = Announcement
        fields = [
            'id', 'title', 'summary', 'body', 'content', 'audience', 'audience_display',
            'branch', 'branch_name', 'ministry', 'ministry_name', 'status', 'status_display',
            'publish_at', 'expires_at', 'is_public', 'attachment', 'posted_by', 'posted_by_name',
            'views_count', 'is_live', 'is_active', 'created_at',
        ]
        read_only_fields = ['views_count', 'created_at']

