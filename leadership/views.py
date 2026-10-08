"""
Leadership API (SRS 23, 54, 65, 66).

    /api/leaders/positions/   position catalogue
    /api/leaders/terms/       appointments with the succession workflow
    /api/leaders/public/      public leadership directory (SRS 66)
"""

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import log_action
from core import access
from core.permissions import IsJimboAdmin

from .models import LeadershipPosition, LeadershipTerm
from .serializers import LeadershipPositionSerializer, LeadershipTermSerializer, PublicLeadershipSerializer


class LeadershipPositionViewSet(viewsets.ModelViewSet):
    """Position catalogue (SRS 23)."""

    queryset = LeadershipPosition.objects.all()
    serializer_class = LeadershipPositionSerializer
    filterset_fields = ['level', 'is_active', 'is_public', 'is_finance_position']
    search_fields = ['title', 'title_sw', 'code']
    ordering_fields = ['rank', 'title']

    def get_permissions(self):
        if self.action in {'list', 'retrieve'}:
            from rest_framework.permissions import IsAuthenticated

            return [IsAuthenticated()]
        return [IsJimboAdmin()]

    def perform_create(self, serializer):
        serializer.save()
        log_action(request=self.request, action='CREATE', instance=serializer.instance,
                   description='Leadership position created.')

    def perform_destroy(self, instance):
        if instance.terms.exists():
            raise ValidationError(
                {'detail': 'Positions that are already used cannot be deleted; deactivate them instead.'}
            )
        instance.delete()


class LeadershipTermViewSet(viewsets.ModelViewSet):
    """
    Appointments (SRS 23) including the succession flow (SRS 65):
    ACTIVE -> TERM COMPLETED -> FORMER LEADER, history always preserved.
    """

    queryset = LeadershipTerm.objects.select_related('position', 'user', 'branch', 'ministry').all()
    serializer_class = LeadershipTermSerializer
    filterset_fields = ['position', 'branch', 'ministry', 'status', 'user', 'is_public']
    search_fields = ['user__username', 'user__first_name', 'user__last_name', 'position__title']
    ordering_fields = ['term_start', 'status', 'position__rank']

    def get_permissions(self):
        if self.action in {'list', 'retrieve', 'public'}:
            from rest_framework.permissions import IsAuthenticated

            return [IsAuthenticated()]
        return [IsJimboAdmin()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action not in {'create', 'update', 'partial_update', 'destroy'}:
            return access.apply_branch_scope(queryset, self.request.user)
        return queryset

    def perform_create(self, serializer):
        term = serializer.save()
        log_action(request=self.request, action='CREATE', instance=term,
                   description=f'Leadership appointment: {term}.')

    @action(detail=True, methods=['post'])
    def complete_term(self, request, pk=None):
        """ACTIVE -> TERM COMPLETED (SRS 65)."""
        term = self.get_object()
        term.complete_term(request.user, notes=request.data.get('notes', ''))
        log_action(request=request, action='UPDATE', instance=term,
                   new_value={'status': 'TERM_COMPLETED'},
                   description=f'Term completed for {term.position.title} ({term.user.username}).')
        return Response(LeadershipTermSerializer(term).data)

    @action(detail=True, methods=['post'], url_path='mark-former')
    def mark_former(self, request, pk=None):
        term = self.get_object()
        term.mark_former()
        log_action(request=request, action='UPDATE', instance=term,
                   new_value={'status': 'FORMER'},
                   description=f'Marked as former leader: {term.position.title} ({term.user.username}).')
        return Response(LeadershipTermSerializer(term).data)


class PublicLeadershipDirectoryView(APIView):
    """
    ``GET /api/leaders/public/`` - public leadership directory (SRS 37, 66).

    Only public, active terms are returned: no contact details and no
    private administrative information.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        today = timezone.localdate()
        queryset = (
            LeadershipTerm.objects
            .filter(status='ACTIVE', is_public=True, is_active=True, term_start__lte=today)
            .select_related('position', 'user', 'branch')
            .filter(position__is_public=True)
        )
        branch = request.query_params.get('branch')
        if branch:
            queryset = queryset.filter(branch_id=branch)
        payload = PublicLeadershipSerializer(queryset.order_by('position__rank'), many=True).data
        return Response({'count': len(payload), 'results': payload})

