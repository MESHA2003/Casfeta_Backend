"""
Finance business logic (SRS 9, 10, 11, 57, 58, 61, 83).

Everything in this module runs on the Django backend. The frontend may show
a preview of the split, but the values that are stored are always the ones
calculated here (SRS 57).
"""

import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from audit.services import log_action
from core.models import FinancialPolicy

from .models import (
    FinancialAccount,
    FinancialTransaction,
    JimboContribution,
    ReconciliationRecord,
    Remittance,
    RemittanceAllocation,
    ReversalRequest,
)

logger = logging.getLogger('czdmp.finance')

MONEY = Decimal('0.01')


def money(value):
    """Normalise a monetary value to two decimals."""
    return Decimal(str(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def resolve_percentage(on_date=None):
    """
    Percentage that applies to a transaction recorded on ``on_date``.

    Historical transactions keep the percentage of their own date because the
    policy is resolved from the FinancialPolicy table (SRS 85).
    """
    return FinancialPolicy.current_percentage(on_date)


def compute_split(gross, percentage, subject_to_jimbo_10):
    """
    Apply the CASFETA 10% / 90% rule (SRS 9, 57).

        Income = 100,000 -> Jimbo = 10,000, Branch = 90,000

    ``branch_amount`` is derived by subtraction so that the two allocations
    always add up to the gross amount, without rounding leftovers.
    """
    gross = money(gross)
    if gross <= 0:
        raise ValidationError({'amount': ['Amount must be greater than zero. (Kiasi kiwe zaidi ya sifuri.)']})

    if not subject_to_jimbo_10:
        return {
            'gross': gross,
            'percentage': Decimal('0.00'),
            'jimbo_amount': Decimal('0.00'),
            'branch_amount': gross,
        }

    percentage = Decimal(str(percentage or 0))
    jimbo_amount = money(gross * percentage / Decimal('100'))
    branch_amount = money(gross - jimbo_amount)
    return {
        'gross': gross,
        'percentage': percentage,
        'jimbo_amount': jimbo_amount,
        'branch_amount': branch_amount,
    }


def branch_ledger(branch):
    """Virtual ledger of a branch (SRS 84)."""
    account, _ = FinancialAccount.objects.get_or_create(
        account_type='BRANCH',
        name=f'{branch.name} Ledger',
        defaults={'branch': branch, 'code': f'LED-{branch.code}'},
    )
    if account.branch_id != branch.id:
        account.branch = branch
        account.save(update_fields=['branch', 'updated_at'])
    return account


def jimbo_ledger():
    """Consolidated Jimbo ledger (SRS 84)."""
    account, _ = FinancialAccount.objects.get_or_create(
        account_type='JIMBO',
        name='CASFETA Jimbo la Zanzibar Consolidated Ledger',
        defaults={'code': 'LED-JIMBO-ZANZIBAR'},
    )
    return account

@transaction.atomic
def record_transaction(*, cashier, category, amount, description, transaction_type=None,
                       branch=None, transaction_date=None, payment_method='CASH',
                       reference_number='', receipt_number='', attachment=None,
                       source_event=None, ministry=None, source='', request=None,
                       account=None):
    """
    Record a branch (or Jimbo) income/expense (SRS 10, 14, 57, 58).

    The whole operation is atomic: transaction + 10% calculation + Jimbo
    obligation + notification + audit are written together, so a failure
    never leaves an inconsistent financial record (SRS 58).
    """
    transaction_type = transaction_type or category.category_type or 'INCOME'
    transaction_date = transaction_date or timezone.localdate()

    if category.category_type != transaction_type:
        raise ValidationError({
            'category': [f'Category "{category.name}" is an {category.category_type.lower()} category.'],
        })

    if branch is None and transaction_type == 'INCOME':
        # A Jimbo level income does not create a contribution to itself.
        subject_to_jimbo = False
        percentage = Decimal('0.00')
    elif transaction_type == 'EXPENSE':
        subject_to_jimbo = False
        percentage = Decimal('0.00')
    else:
        subject_to_jimbo = bool(category.subject_to_jimbo_10)
        percentage = resolve_percentage(transaction_date)

    split = compute_split(amount, percentage, subject_to_jimbo)

    if account is None:
        account = branch_ledger(branch) if branch is not None else jimbo_ledger()

    financial_transaction = FinancialTransaction(
        branch=branch,
        account=account,
        cashier=cashier,
        category=category,
        transaction_type=transaction_type,
        description=description,
        amount=split['gross'],
        subject_to_jimbo_10=subject_to_jimbo,
        jimbo_percentage=split['percentage'] if subject_to_jimbo else Decimal('0.00'),
        jimbo_amount=split['jimbo_amount'],
        branch_amount=split['branch_amount'],
        transaction_date=transaction_date,
        payment_method=payment_method,
        reference_number=reference_number,
        receipt_number=receipt_number,
        attachment=attachment,
        status='RECORDED',
        source_event=source_event,
        ministry=ministry,
        source=source,
    )
    financial_transaction.full_clean(exclude=['transaction_id', 'created_at', 'updated_at', 'is_active'])
    financial_transaction.save()

    contribution = None
    if split['jimbo_amount'] > 0:
        contribution = JimboContribution.objects.create(
            transaction=financial_transaction,
            branch=branch,
            amount_due=split['jimbo_amount'],
            percentage_applied=split['percentage'],
            status='PENDING_REMITTANCE',
        )
        financial_transaction.status = 'PENDING_REMITTANCE'
        financial_transaction.save(update_fields=['status', 'updated_at'])

        notify_jimbo_contribution(contribution, request=request)

    log_action(
        request=request,
        action='PAYMENT',
        instance=financial_transaction,
        branch=branch,
        old_value=None,
        new_value={
            'transaction_id': financial_transaction.transaction_id,
            'amount': str(split['gross']),
            'jimbo_amount': str(split['jimbo_amount']),
            'branch_amount': str(split['branch_amount']),
            'status': financial_transaction.status,
        },
        description=(
            f'{transaction_type.title()} of {split["gross"]} recorded by {cashier.username}'
            + (f' ({split["percentage"]}% Jimbo = {split["jimbo_amount"]}).' if subject_to_jimbo else '.')
        ),
    )
    return financial_transaction


def notify_jimbo_contribution(contribution, request=None):
    """
    Notify the Jimbo cashier(s) about a new contribution (SRS 11).

    Notification failures never roll back the financial record, they are only
    logged, because the obligation itself is already stored.
    """
    try:
        from notifications.services import notify_new_contribution

        notify_new_contribution(contribution)
        contribution.notified_at = timezone.now()
        contribution.save(update_fields=['notified_at', 'updated_at'])
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning('Could not notify Jimbo cashier for %s: %s', contribution.pk, exc)

def approve_transaction(financial_transaction, user, request=None, remarks=''):
    """Branch finance/leader review step (SRS 13)."""
    if financial_transaction.status in {'REVERSED', 'REJECTED'}:
        raise ValidationError({'detail': ['This transaction can no longer be approved.']})
    old_status = financial_transaction.status
    financial_transaction.status = 'APPROVED'
    financial_transaction.approved_by = user
    financial_transaction.approved_at = timezone.now()
    if remarks:
        financial_transaction.remarks = remarks
    financial_transaction.save(update_fields=['status', 'approved_by', 'approved_at', 'remarks', 'updated_at'])

    log_action(request=request, action='FINANCIAL_APPROVAL', instance=financial_transaction,
               old_value={'status': old_status}, new_value={'status': 'APPROVED'},
               description=f'Transaction {financial_transaction.transaction_id} approved by {user.username}.')
    return financial_transaction


def reject_transaction(financial_transaction, user, reason, request=None):
    """Reject a transaction without deleting it (SRS 12, 18)."""
    if not reason:
        raise ValidationError({'reason': ['A reason is required when rejecting a transaction.']})
    old_status = financial_transaction.status
    financial_transaction.status = 'REJECTED'
    financial_transaction.remarks = f'{financial_transaction.remarks}\n{reason}'.strip()
    financial_transaction.save(update_fields=['status', 'remarks', 'updated_at'])

    contribution = getattr(financial_transaction, 'jimbo_contribution', None)
    if contribution is not None and not contribution.is_settled:
        contribution.status = 'CANCELLED'
        contribution.notes = f'{contribution.notes}\nCancelled: transaction rejected.'.strip()
        contribution.save(update_fields=['status', 'notes', 'updated_at'])

    log_action(request=request, action='REJECT', instance=financial_transaction,
               old_value={'status': old_status}, new_value={'status': 'REJECTED'},
               reason=reason, description=f'Transaction {financial_transaction.transaction_id} rejected.')
    return financial_transaction


def mark_contributions_remitted(contribution, user=None):
    if contribution.status not in {'CANCELLED', 'RECONCILED'}:
        contribution.status = 'REMITTED'
        contribution.save(update_fields=['status', 'updated_at'])
    return contribution


@transaction.atomic
def submit_remittance(*, branch, amount, submitted_by, request=None, payment_method='BANK',
                      reference_number='', receipt_number='', evidence=None, payment_date=None, notes=''):
    """
    A branch reports that it has sent its 10% contribution to the Jimbo
    (SRS 60). The Jimbo cashier still has to confirm receipt (SRS 13).
    """
    amount = money(amount)
    if amount <= 0:
        raise ValidationError({'amount': ['Amount must be greater than zero.']})

    remittance = Remittance.objects.create(
        branch=branch,
        amount=amount,
        payment_method=payment_method,
        reference_number=reference_number,
        receipt_number=receipt_number,
        evidence=evidence,
        payment_date=payment_date or timezone.localdate(),
        status='SUBMITTED',
        submitted_by=submitted_by,
        notes=notes or '',
    )

    # Automatically allocate to the oldest outstanding obligations so the
    # contribution records move from PENDING to PARTIAL/RECEIVED (SRS 61).
    remaining = amount
    outstanding = (
        JimboContribution.objects
        .filter(branch=branch)
        .exclude(status__in=['CANCELLED', 'RECONCILED'])
        .order_by('due_date', 'id')
    )
    for contribution in outstanding:
        if remaining <= 0:
            break
        balance = contribution.balance
        if balance <= 0:
            continue
        applied = min(balance, remaining)
        RemittanceAllocation.objects.create(
            remittance=remittance, contribution=contribution, amount=applied, created_by=submitted_by,
        )
        contribution.amount_paid = money(contribution.amount_paid + applied)
        contribution.refresh_status()
        if contribution.is_settled:
            mark_contributions_remitted(contribution, submitted_by)
        remaining = money(remaining - applied)

    remittance.status = 'RECEIVED' if remaining <= 0 else 'PARTIAL'
    remittance.save(update_fields=['status', 'updated_at'])

    log_action(request=request, action='PAYMENT', instance=remittance, branch=branch,
               new_value={'remittance': remittance.remittance_number, 'amount': str(amount),
                          'unallocated': str(remaining)},
               description=f'Remittance {remittance.remittance_number} submitted for {branch.code}.')

    try:
        from notifications.services import notify_remittance_submitted

        notify_remittance_submitted(remittance)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning('Could not notify about remittance %s: %s', remittance.pk, exc)

    return remittance

@transaction.atomic
def confirm_remittance(remittance, user, request=None, notes=''):
    """
    Jimbo cashier confirms that the money was received (SRS 13, 61).

    Only authorized Jimbo users may confirm receipt (SRS 83 Rule 10); the
    linked transactions move to REMITTED/RECEIVED and the contributions to
    RECEIVED so the reconciliation can be closed.
    """
    old_status = remittance.status
    remittance.status = 'RECEIVED'
    remittance.received_by = user
    remittance.received_at = timezone.now()
    if notes:
        remittance.notes = f'{remittance.notes}\n{notes}'.strip()
    remittance.save(update_fields=['status', 'received_by', 'received_at', 'notes', 'updated_at'])

    for allocation in remittance.allocations.select_related('contribution__transaction'):
        contribution = allocation.contribution
        contribution.received_by = user
        contribution.received_at = timezone.now()
        contribution.status = 'RECEIVED' if contribution.is_settled else 'PARTIAL'
        contribution.save(update_fields=['status', 'received_by', 'received_at', 'updated_at'])

        financial_transaction = contribution.transaction
        financial_transaction.status = 'RECEIVED' if contribution.is_settled else 'REMITTED'
        financial_transaction.received_by = user
        financial_transaction.received_at = timezone.now()
        financial_transaction.save(update_fields=['status', 'received_by', 'received_at', 'updated_at'])

        log_action(request=request, action='RECONCILE', instance=contribution,
                   old_value={'status': 'REMITTED'}, new_value={'status': contribution.status},
                   description=f'Contribution for {contribution.transaction.transaction_id} confirmed received.')

    log_action(request=request, action='PAYMENT', instance=remittance,
               old_value={'status': old_status}, new_value={'status': 'RECEIVED'},
               description=f'Remittance {remittance.remittance_number} confirmed received by {user.username}.')

    try:
        from notifications.services import notify_remittance_confirmed

        notify_remittance_confirmed(remittance)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning('Could not notify branch about remittance %s: %s', remittance.pk, exc)

    return remittance


@transaction.atomic
def reconcile_branch_period(branch, year, month, user=None, request=None, notes=''):
    """
    Create/refresh the monthly reconciliation for a branch (SRS 61).

    Expected 25,000 / Received 25,000 -> RECONCILED
    Expected 25,000 / Received 20,000 -> PARTIAL PAYMENT (balance 5,000)
    """
    record, _ = ReconciliationRecord.objects.get_or_create(
        branch=branch, period_year=year, period_month=month,
    )
    record.refresh(verified_by=user, notes=notes)
    log_action(request=request, action='RECONCILE', instance=record,
               new_value={'expected': str(record.expected_amount), 'received': str(record.received_amount),
                          'status': record.status},
               description=f'Reconciliation {year}-{month:02d} for {branch.code} updated.')
    return record

@transaction.atomic
def request_reversal(financial_transaction, user, reason, request=None):
    """Step 1-2 of the reversal workflow (SRS 19): original -> request."""
    if not reason:
        raise ValidationError({'reason': ['A reason is required when requesting a reversal.']})
    if not financial_transaction.can_be_reversed():
        raise ValidationError({'detail': ['This transaction cannot be reversed.']})

    reversal = ReversalRequest.objects.create(
        transaction=financial_transaction, reason=reason, requested_by=user, status='REQUESTED',
    )
    log_action(request=request, action='REVERSAL', instance=financial_transaction,
               reason=reason, description=f'Reversal requested for {financial_transaction.transaction_id}.')
    return reversal


@transaction.atomic
def approve_reversal(reversal_request, user, request=None, notes=''):
    """
    Step 3-5: authorization creates the reversal transaction and keeps the
    original record for history (SRS 19, 83 Rule 8).
    """
    if reversal_request.status == 'APPROVED':
        raise ValidationError({'detail': ['This reversal request was already approved.']})

    original = reversal_request.transaction
    opposite_type = 'EXPENSE' if original.transaction_type == 'INCOME' else 'INCOME'

    reversal_transaction = FinancialTransaction(
        branch=original.branch,
        account=original.account,
        cashier=user,
        category=original.category,
        transaction_type=opposite_type,
        description=f'Reversal of {original.transaction_id}: {original.description}',
        amount=original.amount,
        subject_to_jimbo_10=False,
        jimbo_percentage=Decimal('0.00'),
        jimbo_amount=Decimal('0.00'),
        branch_amount=original.amount,
        transaction_date=timezone.localdate(),
        payment_method=original.payment_method,
        reference_number=original.reference_number,
        status='RECORDED',
        is_reversal=True,
        reversal_of=original,
        reversal_reason=reversal_request.reason,
        source='reversal',
    )
    reversal_transaction.save()

    original.status = 'REVERSED'
    original.save(update_fields=['status', 'updated_at'])

    contribution = getattr(original, 'jimbo_contribution', None)
    if contribution is not None and not contribution.is_settled:
        contribution.status = 'CANCELLED'
        contribution.notes = (
            f'{contribution.notes}\nCancelled by reversal {reversal_transaction.transaction_id}.'
        ).strip()
        contribution.save(update_fields=['status', 'notes', 'updated_at'])

    reversal_request.status = 'APPROVED'
    reversal_request.reviewed_by = user
    reversal_request.reviewed_at = timezone.now()
    reversal_request.review_notes = notes
    reversal_request.reversal_transaction = reversal_transaction
    reversal_request.save(update_fields=[
        'status', 'reviewed_by', 'reviewed_at', 'review_notes', 'reversal_transaction', 'updated_at',
    ])

    log_action(request=request, action='REVERSAL', instance=original,
               old_value={'status': 'RECORDED'}, new_value={'status': 'REVERSED'},
               reason=reversal_request.reason,
               description=(
                   f'Transaction {original.transaction_id} reversed by '
                   f'{reversal_transaction.transaction_id} (approved by {user.username}).'
               ))
    return reversal_transaction


@transaction.atomic
def reject_reversal(reversal_request, user, reason, request=None):
    reversal_request.status = 'REJECTED'
    reversal_request.reviewed_by = user
    reversal_request.reviewed_at = timezone.now()
    reversal_request.review_notes = reason
    reversal_request.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'])

    log_action(request=request, action='REJECT', instance=reversal_request.transaction,
               reason=reason, description='Reversal request rejected.')
    return reversal_request

# ---------------------------------------------------------------------------
# Dashboards and summaries (SRS 17, 60)
# ---------------------------------------------------------------------------

def _period_filter(queryset, year=None, month=None, field='transaction_date'):
    if year:
        queryset = queryset.filter(**{f'{field}__year': year})
    if month:
        queryset = queryset.filter(**{f'{field}__month': month})
    return queryset


def branch_finance_summary(branch, year=None, month=None):
    """
    Branch finance dashboard figures (SRS 17).

    Total Income / Total Expenses / Net Balance / Jimbo Contribution /
    Pending Remittance.
    """
    transactions = FinancialTransaction.objects.filter(
        branch=branch, status__in=FinancialTransaction.POSTED_STATUSES,
    )
    transactions = _period_filter(transactions, year, month)

    total_income = transactions.filter(transaction_type='INCOME').aggregate(
        total=Sum('amount'),
    )['total'] or Decimal('0.00')
    total_expenses = transactions.filter(transaction_type='EXPENSE').aggregate(
        total=Sum('amount'),
    )['total'] or Decimal('0.00')
    jimbo_contribution = transactions.filter(transaction_type='INCOME').aggregate(
        total=Sum('jimbo_amount'),
    )['total'] or Decimal('0.00')

    contributions = JimboContribution.objects.filter(branch=branch).exclude(status='CANCELLED')
    contributions = _period_filter(contributions, year, month, field='transaction__transaction_date')
    pending = contributions.aggregate(total=Sum('amount_due'))['total'] or Decimal('0.00')
    paid = contributions.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')

    return {
        'branch': branch.id,
        'branch_name': branch.name,
        'branch_code': branch.code,
        'currency': (branch.financial_account.currency if hasattr(branch, 'financial_account') else None)
        or 'TZS',
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net_balance': (total_income - total_expenses),
        'jimbo_contribution': jimbo_contribution,
        'jimbo_paid': paid,
        'pending_remittance': max(pending - paid, Decimal('0.00')),
        'branch_share': (total_income - jimbo_contribution),
        'transactions_count': transactions.count(),
    }


def jimbo_finance_summary(year=None, month=None):
    """
    Jimbo consolidated finance dashboard (SRS 17, 30).

    Total Branch Income / Total 10% Contributions / Received / Pending /
    Branches reporting X/Y.
    """
    from branches.models import Branch

    transactions = FinancialTransaction.objects.filter(
        branch__isnull=False, status__in=FinancialTransaction.POSTED_STATUSES,
    )
    transactions = _period_filter(transactions, year, month)
    total_branch_income = transactions.filter(transaction_type='INCOME').aggregate(
        total=Sum('amount'),
    )['total'] or Decimal('0.00')
    total_contributions = transactions.filter(transaction_type='INCOME').aggregate(
        total=Sum('jimbo_amount'),
    )['total'] or Decimal('0.00')

    contributions = JimboContribution.objects.exclude(status='CANCELLED')
    if year:
        contributions = contributions.filter(transaction__transaction_date__year=year)
    if month:
        contributions = contributions.filter(transaction__transaction_date__month=month)

    expected = contributions.aggregate(total=Sum('amount_due'))['total'] or Decimal('0.00')
    received = contributions.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    overdue = contributions.filter(status='OVERDUE').aggregate(total=Sum('amount_due'))['total'] or Decimal('0.00')

    total_branches = Branch.objects.filter(is_active=True).count()
    reporting_branches = contributions.values('branch_id').distinct().count()

    return {
        'total_branch_income': total_branch_income,
        'total_contributions': total_contributions,
        'expected_contributions': expected,
        'received': received,
        'pending': max(expected - received, Decimal('0.00')),
        'overdue': overdue,
        'branches_reporting': reporting_branches,
        'total_branches': total_branches,
        'collection_rate': (
            Decimal(received * 100) / Decimal(expected) if expected else Decimal('0.00')
        ).quantize(Decimal('0.01')),
    }


def pending_remittances(*, branch=None, overdue_only=False, user=None):
    """Outstanding 10% obligations used by the Jimbo cashier dashboard (SRS 60)."""
    from core import access

    queryset = (
        JimboContribution.objects
        .select_related('branch', 'transaction')
        .exclude(status__in=['CANCELLED', 'RECONCILED'])
        .filter(amount_paid__lt=F('amount_due'))
        .order_by('due_date', 'id')
    )
    if branch is not None:
        queryset = queryset.filter(branch=branch)
    if user is not None:
        queryset = access.apply_branch_scope(queryset, user)
    if overdue_only:
        queryset = queryset.filter(due_date__lt=timezone.localdate())
    return queryset


def mark_overdue_contributions():
    """Flag obligations whose due date passed (SRS 60) and return them."""
    today = timezone.localdate()
    updated = (
        JimboContribution.objects
        .filter(due_date__lt=today, amount_paid__lt=F('amount_due'), status='PENDING_REMITTANCE')
        .update(status='OVERDUE', updated_at=timezone.now())
    )
    return updated
