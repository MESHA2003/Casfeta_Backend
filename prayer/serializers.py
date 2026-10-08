"""Prayer request serializers (SRS 33, 46 - privacy mandatory)."""

from rest_framework import serializers

from .models import PrayerFollowUp, PrayerRequest


class PrayerFollowUpSerializer(serializers.ModelSerializer):
    handled_by_name = serializers.CharField(source='handled_by.username', read_only=True, default=None)

    class Meta:
        model = PrayerFollowUp
        fields = [
            'id', 'prayer_request', 'handled_by', 'handled_by_name', 'note', 'is_private',
            'created_at',
        ]
        read_only_fields = ['handled_by', 'created_at']


class PrayerRequestSerializer(serializers.ModelSerializer):
    """Detail serializer - restricted according to SRS 33 and SRS 46."""

    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    assigned_to_name = serializers.CharField(source='assigned_to.username', read_only=True, default=None)
    follow_ups = PrayerFollowUpSerializer(many=True, read_only=True)

    class Meta:
        model = PrayerRequest
        fields = [
            'id', 'reference', 'category', 'subject', 'details', 'is_private', 'allow_public',
            'status', 'branch', 'branch_name', 'assigned_to', 'assigned_to_name',
            'follow_up_notes', 'answered_note', 'is_team_request', 'follow_ups',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['reference', 'created_at', 'updated_at']

    def to_representation(self, instance):
        """Hide private pastoral notes from the member who owns the request."""
        data = super().to_representation(instance)
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        from core import access

        privileged = bool(
            user is not None and access.is_authenticated_user(user) and (
                getattr(user, 'is_superuser', False)
                or access.has_role(user, 'JIMBO_ADMIN', 'BRANCH_LEADER', 'MINISTRY_LEADER')
                or (instance.assigned_to_id and instance.assigned_to_id == getattr(user, 'id', None))
            )
        )
        if not privileged:
            data.pop('follow_up_notes', None)
            # Follow-ups marked private stay hidden from the requester.
            data['follow_ups'] = [
                entry for entry in data.get('follow_ups', [])
                if not entry.get('is_private', True)
            ]
        return data


class PrayerRequestCreateSerializer(serializers.ModelSerializer):
    """Serializer used when a member submits a request (SRS 33)."""

    class Meta:
        model = PrayerRequest
        fields = ['category', 'subject', 'details', 'allow_public']

    def validate_subject(self, value):
        if not (value or '').strip():
            raise serializers.ValidationError('Taja kichwa cha ombi (subject is required).')
        return value.strip()

    def validate_details(self, value):
        if len((value or '').strip()) < 10:
            raise serializers.ValidationError('Eleza ombi lako kwa angalau herufi 10.')
        return value.strip()

