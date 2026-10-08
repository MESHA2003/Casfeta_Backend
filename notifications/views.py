"""
Notification centre, announcement and template API (SRS 35, 36, 44, 69).

    /api/notifications/            my notifications (unread first)
    /api/notifications/unread/     unread count for the bell icon
    /api/announcements/            public/branch announcements
    /api/notification-templates/   reusable message templates (SRS 44)
"""

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import log_action
from core import access
from core.permissions import IsBranchLeaderOrAbove, IsJimboAdmin

from .models import Announcement, Notification, NotificationPreference, NotificationTemplate
from .serializers import (
    AnnouncementSerializer,
    NotificationPreferenceSerializer,
    NotificationSerializer,
    NotificationTemplateSerializer,
)
from .services import notify_announcement, notify_user


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """The user's own notification centre (SRS 69)."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['category', 'is_read', 'priority']
    ordering_fields = ['created_at', 'priority']

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).select_related('branch')

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_read()
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=['post'], url_path='mark-all-read')
    def mark_all_read(self, request):
        updated = Notification.objects.filter(recipient=request.user, is_read=False).update(
            is_read=True, read_at=timezone.now(),
        )
        return Response({'detail': f'{updated} notifications marked as read.'})

    @action(detail=False, methods=['get'])
    def unread(self, request):
        """Unread count + latest messages for the bell icon (SRS 69)."""
        queryset = Notification.objects.filter(recipient=request.user)
        unread_count = queryset.filter(is_read=False).count()
        return Response({
            'unread_count': unread_count,
            'by_category': {
                row['category']: row['total']
                for row in queryset.filter(is_read=False).values('category').annotate(total=Count('id'))
            },
            'latest': NotificationSerializer(queryset.order_by('-created_at')[:8], many=True).data,
        })

class AnnouncementViewSet(viewsets.ModelViewSet):
    """Announcements with audience targeting (SRS 35, 67)."""

    queryset = Announcement.objects.select_related('branch', 'ministry', 'posted_by').all()
    serializer_class = AnnouncementSerializer
    filterset_fields = ['status', 'audience', 'branch', 'ministry', 'is_public']
    search_fields = ['title', 'summary', 'body']
    ordering_fields = ['publish_at', 'created_at']

    def get_permissions(self):
        if self.action == 'public':
            # Public website endpoint: no authentication required (SRS 37).
            return [AllowAny()]
        if self.action in {'list', 'retrieve'}:
            return [IsAuthenticated()]
        return [IsBranchLeaderOrAbove()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'public':
            now = timezone.now()
            return (
                queryset
                .filter(is_public=True, status='PUBLISHED', is_active=True)
                .filter(Q(publish_at__isnull=True) | Q(publish_at__lte=now))
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))
                .order_by('-publish_at')
            )
        return access.apply_branch_scope(queryset, self.request.user)

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def public(self, request):
        """Live announcements for the public website (SRS 37)."""
        queryset = self.filter_queryset(self.get_queryset())
        return Response({
            'count': queryset.count(),
            'results': AnnouncementSerializer(queryset[:50], many=True).data,
        })

    def perform_create(self, serializer):
        announcement = serializer.save(
            posted_by=self.request.user,
            posted_by_name=self.request.user.get_full_name() or self.request.user.username,
        )
        if announcement.branch_id and not access.can_access_branch(self.request.user, announcement.branch_id):
            raise PermissionDenied('You are not authorized to publish announcements for this branch.')
        log_action(request=self.request, action='CREATE', instance=announcement,
                   description=f'Announcement "{announcement.title}" created.')

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish and fan out to the selected audience (SRS 35, 69)."""
        announcement = self.get_object()
        if announcement.branch_id and not access.can_access_branch(request.user, announcement.branch_id):
            raise PermissionDenied('You are not authorized to publish announcements for this branch.')

        announcement.publish(request.user)
        recipients = notify_announcement(announcement)
        log_action(request=request, action='PUBLISH', instance=announcement,
                   new_value={'status': 'PUBLISHED', 'recipients': recipients},
                   description=f'Announcement "{announcement.title}" published to {recipients} users.')
        return Response({
            'detail': f'Announcement published to {recipients} users.',
            'announcement': AnnouncementSerializer(announcement, context={'request': request}).data,
        })

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        announcement = self.get_object()
        announcement.status = 'ARCHIVED'
        announcement.save(update_fields=['status', 'updated_at'])
        return Response(AnnouncementSerializer(announcement, context={'request': request}).data)

class NotificationTemplateViewSet(viewsets.ModelViewSet):
    """Message templates (SRS 44)."""

    queryset = NotificationTemplate.objects.all()
    serializer_class = NotificationTemplateSerializer
    permission_classes = [IsJimboAdmin]
    filterset_fields = ['channel', 'language', 'is_active']
    search_fields = ['code', 'name', 'subject', 'body']


class NotificationPreferenceView(APIView):
    """``GET/PUT /api/notifications/preferences/`` - channel preferences (SRS 44)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        preference, _ = NotificationPreference.objects.get_or_create(user=request.user)
        return Response(NotificationPreferenceSerializer(preference).data)

    def put(self, request):
        preference, _ = NotificationPreference.objects.get_or_create(user=request.user)
        serializer = NotificationPreferenceSerializer(preference, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class TestNotificationView(APIView):
    """``POST /api/notifications/test/`` - send yourself a test notification."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        notification = notify_user(
            request.user,
            title=request.data.get('title', 'CZDMP - Jaribio ya Arifa'),
            body=request.data.get('body', 'Hii ni arifa ya majaribio.'),
            category='SYSTEM',
        )
        if notification is None:
            raise ValidationError({'detail': ['In-system notifications are disabled for your account.']})
        return Response(NotificationSerializer(notification).data, status=status.HTTP_201_CREATED)

