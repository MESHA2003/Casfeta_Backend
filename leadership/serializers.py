"""Leadership serializers (SRS 23, 65, 66)."""

from rest_framework import serializers

from core.serializers import UserMiniSerializer

from .models import LeadershipPosition, LeadershipTerm


class LeadershipPositionSerializer(serializers.ModelSerializer):
    term_count = serializers.IntegerField(source='terms.count', read_only=True)

    class Meta:
        model = LeadershipPosition
        fields = [
            'id', 'title', 'title_sw', 'code', 'level', 'rank', 'description',
            'is_finance_position', 'is_public', 'is_hod', 'is_active', 'term_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'term_count']


class LeadershipTermSerializer(serializers.ModelSerializer):
    position_title = serializers.CharField(source='position.title', read_only=True)
    position_level = serializers.CharField(source='position.level', read_only=True)
    user_detail = UserMiniSerializer(source='user', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    ministry_name = serializers.CharField(source='ministry.name', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_current = serializers.BooleanField(read_only=True)

    class Meta:
        model = LeadershipTerm
        fields = [
            'id', 'position', 'position_title', 'position_level', 'user', 'user_detail',
            'branch', 'branch_name', 'ministry', 'ministry_name', 'term_name', 'term_start',
            'term_end', 'status', 'status_display', 'appointment_status', 'is_public',
            'appointed_by', 'notes', 'is_current', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'is_current']

    def validate(self, attrs):
        position = attrs.get('position') or getattr(self.instance, 'position', None)
        branch = attrs.get('branch') or getattr(self.instance, 'branch', None)
        ministry = attrs.get('ministry') or getattr(self.instance, 'ministry', None)
        if position and position.level == 'BRANCH' and not branch:
            raise serializers.ValidationError({'branch': 'A branch position requires a branch.'})
        if position and position.level == 'MINISTRY' and not ministry:
            raise serializers.ValidationError({'ministry': 'A ministry position requires a ministry.'})
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            validated_data.setdefault('appointed_by', request.user)
        return super().create(validated_data)


class PublicLeadershipSerializer(serializers.ModelSerializer):
    """Public leadership directory (SRS 66) - approved data only."""

    position = serializers.CharField(source='position.title', read_only=True)
    person = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)

    class Meta:
        model = LeadershipTerm
        fields = ['id', 'position', 'person', 'branch_name', 'term_name', 'term_start', 'term_end', 'status']

    def get_person(self, obj):
        return obj.user.get_full_name() or obj.user.username

