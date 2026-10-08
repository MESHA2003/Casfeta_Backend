"""Event and registration serializers (SRS 25, 26)."""

from rest_framework import serializers

from core.files import validate_upload

from .models import Event, EventCategory, EventRegistration


class EventCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = EventCategory
        fields = ['id', 'name', 'name_sw', 'description', 'is_active']


class EventSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    ministry_name = serializers.CharField(source='ministry.name', read_only=True, default=None)
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    organizer_name = serializers.CharField(source='organizer.username', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    registration_count = serializers.IntegerField(read_only=True)
    is_upcoming = serializers.BooleanField(read_only=True)
    is_full = serializers.BooleanField(read_only=True)
    my_registration = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            'id', 'title', 'slug', 'category', 'category_name', 'level', 'branch', 'branch_name',
            'ministry', 'ministry_name', 'description', 'objectives', 'start_date', 'end_date',
            'start_time', 'end_time', 'venue', 'is_online', 'online_link', 'organizer',
            'organizer_name', 'capacity', 'requires_registration', 'fee', 'currency', 'poster',
            'status', 'status_display', 'is_public', 'is_active', 'registration_count',
            'is_upcoming', 'is_full', 'my_registration', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'registration_count', 'is_upcoming', 'is_full']

    def get_my_registration(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        member = getattr(request.user, 'member_profile', None)
        if member is None:
            return None
        registration = obj.registrations.filter(member=member).first()
        if registration is None:
            return None
        return {
            'id': registration.id,
            'registration_id': registration.registration_id,
            'status': registration.status,
            'payment_status': registration.payment_status,
            'qr_token': registration.qr_token,
        }

    def validate_poster(self, value):
        return validate_upload(value, ['png', 'jpg', 'jpeg', 'webp'])

    def validate(self, attrs):
        level = attrs.get('level') or getattr(self.instance, 'level', 'BRANCH')
        branch = attrs.get('branch') or getattr(self.instance, 'branch', None)
        if level == 'BRANCH' and not branch:
            raise serializers.ValidationError({'branch': 'A branch event must be linked to a branch.'})
        start_date = attrs.get('start_date') or getattr(self.instance, 'start_date', None)
        end_date = attrs.get('end_date') or getattr(self.instance, 'end_date', None)
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({'end_date': 'The end date must be on or after the start date.'})
        return attrs

class EventRegistrationSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source='event.title', read_only=True)
    event_date = serializers.DateField(source='event.start_date', read_only=True)
    member_name = serializers.SerializerMethodField()
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = EventRegistration
        fields = [
            'id', 'registration_id', 'event', 'event_title', 'event_date', 'member', 'member_name',
            'guest_name', 'guest_phone', 'guest_email', 'branch', 'branch_name', 'status',
            'status_display', 'payment_status', 'fee_amount', 'payment_reference', 'qr_token',
            'attended_at', 'cancellation_reason', 'notes', 'created_at',
        ]
        read_only_fields = ['registration_id', 'qr_token', 'attended_at', 'created_at']

    def get_member_name(self, obj):
        return obj.registrant_name

    def validate(self, attrs):
        event = attrs.get('event') or getattr(self.instance, 'event', None)
        member = attrs.get('member') or getattr(self.instance, 'member', None)

        if event and not self.instance and event.is_full:
            raise serializers.ValidationError({'event': 'This event has reached its capacity.'})
        if event and member:
            existing = EventRegistration.objects.filter(event=event, member=member)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError({'member': 'You are already registered for this event.'})
        return attrs

    def create(self, validated_data):
        request = self.context.get('request')
        if request and getattr(request, 'user', None) and request.user.is_authenticated:
            member = getattr(request.user, 'member_profile', None)
            if member is not None and not validated_data.get('member'):
                validated_data['member'] = member
                validated_data.setdefault('branch', member.branch)
        return super().create(validated_data)


class PublicEventSerializer(serializers.ModelSerializer):
    """Public website event listing (SRS 37) - no internal data."""

    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Event
        fields = [
            'id', 'title', 'slug', 'category_name', 'branch_name', 'description', 'start_date',
            'end_date', 'start_time', 'end_time', 'venue', 'is_online', 'capacity', 'fee',
            'currency', 'poster', 'requires_registration', 'status_display',
        ]

