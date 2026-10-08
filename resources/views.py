"""
Digital library, academic hub, documents and news API (SRS 31, 32, 43, 67).

    /api/resources/            digital library (access controlled, SRS 43)
    /api/resources/public/     public items for the website (SRS 37)
    /api/resources/<id>/download/  download with access check + counter
    /api/news/                 news management (SRS 67 - CMS)
    /api/news/public/          published news for the website
"""

import os

from django.db.models import F
from django.http import FileResponse
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import log_action
from core.permissions import IsJimboAdmin

from .models import NewsArticle, Resource, ResourceCategory
from .serializers import (
    NewsArticlePublicSerializer,
    NewsArticleSerializer,
    ResourceAccessCheck,
    ResourceCategorySerializer,
    ResourcePublicSerializer,
    ResourceSerializer,
)


class ResourceCategoryViewSet(viewsets.ModelViewSet):
    """Categories of the digital library (SRS 32, 86)."""

    queryset = ResourceCategory.objects.all()
    serializer_class = ResourceCategorySerializer
    filterset_fields = ['group', 'is_active']

    def get_permissions(self):
        if self.action in {'list', 'retrieve'}:
            return [IsAuthenticated()]
        return [IsJimboAdmin()]

    @action(detail=False, methods=['post'], permission_classes=[IsJimboAdmin])
    def seed_defaults(self, request):
        """Create the standard library / academic categories (SRS 32, 86)."""
        created = ResourceCategory.seed_defaults()
        log_action(request=request, action='CREATE', entity='ResourceCategory',
                   description=f'{created} default resource categories seeded.')
        return Response(
            {'detail': f'{created} categories created.', 'created': created},
            status=status.HTTP_201_CREATED,
        )


class ResourceViewSet(viewsets.ModelViewSet):
    """Digital library with access levels (SRS 32, 43)."""

    queryset = Resource.objects.select_related('category', 'author').all()
    serializer_class = ResourceSerializer
    filterset_fields = ['resource_type', 'category', 'access_level', 'status', 'is_featured']
    search_fields = ['title', 'description', 'tags', 'organisation']
    ordering_fields = ['created_at', 'title', 'deadline']

    def get_permissions(self):
        if self.action in {'public', 'download'}:
            # The download action re-checks SRS 43 access levels per record.
            return [AllowAny()]
        if self.action in {'create', 'update', 'partial_update', 'destroy'}:
            return [IsJimboAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'public':
            return queryset.filter(status='PUBLISHED', access_level='PUBLIC', is_active=True)
        if self.action in {'list', 'retrieve'}:
            allowed_ids = [
                resource.pk for resource in queryset
                if ResourceAccessCheck.can_access(self.request.user, resource)
            ]
            return queryset.filter(pk__in=allowed_ids or [-1])
        return queryset

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def public(self, request):
        """Public items for the website (SRS 37)."""
        queryset = self.get_queryset().order_by('-created_at')
        return Response({
            'count': queryset.count(),
            'results': ResourcePublicSerializer(queryset[:100], many=True).data,
        })


    def perform_create(self, serializer):
        resource = serializer.save(author=self.request.user)
        log_action(request=self.request, action='CREATE', instance=resource,
                   description=f'Resource "{resource.title}" published to the library.')

    def perform_update(self, serializer):
        resource = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=resource,
                   description=f'Resource "{resource.title}" updated.')

    def perform_destroy(self, instance):
        """Library items are deactivated, never deleted (SRS 18, 68)."""
        instance.deactivate(self.request.user, self.request.data.get('reason', ''))
        log_action(request=self.request, action='DEACTIVATE', instance=instance,
                   description=f'Resource "{instance.title}" deactivated.')

    @action(detail=True, methods=['get'], permission_classes=[AllowAny])
    def download(self, request, pk=None):
        """
        ``GET /api/resources/<id>/download/`` - access controlled download (SRS 43).

        Access is re-checked on the server for every request; the counter is
        increased atomically so reports stay accurate.
        """
        resource = self.get_object()
        if not ResourceAccessCheck.can_access(request.user, resource):
            raise PermissionDenied('You are not authorized to download this resource.')

        Resource.objects.filter(pk=resource.pk).update(download_count=F('download_count') + 1)
        log_action(request=request, action='EXPORT', instance=resource,
                   description=f'Resource "{resource.title}" downloaded.')

        if resource.file:
            return FileResponse(
                resource.file.open('rb'),
                as_attachment=True,
                filename=os.path.basename(resource.file.name),
            )
        if resource.external_url:
            return redirect(resource.external_url)
        raise ValidationError({'file': ['This resource has no file or link to download.']})


class NewsArticleViewSet(viewsets.ModelViewSet):
    """News / publications CMS for the public website (SRS 67)."""

    queryset = NewsArticle.objects.all()
    serializer_class = NewsArticleSerializer
    filterset_fields = ['status', 'is_featured', 'is_active']
    search_fields = ['title', 'excerpt', 'body', 'author_name']
    ordering_fields = ['published_at', 'created_at', 'title']

    def get_permissions(self):
        if self.action == 'public':
            return [AllowAny()]
        if self.action in {'create', 'update', 'partial_update', 'destroy', 'publish'}:
            return [IsJimboAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'public':
            return queryset.filter(
                is_active=True, status='PUBLISHED', published_at__lte=timezone.now(),
            )
        return queryset

    def retrieve(self, request, *args, **kwargs):
        article = self.get_object()
        if article.is_live:
            NewsArticle.objects.filter(pk=article.pk).update(views_count=F('views_count') + 1)
        return Response(self.get_serializer(article).data)

    def perform_create(self, serializer):
        author_name = serializer.validated_data.get('author_name') or request_display_name(self.request)
        article = serializer.save(author_name=author_name)
        log_action(request=self.request, action='CREATE', instance=article,
                   description=f'News article "{article.title}" created.')

    def perform_update(self, serializer):
        article = serializer.save()
        log_action(request=self.request, action='UPDATE', instance=article,
                   description=f'News article "{article.title}" updated.')

    def perform_destroy(self, instance):
        instance.deactivate(self.request.user, self.request.data.get('reason', ''))
        log_action(request=self.request, action='DEACTIVATE', instance=instance,
                   description=f'News article "{instance.title}" deactivated.')

    @action(detail=False, methods=['get'], permission_classes=[AllowAny])
    def public(self, request):
        """Published articles for the public website (SRS 37, 67)."""
        queryset = self.filter_queryset(self.get_queryset()).order_by('-published_at', '-id')
        limit = request.query_params.get('limit')
        if limit and limit.isdigit():
            queryset = list(queryset[:int(limit)])
        return Response({
            'count': len(queryset) if isinstance(queryset, list) else queryset.count(),
            'results': NewsArticlePublicSerializer(queryset, many=True).data,
        })

    @action(detail=True, methods=['post'], permission_classes=[IsJimboAdmin])
    def publish(self, request, pk=None):
        """Publish an article immediately (SRS 67)."""
        article = self.get_object()
        article.status = 'PUBLISHED'
        article.published_at = article.published_at or timezone.now()
        article.save(update_fields=['status', 'published_at', 'updated_at'])
        log_action(request=request, action='PUBLISH', instance=article,
                   new_value={'status': 'PUBLISHED'},
                   description=f'News article "{article.title}" published.')
        return Response(self.get_serializer(article).data)


def request_display_name(request):
    """Display name stored on articles created from the API."""
    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        return 'CASFETA Zanzibar'
    return user.get_full_name() or user.username

