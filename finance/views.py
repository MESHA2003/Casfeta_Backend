"""
Finance API (SRS 10, 12, 13, 19, 54, 60, 61, 70).

Endpoints
    /api/finance/categories/          income / expense categories (SRS 16)
    /api/finance/accounts/            branch and Jimbo ledgers (SRS 84)
    /api/finance/transactions/        all transactions (filterable, SRS 70)
    /api/finance/income/              income only (SRS 54)
    /api/finance/expenses/            expenses only (SRS 54)
    /api/finance/jimbo-contributions/ the 10% obligations (SRS 53, 54)
    /api/finance/remittances/         branch remittances (SRS 54, 60, 61)
    /api/finance/reconciliations/     monthly reconciliation (SRS 61)
    /api/finance/reversals/           reversal workflow (SRS 19)
    /api/finance/split-preview/       automatic 10% preview (SRS 57)
    /api/finance/branch-dashboard/    branch finance dashboard (SRS 17)
    /api/finance/jimbo-dashboard/     Jimbo finance dashboard (SRS 17)
"""

from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import log_action
from core import access
from core.permissions import IsBranchCashierOrAbove, IsJimboAdmin, IsJimboFinance
from finance import services

from .models import (
    FinancialAccount,
    FinancialTransaction,
    JimboContribution,
    ReconciliationRecord,
    Remittance,
    ReversalRequest,
    TransactionCategory,
)
from .serializers import (
    BranchFinanceSummarySerializer,
    FinancialAccountSerializer,
    FinancialTransactionSerializer,
    FinancialTransactionWriteSerializer,
    JimboContributionSerializer,
    JimboFinanceSummarySerializer,
    ReconciliationRecordSerializer,
    RemittanceSerializer,
    ReversalRequestSerializer,
    SplitPreviewSerializer,
    TransactionCategorySerializer,
)


class TransactionCategoryFilter(filters.FilterSet):
    class Meta:
        model = TransactionCategory
        fields = ['category_type', 'subject_to_jimbo_10', 'is_active']


class TransactionCategoryViewSet(viewsets.ModelViewSet):
    """
    Category management (SRS 15, 16).

    Only Jimbo administrators (finance policy roles) may create categories or
    change which categories are subject to the 10%.
    """

    queryset = TransactionCategory.objects.all()
    serializer_class = TransactionCategorySerializer
    permission_classes = [IsJimboAdmin]
    filterset_class = TransactionCategoryFilter
    search_fields = ['name', 'name_sw', 'code']
    ordering_fields = ['name', 'category_type', 'created_at']

    def get_permissions(self):
        if self.action in {'list', 'retrieve'}:
            from rest_framework.permissions import IsAuthenticated

            return [IsAuthenticated()]
        return [IsJimboAdmin()]

    def perform_create(self, serializer):
        category = serializer.save(created_by=self.request.user)
        log_action(request=self.request, action='CREATE', instance=category,
                   description=f'Financial category "{category.name}" created.')

    def perform_update(self, serializer):
        old_value = {
            'subject_to_jimbo_10': serializer.instance.subject_to_jimbo_10,
            'is_active': serializer.instance.is_active,
        }
        category = serializer.save()
        if old_value['subject_to_jimbo_10'] != category.subject_to_jimbo_10:
            log_action(request=self.request, action='FINANCIAL_APPROVAL', instance=category,
                       old_value=old_value,
                       new_value={'subject_to_jimbo_10': category.subject_to_jimbo_10},
                       description=f'10% policy flag changed for "{category.name}".')
        else:
            log_action(request=self.request, action='UPDATE', instance=category, old_value=old_value,
                       description=f'Financial category "{category.name}" updated.')

    def perform_destroy(self, instance):
        raise MethodNotAllowed('DELETE', detail='Categories are deactivated, never deleted.')


class FinancialAccountViewSet(viewsets.ModelViewSet):
    """Branch and Jimbo ledgers (SRS 84)."""

    queryset = FinancialAccount.objects.select_related('branch').all()
    serializer_class = FinancialAccountSerializer
    permission_classes = [IsJimboFinance]
    filterset_fields = ['account_type', 'branch', 'is_active']
    search_fields = ['name', 'code']

    def get_queryset(self):
        queryset = super().get_queryset()
        return access.apply_branch_scope(queryset, self.request.user)


class FinancialTransactionFilter(filters.FilterSet):
    """Financial record filters required by SRS 70."""

    date_from = filters.DateFilter(field_name='transaction_date', lookup_expr='gte')
    date_to = filters.DateFilter(field_name='transaction_date', lookup_expr='lte')
    amount_min = filters.NumberFilter(field_name='amount', lookup_expr='gte')
    amount_max = filters.NumberFilter(field_name='amount', lookup_expr='lte')
    cashier_name = filters.CharFilter(field_name='cashier__username', lookup_expr='icontains')
    reference = filters.CharFilter(field_name='reference_number', lookup_expr='icontains')
    transaction_type = filters.CharFilter(field_name='transaction_type', lookup_expr='iexact')

    class Meta:
        model = FinancialTransaction
        fields = [
            'branch', 'cashier', 'category', 'status', 'transaction_type', 'payment_method',
            'is_reversal', 'date_from', 'date_to', 'amount_min', 'amount_max', 'reference',
        ]

class FinancialTransactionViewSet(viewsets.ModelViewSet):
    """
    Recording and reviewing financial transactions (SRS 10 - 19).

    Records are **never** deleted: corrections go through the reversal
    workflow (SRS 18, 19, 83 Rule 7/8) and the 10% is always calculated by the
    backend (SRS 57).
    """

    queryset = (
        FinancialTransaction.objects
        .select_related('branch', 'category', 'cashier', 'approved_by', 'received_by', 'account')
        .all()
    )
    filterset_class = FinancialTransactionFilter
    search_fields = ['transaction_id', 'description', 'reference_number', 'receipt_number']
    ordering_fields = ['transaction_date', 'amount', 'created_at', 'status']

    def get_serializer_class(self):
        if self.action in {'create', 'update', 'partial_update'}:
            return FinancialTransactionWriteSerializer
        return FinancialTransactionSerializer

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'approve', 'reject', 'reverse'}:
            return [IsBranchCashierOrAbove()]
        return super().get_permissions()

    def get_queryset(self):
        queryset = super().get_queryset()
        return access.apply_branch_scope(queryset, self.request.user)

    def create(self, request, *args, **kwargs):
        """
        Record income/expense.

        The gross amount comes from the cashier, but the 10% / 90% split is
        calculated here on the server (SRS 57) together with the Jimbo
        obligation and the notification (SRS 10, 11, 58).
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        branch = serializer.validated_data.get('branch')
        if branch is None and not access.is_jimbo_level(request.user):
            branch = access.primary_branch(request.user)
        if branch is not None and not access.can_access_branch(request.user, branch.id):
            raise PermissionDenied('You are not authorized to record financial data for another branch.')

        financial_transaction = services.record_transaction(
            cashier=request.user,
            category=serializer.validated_data['category'],
            amount=serializer.validated_data['amount'],
            description=serializer.validated_data['description'],
            transaction_type=serializer.validated_data.get('transaction_type'),
            branch=branch,
            transaction_date=serializer.validated_data.get('transaction_date'),
            payment_method=serializer.validated_data.get('payment_method', 'CASH'),
            reference_number=serializer.validated_data.get('reference_number', ''),
            receipt_number=serializer.validated_data.get('receipt_number', ''),
            attachment=serializer.validated_data.get('attachment'),
            source_event=serializer.validated_data.get('source_event'),
            ministry=serializer.validated_data.get('ministry'),
            source=serializer.validated_data.get('source', ''),
            request=request,
        )
        output = FinancialTransactionSerializer(financial_transaction, context={'request': request})
        return Response(output.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """
        Amounts can never be edited directly: corrections go through the
        reversal workflow so the audit trail stays intact (SRS 18, 19).
        """
        instance = self.get_object()
        allowed_fields = {'description', 'reference_number', 'receipt_number', 'attachment', 'remarks'}
        requested_fields = set(request.data.keys())
        if requested_fields - allowed_fields:
            raise ValidationError({
                'detail': [
                    'Financial amounts cannot be edited directly. Request a reversal instead '
                    '(SRS 18/19). Only description, reference, receipt, attachment and remarks may change.',
                ],
            })

        old_value = {field: getattr(instance, field) for field in allowed_fields}
        for field in allowed_fields:
            if field in request.data:
                setattr(instance, field, request.data[field])
        instance.save(update_fields=list(allowed_fields) + ['updated_at'])
        log_action(request=request, action='UPDATE', instance=instance, old_value=old_value,
                   description=f'Metadata of {instance.transaction_id} updated.')
        return Response(FinancialTransactionSerializer(instance, context={'request': request}).data)

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed(
            'DELETE',
            detail='Financial records can never be deleted. Request a reversal instead (SRS 18/19).',
        )

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        financial_transaction = self.get_object()
        services.approve_transaction(
            financial_transaction, request.user, request=request, remarks=request.data.get('remarks', ''),
        )
        return Response(FinancialTransactionSerializer(financial_transaction, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        financial_transaction = self.get_object()
        services.reject_transaction(
            financial_transaction, request.user, request.data.get('reason', ''), request=request,
        )
        return Response(FinancialTransactionSerializer(financial_transaction, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def reverse(self, request, pk=None):
        """Ask for a reversal of a posted transaction (SRS 19)."""
        financial_transaction = self.get_object()
        reversal = services.request_reversal(
            financial_transaction, request.user, request.data.get('reason', ''), request=request,
        )
        return Response(ReversalRequestSerializer(reversal).data, status=status.HTTP_201_CREATED)


class IncomeViewSet(FinancialTransactionViewSet):
    """``/api/finance/income/`` - income only (SRS 54)."""

    def get_queryset(self):
        return super().get_queryset().filter(transaction_type='INCOME')


class ExpenseViewSet(FinancialTransactionViewSet):
    """``/api/finance/expenses/`` - expenses only (SRS 54)."""

    def get_queryset(self):
        return super().get_queryset().filter(transaction_type='EXPENSE')

class JimboContributionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    The 10% obligations (SRS 11, 53, 60).

    Branch cashiers see their own branch; Jimbo finance sees everything. Only
    Jimbo users may confirm receipt (SRS 83 Rule 10), which is done through
    the remittance endpoints.
    """

    queryset = (
        JimboContribution.objects
        .select_related('branch', 'transaction', 'transaction__category')
        .all()
    )
    serializer_class = JimboContributionSerializer
    permission_classes = [IsJimboFinance]
    filterset_fields = ['branch', 'status', 'due_date']
    search_fields = ['branch__name', 'branch__code', 'transaction__transaction_id']
    ordering_fields = ['due_date', 'amount_due', 'created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = access.apply_branch_scope(queryset, self.request.user)
        overdue = self.request.query_params.get('overdue')
        if overdue in {'1', 'true', 'yes'}:
            queryset = queryset.filter(
                due_date__lt=timezone.localdate(), amount_paid__lt=F('amount_due'),
            ).exclude(status__in=['CANCELLED', 'RECONCILED'])
        return queryset

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Jimbo contribution dashboard for the cashier (SRS 17, 60)."""
        branch = request.query_params.get('branch')
        queryset = self.get_queryset()
        if branch:
            queryset = queryset.filter(branch_id=branch)
        outstanding = queryset.exclude(status__in=['CANCELLED', 'RECONCILED']).filter(
            amount_paid__lt=F('amount_due'),
        )
        return Response({
            'expected': queryset.exclude(status='CANCELLED').aggregate(
                total=Sum('amount_due'),
            )['total'] or Decimal('0.00'),
            'received': queryset.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00'),
            'outstanding': outstanding.aggregate(total=Sum('amount_due') - Sum('amount_paid'))['total']
            or Decimal('0.00'),
            'overdue_count': outstanding.filter(due_date__lt=timezone.localdate()).count(),
            'pending_count': outstanding.count(),
        })


class RemittanceViewSet(viewsets.ModelViewSet):
    """
    Branch remittances to the Jimbo (SRS 60, 61).

    * Branch cashier : submit a remittance (with evidence).
    * Jimbo cashier  : confirm receipt; only authorised Jimbo users may do it
                       (SRS 83 Rule 10).
    """

    queryset = Remittance.objects.select_related('branch', 'submitted_by', 'received_by').all()
    serializer_class = RemittanceSerializer
    filterset_fields = ['branch', 'status', 'payment_method', 'payment_date']
    search_fields = ['remittance_number', 'reference_number', 'receipt_number', 'branch__name']
    ordering_fields = ['payment_date', 'amount', 'created_at']

    def get_permissions(self):
        if self.action in {'create'}:
            return [IsBranchCashierOrAbove()]
        if self.action in {'confirm', 'verify', 'reconcile'}:
            return [IsJimboCashier()]
        return super().get_permissions()

    def get_queryset(self):
        return access.apply_branch_scope(super().get_queryset(), self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        branch = serializer.validated_data.get('branch') or access.primary_branch(request.user)
        if branch is None:
            raise ValidationError({'branch': ['A branch is required to submit a remittance.']})
        if not access.can_access_branch(request.user, branch.id):
            raise PermissionDenied('You are not authorized to submit a remittance for another branch.')

        remittance = services.submit_remittance(
            branch=branch,
            amount=serializer.validated_data['amount'],
            submitted_by=request.user,
            request=request,
            payment_method=serializer.validated_data.get('payment_method', 'BANK'),
            reference_number=serializer.validated_data.get('reference_number', ''),
            receipt_number=serializer.validated_data.get('receipt_number', ''),
            evidence=serializer.validated_data.get('evidence'),
            payment_date=serializer.validated_data.get('payment_date'),
            notes=serializer.validated_data.get('notes', ''),
        )
        return Response(
            RemittanceSerializer(remittance, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        remittance = self.get_object()
        remittance.status = 'VERIFIED'
        remittance.verified_by = request.user
        remittance.verified_at = timezone.now()
        remittance.save(update_fields=['status', 'verified_by', 'verified_at', 'updated_at'])
        log_action(request=request, action='FINANCIAL_APPROVAL', instance=remittance,
                   new_value={'status': 'VERIFIED'},
                   description=f'Remittance {remittance.remittance_number} verified.')
        return Response(RemittanceSerializer(remittance, context={'request': request}).data)

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Jimbo cashier confirms the funds were received (SRS 13, 83 Rule 10)."""
        remittance = self.get_object()
        services.confirm_remittance(
            remittance, request.user, request=request, notes=request.data.get('notes', ''),
        )
        return Response(RemittanceSerializer(remittance, context={'request': request}).data)

class ReconciliationViewSet(viewsets.ModelViewSet):
    """
    Monthly branch - Jimbo reconciliation (SRS 61).

    Expected 25,000 / Received 25,000 -> RECONCILED
    Expected 25,000 / Received 20,000 -> PARTIAL PAYMENT (balance 5,000)
    """

    queryset = ReconciliationRecord.objects.select_related('branch', 'verified_by').all()
    serializer_class = ReconciliationRecordSerializer
    permission_classes = [IsJimboFinance]
    filterset_fields = ['branch', 'status', 'period_year', 'period_month']
    ordering_fields = ['period_year', 'period_month', 'expected_amount']

    def get_queryset(self):
        return access.apply_branch_scope(super().get_queryset(), self.request.user)

    @action(detail=False, methods=['post'])
    def run(self, request):
        """Recalculate the reconciliation for a branch and month (SRS 61)."""
        from branches.models import Branch

        branch_id = request.data.get('branch')
        year = int(request.data.get('year') or timezone.localdate().year)
        month = int(request.data.get('month') or timezone.localdate().month)

        branch = Branch.objects.filter(pk=branch_id).first()
        if branch is None:
            raise ValidationError({'branch': ['A valid branch is required.']})
        if not access.can_access_branch(request.user, branch.id):
            raise PermissionDenied('You are not authorized to reconcile another branch.')

        record = services.reconcile_branch_period(
            branch, year, month, user=request.user, request=request, notes=request.data.get('notes', ''),
        )
        return Response(ReconciliationRecordSerializer(record).data, status=status.HTTP_200_OK)


class ReversalRequestViewSet(viewsets.ModelViewSet):
    """
    Reversal workflow (SRS 19).

    Original transaction -> reversal request -> authorization -> reversal
    transaction -> audit record. Nothing is ever deleted.
    """

    queryset = ReversalRequest.objects.select_related(
        'transaction', 'transaction__branch', 'requested_by', 'reviewed_by', 'reversal_transaction',
    ).all()
    serializer_class = ReversalRequestSerializer
    filterset_fields = ['status', 'transaction', 'requested_by']
    ordering_fields = ['created_at', 'status']

    def get_permissions(self):
        if self.action in {'approve', 'reject'}:
            return [IsJimboFinance()]
        return [IsBranchCashierOrAbove()]

    def get_queryset(self):
        queryset = super().get_queryset()
        scope = access.branch_scope(self.request.user)
        if scope is None:
            return queryset
        return queryset.filter(transaction__branch_id__in=list(scope) or [-1])

    def create(self, request, *args, **kwargs):
        transaction_id = request.data.get('transaction')
        financial_transaction = FinancialTransaction.objects.filter(pk=transaction_id).first()
        if financial_transaction is None:
            raise ValidationError({'transaction': ['Unknown transaction.']})
        if not access.can_access_branch(request.user, financial_transaction.branch_id):
            raise PermissionDenied('You are not authorized to request a reversal for this branch.')
        reversal = services.request_reversal(
            financial_transaction, request.user, request.data.get('reason', ''), request=request,
        )
        return Response(ReversalRequestSerializer(reversal).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        reversal = self.get_object()
        reversal_transaction = services.approve_reversal(
            reversal, request.user, request=request, notes=request.data.get('notes', ''),
        )
        return Response({
            'detail': 'Reversal approved. The original record was kept and a reversing record was created.',
            'reversal_request': ReversalRequestSerializer(reversal).data,
            'reversal_transaction': FinancialTransactionSerializer(reversal_transaction).data,
        })

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        reversal = self.get_object()
        services.reject_reversal(reversal, request.user, request.data.get('reason', ''), request=request)
        return Response(ReversalRequestSerializer(reversal).data)

class BranchFinanceDashboardView(APIView):
    """
    ``GET /api/finance/branch-dashboard/`` - branch finance dashboard (SRS 17).

    Total Income / Total Expenses / Net Balance / Jimbo Contribution /
    Pending Remittance.
    """

    permission_classes = [IsBranchCashierOrAbove]

    def get(self, request):
        from branches.models import Branch

        branch_id = request.query_params.get('branch')
        if branch_id:
            branch = Branch.objects.filter(pk=branch_id).first()
        else:
            branch = access.primary_branch(request.user)
        if branch is None:
            raise ValidationError({'branch': ['No branch available for this user.']})
        if not access.can_access_branch(request.user, branch.id):
            raise PermissionDenied('You are not authorized to access this financial record.')

        year = request.query_params.get('year')
        month = request.query_params.get('month')
        summary = services.branch_finance_summary(
            branch, int(year) if year else None, int(month) if month else None,
        )
        return Response(BranchFinanceSummarySerializer(summary).data)


class JimboFinanceDashboardView(APIView):
    """
    ``GET /api/finance/jimbo-dashboard/`` - consolidated Jimbo finance (SRS 17, 30).
    """

    permission_classes = [IsJimboFinance]

    def get(self, request):
        year = request.query_params.get('year')
        month = request.query_params.get('month')
        summary = services.jimbo_finance_summary(
            int(year) if year else None, int(month) if month else None,
        )
        summary['pending_remittances'] = JimboContributionSerializer(
            services.pending_remittances(user=request.user)[:50], many=True,
        ).data
        summary['recent_remittances'] = RemittanceSerializer(
            Remittance.objects.select_related('branch', 'submitted_by')[:10], many=True,
        ).data
        return Response(JimboFinanceSummarySerializer(summary).data | {
            'pending_remittances': summary['pending_remittances'],
            'recent_remittances': summary['recent_remittances'],
        })


class SplitPreviewAPIView(APIView):
    """
    ``POST /api/finance/split-preview/`` - preview of the automatic split.

    This is a *display* helper only: the values that are stored are always
    recalculated by ``services.record_transaction`` (SRS 57).
    """

    permission_classes = [IsBranchCashierOrAbove]

    def post(self, request):
        category = TransactionCategory.objects.filter(pk=request.data.get('category')).first()
        if category is None:
            raise ValidationError({'category': ['A valid category is required.']})

        amount = Decimal(str(request.data.get('amount') or 0))
        transaction_date = request.data.get('transaction_date')
        branch_id = request.data.get('branch')
        branch = None
        if branch_id:
            from branches.models import Branch

            branch = Branch.objects.filter(pk=branch_id).first()
        if branch is None:
            branch = access.primary_branch(request.user)
        if branch is not None and not access.can_access_branch(request.user, branch.id):
            raise PermissionDenied('You are not authorized to access this financial record.')

        percentage = services.resolve_percentage(transaction_date)
        subject = bool(category.subject_to_jimbo_10 and branch is not None)
        split = services.compute_split(amount, percentage, subject)
        return Response(
            SplitPreviewSerializer({
                'gross': split['gross'],
                'percentage': split['percentage'],
                'jimbo_amount': split['jimbo_amount'],
                'branch_amount': split['branch_amount'],
            }).data | {
                'subject_to_jimbo_10': subject,
                'category': category.name,
                'branch': branch.name if branch else None,
                'message': (
                    f'{split["percentage"]}% Jimbo contribution = {split["jimbo_amount"]}; '
                    f'branch keeps {split["branch_amount"]}.'
                    if subject else
                    'This transaction is not subject to the Jimbo 10% contribution.'
                ),
            }
        )

