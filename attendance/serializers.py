"""Attendance serializers (SRS 27)."""

from rest_framework import serializers

from .models import AttendanceRecord, AttendanceSession


class AttendanceSessionSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source='event.title', read_only=True, default=None)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    opened_by_name = serializers.CharField(source='opened_by.username', read_only=True, default=None)
    present_count = serializers.IntegerField(read_only=True)
    total_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AttendanceSession
        fields = [
            'id', 'event', 'event_title', 'branch', 'branch_name', 'title', 'session_date',
            'start_time', 'end_time', 'is_open', 'opened_by', 'opened_by_name', 'closed_at',
            'notes', 'present_count', 'total_count', 'created_at',
        ]
        read_only_fields = ['opened_by', 'closed_at', 'created_at']

    def create(self, validated_data):
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            validated_data.setdefault('opened_by', request.user)
        return super().create(validated_data)


class AttendanceRecordSerializer(serializers.ModelSerializer):
    member_name = serializers.SerializerMethodField()
    member_id = serializers.CharField(source='member.member_id', read_only=True, default=None)
    event_title = serializers.CharField(source='event.title', read_only=True, default=None)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    recorded_by_name = serializers.CharField(source='recorded_by.username', read_only=True, default=None)

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'session', 'event', 'event_title', 'registration', 'member', 'member_name',
            'member_id', 'branch', 'branch_name', 'attendance_date', 'check_in_time',
            'check_out_time', 'status', 'status_display', 'method', 'recorded_by',
            'recorded_by_name', 'remarks', 'guest_name', 'created_at',
        ]
        read_only_fields = ['check_in_time', 'check_out_time', 'created_at']

    def get_member_name(self, obj):
        return obj.person_name

    def validate(self, attrs):
        if not attrs.get('session') and not attrs.get('event'):
            raise serializers.ValidationError(
                {'session': 'Attendance must be recorded against a session or an event.'}
            )
        return attrs

