"""Testimony serializers (SRS 34)."""

from rest_framework import serializers

from core.files import validate_upload

from .models import Testimony


class TestimonySerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Testimony
        fields = [
            'id', 'reference', 'title', 'body', 'category', 'branch', 'branch_name',
            'allow_public', 'status', 'status_display', 'review_notes', 'is_featured',
            'photo', 'published_at', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['reference', 'status', 'review_notes', 'published_at', 'created_at', 'updated_at']

    def validate_title(self, value):
        if len((value or '').strip()) < 5:
            raise serializers.ValidationError('Title must have at least 5 characters.')
        return value.strip()

    def validate_body(self, value):
        if len((value or '').strip()) < 20:
            raise serializers.ValidationError('Testimony body must have at least 20 characters.')
        return value.strip()

    def validate_photo(self, value):
        return validate_upload(value, ['png', 'jpg', 'jpeg', 'webp'])


class TestimonyPublicSerializer(serializers.ModelSerializer):
    """Approved testimonies shown on the public website (SRS 34, 37)."""

    category_display = serializers.CharField(source='get_category_display', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)

    class Meta:
        model = Testimony
        fields = ['id', 'title', 'body', 'category', 'category_display', 'branch_name',
                  'photo', 'published_at', 'is_featured']



