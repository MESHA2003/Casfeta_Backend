from django.contrib import admin

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


@admin.register(TransactionCategory)
class TransactionCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'category_type', 'subject_to_jimbo_10', 'is_active')
    list_filter = ('category_type', 'subject_to_jimbo_10', 'is_active')
    search_fields = ('name', 'name_sw', 'code')


@admin.register(FinancialAccount)
class FinancialAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'account_type', 'branch', 'currency', 'is_active')
    list_filter = ('account_type', 'is_active')


@admin.register(FinancialTransaction)
class FinancialTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'transaction_id', 'branch', 'transaction_type', 'category', 'amount',
        'jimbo_amount', 'branch_amount', 'status', 'transaction_date', 'cashier',
    )
    list_filter = ('transaction_type', 'status', 'branch', 'category', 'is_reversal')
    search_fields = ('transaction_id', 'description', 'reference_number', 'receipt_number')
    date_hierarchy = 'transaction_date'
    readonly_fields = ('transaction_id', 'jimbo_amount', 'branch_amount', 'jimbo_percentage', 'subject_to_jimbo_10')

    def has_delete_permission(self, request, obj=None):
        # Financial records must never be deleted (SRS 18, 83 Rule 7).
        return False


@admin.register(JimboContribution)
class JimboContributionAdmin(admin.ModelAdmin):
    list_display = ('branch', 'transaction', 'amount_due', 'amount_paid', 'status', 'due_date')
    list_filter = ('status', 'branch')
    search_fields = ('branch__name', 'transaction__transaction_id')
    date_hierarchy = 'due_date'


class RemittanceAllocationInline(admin.TabularInline):
    model = RemittanceAllocation
    extra = 0


@admin.register(Remittance)
class RemittanceAdmin(admin.ModelAdmin):
    list_display = ('remittance_number', 'branch', 'amount', 'status', 'payment_date', 'submitted_by')
    list_filter = ('status', 'branch', 'payment_method')
    search_fields = ('remittance_number', 'reference_number', 'receipt_number')
    inlines = [RemittanceAllocationInline]


@admin.register(ReconciliationRecord)
class ReconciliationRecordAdmin(admin.ModelAdmin):
    list_display = ('branch', 'period_year', 'period_month', 'expected_amount', 'received_amount', 'status')
    list_filter = ('status', 'period_year', 'branch')


@admin.register(ReversalRequest)
class ReversalRequestAdmin(admin.ModelAdmin):
    list_display = ('transaction', 'status', 'requested_by', 'reviewed_by', 'created_at')
    list_filter = ('status',)
    search_fields = ('transaction__transaction_id', 'reason')

