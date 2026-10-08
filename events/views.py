"""
Event management API (SRS 25, 26, 54 - /api/events/).

    /api/events/                     event register
    /api/events/public/              public website events (SRS 37)
    /api/events/<id>/register/       register (generates id + QR ticket)
    /api/event-registrations/        registration register
    /api/event-registrations/<id>/ticket/   QR ticket PNG
"""

from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import log_action, model_snapshot
from core import access
from core.permissions import IsBranchStaff, IsJimboAdmin
from core.qr import qr_png

from .models import Event, EventCategory, EventRegistration
from .serializers import (
    EventCategorySerializer,
    EventRegistrationSerializer,
    EventSerializer,
    PublicEventSerializer,
)


class EventFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name='start_date', lookup_expr='gte')
    date_to = filters.DateFilter(field_name='start_date', lookup_expr='lte')
    upcoming = filters.BooleanFilter(method='filter_upcoming')

    class Meta:
        model = Event
        fields = ['branch', 'ministry', 'category', 'status', 'level', 'is_public', 'start_date']

    def filter_upcoming(self, queryset, name, value):
        today = timezone.localdate()
        return queryset.filter(start_date__gte=today) if value else queryset.filter(start_date__lt=today)


class EventViewSet(viewsets.ModelViewSet):
    """Event register (SRS 25)."""

    queryset = Event.objects.select_related('branch', 'ministry', 'category', 'organizer').all()
    serializer_class = EventSerializer
    filterset_class = EventFilter
    search_fields = ['title', 'description', 'venue']
    ordering_fields = ['start_date', 'title', 'created_at']

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy'}:
            return [IsBranchStaff()]
        if self.action in {'public', 'upcoming'}:
            return [AllowAny()]
        return super().get_permissions()

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action in {'public', 'upcoming'}:
            # Public endpoints only expose published, public events (SRS 37, 83 Rule 12).
            return queryset.filter(is_active=True, status__in=['PUBLISHED', 'ONGOING'], is_public=True)
        return access.apply_branch_scope(queryset, self.request.user)

    def perform_create(self, serializer):
        event = serializer.save(organizer=self.request.user)
        log_action(request=self.request, action='CREATE', instance=event,
                   description=f'Event "{event.title}" created.')

    def perform_update(self, serializer):
        old_value = model_snapshot(serializer.instance, exclude=('updated_at',))
        event = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=event, old_value=old_value,
                   description=f'Event "{event.title}" updated.')

    def perform_destroy(self, instance):
        instance.deactivate(self.request.user, self.request.data.get('reason', ''))
        log_action(self.request, action='DEACTIVATE', instance=instance,
                   description=f'Event "{instance.title}" cancelled/removed.')

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def register(self, request, pk=None):
        """
        Register the logged-in member for this event (SRS 26).

        Returns the registration id, the confirmation and the QR ticket
        payload used for attendance (SRS 27, 72).
        """
        event = self.get_object()
        member = getattr(request.user, 'member_profile', None)
        if member is None:
            raise ValidationError({'detail': ['Only approved CASFETA members can register for events.']})
        if event.branch_id and not access.can_access_branch(request.user, event.branch_id):
            raise PermissionDenied('You are not authorized to register for this event.')
        if event.is_full:
            raise ValidationError({'detail': ['This event has reached its capacity.']})

        serializer = EventRegistrationSerializer(
            data={'event': event.pk, 'member': member.pk, 'branch': member.branch_id},
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        registration = serializer.save(event=event, member=member, branch=member.branch)

        log_action(request=request, action='CREATE', instance=registration,
                   description=f'{member.full_name} registered for "{event.title}".')
        payload = serializer.data
        payload['confirmation'] = (
            f'You are registered for "{event.title}" on {event.start_date:%d %B %Y}. '
            f'Registration ID: {registration.registration_id}. Show the QR ticket at the entrance.'
        )
        payload['qr_payload'] = f'/verify/registration/{registration.qr_token}/'
        return Response(payload, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], permission_classes=[IsBranchStaff])
    def publish(self, request, pk=None):
        event = self.get_object()
        event.status = request.data.get('status', 'PUBLISHED')
        event.save(update_fields=['status', 'updated_at'])
        log_action(request=request, action='PUBLISH', instance=event,
                   description=f'Event "{event.title}" set to {event.status}.')
        return Response(EventSerializer(event, context={'request': request}).data)

    @action(detail=True, methods=['get'])
    def registrations(self, request, pk=None):
        event = self.get_object()
        queryset = event.registrations.select_related('member', 'branch').all()
        status_param = request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)
        return Response({
            'event': event.title,
            'count': queryset.count(),
            'registrations': EventRegistrationSerializer(queryset, many=True, context={'request': request}).data,
        })

class EventCategoryViewSet(viewsets.ModelViewSet):
    """Configurable event categories (SRS 86)."""

    queryset = EventCategory.objects.all()
    serializer_class = EventCategorySerializer
    filterset_fields = ['is_active']
    search_fields = ['name', 'name_sw']

    def get_permissions(self):
        if self.action in {'list', 'retrieve'}:
            from rest_framework.permissions import IsAuthenticated

            return [IsAuthenticated()]
        return [IsJimboAdmin()]


class EventRegistrationViewSet(viewsets.ModelViewSet):
    """Event registrations with QR tickets (SRS 26, 54)."""

    queryset = EventRegistration.objects.select_related('event', 'member', 'branch').all()
    serializer_class = EventRegistrationSerializer
    filterset_fields = ['event', 'branch', 'status', 'payment_status']
    search_fields = ['registration_id', 'member__first_name', 'member__last_name', 'guest_name']
    ordering_fields = ['created_at', 'status']

    def get_permissions(self):
        if self.action in {'cancel', 'mark_paid'}:
            return [IsBranchStaff()]
        return super().get_permissions()

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'mine':
            return queryset.filter(member__user=self.request.user)
        return access.apply_branch_scope(queryset, self.request.user)

    @action(detail=False, methods=['get'])
    def mine(self, request):
        """Registrations of the logged-in member (SRS 6.2 - my events)."""
        queryset = self.filter_queryset(self.get_queryset())
        return Response(EventRegistrationSerializer(queryset, many=True, context={'request': request}).data)

    @action(detail=True, methods=['get'])
    def ticket(self, request, pk=None):
        """QR ticket PNG (SRS 26, 72)."""
        from django.http import HttpResponse

        registration = self.get_object()
        response = HttpResponse(
            qr_png(f'/verify/registration/{registration.qr_token}'), content_type='image/png',
        )
        response['Content-Disposition'] = f'inline; filename="ticket-{registration.registration_id}.png"'
        return response

    @action(detail=True, methods=['post'], permission_classes=[IsBranchStaff])
    def cancel(self, request, pk=None):
        registration = self.get_object()
        registration.status = 'CANCELLED'
        registration.cancellation_reason = request.data.get('reason', '')
        registration.save(update_fields=['status', 'cancellation_reason', 'updated_at'])
        log_action(request=request, action='UPDATE', instance=registration,
                   reason=registration.cancellation_reason,
                   description=f'Registration {registration.registration_id} cancelled.')
        return Response(EventRegistrationSerializer(registration, context={'request': request}).data)

    @action(detail=True, methods=['post'], permission_classes=[IsBranchStaff], url_path='mark-paid')
    def mark_paid(self, request, pk=None):
        """Mark an event fee as paid; the fee income is recorded in finance."""
        registration = self.get_object()
        registration.payment_status = 'PAID'
        registration.payment_reference = request.data.get('reference', registration.payment_reference)
        registration.save(update_fields=['payment_status', 'payment_reference', 'updated_at'])
        log_action(request=request, action='PAYMENT', instance=registration,
                   description=f'Event fee marked as paid for {registration.registration_id}.')
        return Response(EventRegistrationSerializer(registration, context={'request': request}).data)


class PublicEventListView(APIView):
    """Public website events (SRS 37)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        queryset = Event.objects.filter(
            is_active=True, status__in=['PUBLISHED', 'ONGOING'], is_public=True,
        ).select_related('branch', 'category')
        if request.query_params.get('upcoming') in {'1', 'true', 'yes'}:
            queryset = queryset.filter(start_date__gte=timezone.localdate())
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(title__icontains=search)
        limit = request.query_params.get('limit')
        if limit and limit.isdigit():
            queryset = queryset[:int(limit)]
        return Response({
            'count': len(queryset) if isinstance(queryset, list) else queryset.count(),
            'results': PublicEventSerializer(queryset, many=True).data,
        })

