"""Finance serializers (SRS 14, 15, 17, 54, 70)."""

from decimal import Decimal

from rest_framework import serializers

from core.files import EvidenceFileField

from .models import (
    FinancialAccount,
    FinancialTransaction,
    JimboContribution,
    ReconciliationRecord,
    Remittance,
    RemittanceAllocation,
    ReversalRequest,
    TransactionCategory,
)
from .services import compute_split, resolve_percentage


class TransactionCategorySerializer(serializers.ModelSerializer):
    """
    Categories carry the configurable "Subject to Jimbo 10%" flag (SRS 15).

    Only Jimbo administrators may create categories or change that flag; the
    permission is enforced by the viewset, never by the UI.
    """

    transaction_count = serializers.IntegerField(source='transactions.count', read_only=True)

    class Meta:
        model = TransactionCategory
        fields = [
            'id', 'name', 'name_sw', 'code', 'category_type', 'subject_to_jimbo_10',
            'description', 'is_active', 'transaction_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at', 'transaction_count']


class FinancialAccountSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    total_income = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    total_expenses = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    balance = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = FinancialAccount
        fields = [
            'id', 'name', 'code', 'account_type', 'branch', 'branch_name', 'currency',
            'opening_balance', 'is_active', 'total_income', 'total_expenses', 'balance',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class FinancialTransactionSerializer(serializers.ModelSerializer):
    """Read serializer: the fields listed in SRS 14 plus derived helpers."""

    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    branch_code = serializers.CharField(source='branch.code', read_only=True, default=None)
    cashier_name = serializers.CharField(source='cashier.username', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_name_sw = serializers.CharField(source='category.name_sw', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.username', read_only=True, default=None)
    received_by_name = serializers.CharField(source='received_by.username', read_only=True, default=None)
    contribution_status = serializers.SerializerMethodField()
    contribution_balance = serializers.SerializerMethodField()
    can_be_reversed = serializers.SerializerMethodField()

    class Meta:
        model = FinancialTransaction
        fields = [
            'id', 'transaction_id', 'branch', 'branch_name', 'branch_code', 'account',
            'cashier', 'cashier_name', 'category', 'category_name', 'category_name_sw',
            'transaction_type', 'transaction_type_display', 'description', 'amount',
            'subject_to_jimbo_10', 'jimbo_percentage', 'jimbo_amount', 'branch_amount',
            'transaction_date', 'payment_method', 'payment_method_display',
            'reference_number', 'receipt_number', 'attachment', 'status', 'status_display',
            'approved_by', 'approved_by_name', 'approved_at', 'received_by', 'received_by_name',
            'received_at', 'remarks', 'is_reversal', 'reversal_of', 'reversal_reason',
            'source_event', 'ministry', 'source', 'currency',
            'contribution_status', 'contribution_balance', 'can_be_reversed',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_contribution_status(self, obj):
        contribution = getattr(obj, 'jimbo_contribution', None)
        return contribution.status if contribution else None

    def get_contribution_balance(self, obj):
        contribution = getattr(obj, 'jimbo_contribution', None)
        return str(contribution.balance) if contribution else None

    def get_can_be_reversed(self, obj):
        return obj.can_be_reversed()

class FinancialTransactionWriteSerializer(serializers.ModelSerializer):
    """
    Write serializer for recording income and expenses (SRS 10, 14, 57).

    ``jimbo_amount``, ``branch_amount`` and ``jimbo_percentage`` are **not**
    accepted from the client: the backend calculates them (SRS 57, 83 Rule 5/6).
    """

    attachment = EvidenceFileField(required=False, allow_null=True)
    amount = serializers.DecimalField(max_digits=16, decimal_places=2)

    class Meta:
        model = FinancialTransaction
        fields = [
            'id', 'branch', 'category', 'transaction_type', 'description', 'amount',
            'transaction_date', 'payment_method', 'reference_number', 'receipt_number',
            'attachment', 'source_event', 'ministry', 'source', 'remarks',
        ]

    def validate_amount(self, value):
        """SRS 78: negative or zero amounts are rejected with a clear message."""
        if value is None or Decimal(value) <= 0:
            raise serializers.ValidationError(
                'Amount must be greater than zero. (Kiasi kiwe zaidi ya sifuri.)'
            )
        return value

    def validate(self, attrs):
        category = attrs.get('category')
        transaction_type = attrs.get('transaction_type') or (category.category_type if category else None)
        if category and transaction_type and category.category_type != transaction_type:
            raise serializers.ValidationError({
                'category': f'"{category.name}" is an {category.category_type.lower()} category.',
            })
        return attrs

    def preview_split(self):
        """Preview used by the branch cashier form (SRS 57 - display only)."""
        category = self.validated_data.get('category')
        amount = self.validated_data.get('amount') or Decimal('0.00')
        transaction_type = self.validated_data.get('transaction_type') or (
            category.category_type if category else 'INCOME'
        )
        branch = self.validated_data.get('branch')
        percentage = resolve_percentage(self.validated_data.get('transaction_date'))
        subject = bool(
            transaction_type == 'INCOME' and branch and category and category.subject_to_jimbo_10
        )
        return compute_split(amount, percentage, subject)


class JimboContributionSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    branch_code = serializers.CharField(source='branch.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    transaction_id = serializers.CharField(source='transaction.transaction_id', read_only=True)
    transaction_description = serializers.CharField(source='transaction.description', read_only=True)
    transaction_date = serializers.DateField(source='transaction.transaction_date', read_only=True)
    transaction_amount = serializers.DecimalField(
        source='transaction.amount', max_digits=16, decimal_places=2, read_only=True,
    )
    category_name = serializers.CharField(source='transaction.category.name', read_only=True)
    balance = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = JimboContribution
        fields = [
            'id', 'transaction', 'transaction_id', 'transaction_description', 'transaction_date',
            'transaction_amount', 'category_name', 'branch', 'branch_name', 'branch_code',
            'amount_due', 'amount_paid', 'percentage_applied', 'balance', 'due_date', 'status',
            'status_display', 'is_overdue', 'notified_at', 'received_by', 'received_at',
            'reconciled_by', 'reconciled_at', 'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


class RemittanceAllocationSerializer(serializers.ModelSerializer):
    contribution_transaction = serializers.CharField(
        source='contribution.transaction.transaction_id', read_only=True,
    )

    class Meta:
        model = RemittanceAllocation
        fields = ['id', 'remittance', 'contribution', 'contribution_transaction', 'amount', 'created_at']
        read_only_fields = ['created_at']

class RemittanceSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    branch_code = serializers.CharField(source='branch.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    submitted_by_name = serializers.CharField(source='submitted_by.username', read_only=True)
    received_by_name = serializers.CharField(source='received_by.username', read_only=True, default=None)
    allocations = RemittanceAllocationSerializer(many=True, read_only=True)
    allocated_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    unallocated_amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = Remittance
        fields = [
            'id', 'remittance_number', 'branch', 'branch_name', 'branch_code', 'amount',
            'payment_method', 'reference_number', 'receipt_number', 'evidence', 'payment_date',
            'status', 'status_display', 'submitted_by', 'submitted_by_name', 'verified_by',
            'verified_at', 'received_by', 'received_by_name', 'received_at', 'reconciled_by',
            'reconciled_at', 'notes', 'allocations', 'allocated_amount', 'unallocated_amount',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'remittance_number', 'status', 'submitted_by', 'verified_by', 'verified_at',
            'received_by', 'received_at', 'reconciled_by', 'reconciled_at', 'created_at', 'updated_at',
        ]

    def validate_amount(self, value):
        if value is None or Decimal(value) <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value


class ReconciliationRecordSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    branch_code = serializers.CharField(source='branch.code', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    difference = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    balance_due = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    verified_by_name = serializers.CharField(source='verified_by.username', read_only=True, default=None)

    class Meta:
        model = ReconciliationRecord
        fields = [
            'id', 'branch', 'branch_name', 'branch_code', 'period_year', 'period_month',
            'expected_amount', 'received_amount', 'difference', 'balance_due', 'status',
            'status_display', 'verified_by', 'verified_by_name', 'reconciled_at', 'notes',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'expected_amount', 'received_amount', 'status', 'verified_by', 'reconciled_at',
            'created_at', 'updated_at',
        ]

class ReversalRequestSerializer(serializers.ModelSerializer):
    transaction_id = serializers.CharField(source='transaction.transaction_id', read_only=True)
    transaction_amount = serializers.DecimalField(
        source='transaction.amount', max_digits=16, decimal_places=2, read_only=True,
    )
    branch_name = serializers.CharField(source='transaction.branch.name', read_only=True, default=None)
    requested_by_name = serializers.CharField(source='requested_by.username', read_only=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.username', read_only=True, default=None)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    reversal_transaction_id = serializers.CharField(
        source='reversal_transaction.transaction_id', read_only=True, default=None,
    )

    class Meta:
        model = ReversalRequest
        fields = [
            'id', 'transaction', 'transaction_id', 'transaction_amount', 'branch_name', 'reason',
            'status', 'status_display', 'requested_by', 'requested_by_name', 'reviewed_by',
            'reviewed_by_name', 'reviewed_at', 'review_notes', 'reversal_transaction',
            'reversal_transaction_id', 'created_at',
        ]
        read_only_fields = [
            'status', 'requested_by', 'reviewed_by', 'reviewed_at', 'review_notes',
            'reversal_transaction', 'created_at',
        ]


class BranchFinanceSummarySerializer(serializers.Serializer):
    """Branch finance dashboard (SRS 17)."""

    branch = serializers.IntegerField()
    branch_name = serializers.CharField()
    branch_code = serializers.CharField()
    currency = serializers.CharField()
    total_income = serializers.DecimalField(max_digits=16, decimal_places=2)
    total_expenses = serializers.DecimalField(max_digits=16, decimal_places=2)
    net_balance = serializers.DecimalField(max_digits=16, decimal_places=2)
    jimbo_contribution = serializers.DecimalField(max_digits=16, decimal_places=2)
    jimbo_paid = serializers.DecimalField(max_digits=16, decimal_places=2)
    pending_remittance = serializers.DecimalField(max_digits=16, decimal_places=2)
    branch_share = serializers.DecimalField(max_digits=16, decimal_places=2)
    transactions_count = serializers.IntegerField()


class JimboFinanceSummarySerializer(serializers.Serializer):
    """Consolidated Jimbo finance dashboard (SRS 17, 30)."""

    total_branch_income = serializers.DecimalField(max_digits=16, decimal_places=2)
    total_contributions = serializers.DecimalField(max_digits=16, decimal_places=2)
    expected_contributions = serializers.DecimalField(max_digits=16, decimal_places=2)
    received = serializers.DecimalField(max_digits=16, decimal_places=2)
    pending = serializers.DecimalField(max_digits=16, decimal_places=2)
    overdue = serializers.DecimalField(max_digits=16, decimal_places=2)
    branches_reporting = serializers.IntegerField()
    total_branches = serializers.IntegerField()
    collection_rate = serializers.DecimalField(max_digits=5, decimal_places=2)


class SplitPreviewSerializer(serializers.Serializer):
    """Preview of the automatic 10% calculation (SRS 57 - display only)."""

    gross = serializers.DecimalField(max_digits=16, decimal_places=2)
    percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    jimbo_amount = serializers.DecimalField(max_digits=16, decimal_places=2)
    branch_amount = serializers.DecimalField(max_digits=16, decimal_places=2)

