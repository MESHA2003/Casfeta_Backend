"""
Financial management (SRS 8 - 19, 53, 57 - 63, 84, 85).

Key rules enforced here:

* every branch has its own ledger (SRS 84);
* eligible income is split 90% branch / 10% Jimbo **on the server** (SRS 57);
* the percentage comes from the FinancialPolicy table, never from code
  (SRS 85) so historical transactions keep the percentage of their own date;
* financial records are never deleted, only reversed (SRS 19, 83 Rule 7/8).
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import SoftDeleteModel, TimeStampedModel


def default_currency():
    return settings.CZDMP['DEFAULT_CURRENCY']


def contribution_due_date():
    return timezone.localdate() + timedelta(days=settings.CZDMP['CONTRIBUTION_DUE_DAYS'])


class TransactionCategory(TimeStampedModel):
    """
    Income / expense category (SRS 16) plus the configurable
    "Subject to Jimbo 10%" flag (SRS 15).

    Only Jimbo administrators may change ``subject_to_jimbo_10`` so that
    income which the organisational policy exempts is never deducted by
    accident (SRS 15, 83 Rule 6).
    """

    CATEGORY_TYPES = [('INCOME', 'Income'), ('EXPENSE', 'Expense')]

    INCOME_DEFAULTS = [
        ('Membership Contributions', 'Michango ya Uanachama'),
        ('Event Registration', 'Usajili wa Matukio'),
        ('Donations', 'Michango ya Hiari'),
        ('Fundraising', 'Kuchangisha Fedha'),
        ('Offering', 'Sadaka'),
        ('Project Income', 'Mapato ya Miradi'),
        ('Merchandise', 'Mauzo ya Bidhaa'),
        ('Training Fees', 'Ada za Mafunzo'),
        ('Conference Fees', 'Ada za Kongamano'),
        ('Other Income', 'Mapato Mengine'),
    ]

    EXPENSE_DEFAULTS = [
        ('Transport', 'Usafiri'),
        ('Venue', 'Ukumbi'),
        ('Food', 'Chakula'),
        ('Printing', 'Uchapishaji'),
        ('Communication', 'Mawasiliano'),
        ('Equipment', 'Vifaa'),
        ('Accommodation', 'Malazi'),
        ('Evangelism', 'Uinjilisti'),
        ('Outreach', 'Huduma za Jamii'),
        ('Administration', 'Uendeshaji'),
        ('Other Expenses', 'Matumizi Mengine'),
    ]

    name = models.CharField(max_length=120)
    name_sw = models.CharField(max_length=120, blank=True)
    code = models.CharField(max_length=40, blank=True)
    category_type = models.CharField(max_length=10, choices=CATEGORY_TYPES, default='INCOME')
    subject_to_jimbo_10 = models.BooleanField(
        default=True,
        help_text='Only Jimbo administrators may change this. When YES, eligible income creates a Jimbo contribution.',
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_categories',
    )

    class Meta:
        ordering = ['category_type', 'name']
        verbose_name = 'Transaction category'
        verbose_name_plural = 'Transaction categories'
        constraints = [
            models.UniqueConstraint(fields=['name', 'category_type'], name='unique_category_per_type'),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_category_type_display()})'

    def save(self, *args, **kwargs):
        # Expense categories never carry a Jimbo contribution (SRS 15).
        if self.category_type == 'EXPENSE':
            self.subject_to_jimbo_10 = False
        if not self.code:
            self.code = (self.name or '').upper().replace(' ', '_')[:40]
        return super().save(*args, **kwargs)

    @classmethod
    def seed_defaults(cls):
        """Create the standard CASFETA categories (SRS 16)."""
        created = 0
        for name, name_sw in cls.INCOME_DEFAULTS:
            _, was_created = cls.objects.get_or_create(
                name=name, category_type='INCOME',
                defaults={'name_sw': name_sw, 'subject_to_jimbo_10': True},
            )
            created += 1 if was_created else 0
        for name, name_sw in cls.EXPENSE_DEFAULTS:
            _, was_created = cls.objects.get_or_create(
                name=name, category_type='EXPENSE',
                defaults={'name_sw': name_sw, 'subject_to_jimbo_10': False},
            )
            created += 1 if was_created else 0
        return created

class FinancialAccount(TimeStampedModel):
    """
    Virtual ledger (SRS 84): one per branch plus a consolidated Jimbo ledger.

    BRANCH LEDGER : income, expenses, branch share, Jimbo obligation
    JIMBO LEDGER  : contributions, Jimbo expenses, receivables, reconciled funds
    """

    ACCOUNT_TYPES = [('BRANCH', 'Branch ledger'), ('JIMBO', 'Jimbo consolidated ledger')]

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=40, blank=True)
    account_type = models.CharField(max_length=10, choices=ACCOUNT_TYPES, default='BRANCH')
    branch = models.OneToOneField(
        'branches.Branch', on_delete=models.CASCADE, null=True, blank=True, related_name='financial_account',
    )
    currency = models.CharField(max_length=10, default=default_currency)
    opening_balance = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0.00'))
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['account_type', 'name']
        constraints = [
            models.UniqueConstraint(fields=['account_type', 'name'], name='unique_account_name_per_type'),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_account_type_display()})'

    def clean(self):
        if self.account_type == 'BRANCH' and not self.branch_id:
            raise ValidationError({'branch': 'A branch ledger must be linked to a branch.'})
        if self.account_type == 'JIMBO' and self.branch_id:
            raise ValidationError({'branch': 'The Jimbo ledger must not be linked to a branch.'})

    def _posted(self):
        return self.transactions.filter(status__in=FinancialTransaction.POSTED_STATUSES)

    @property
    def total_income(self):
        return self._posted().filter(transaction_type='INCOME').aggregate(
            total=models.Sum('amount'),
        )['total'] or Decimal('0.00')

    @property
    def total_expenses(self):
        return self._posted().filter(transaction_type='EXPENSE').aggregate(
            total=models.Sum('amount'),
        )['total'] or Decimal('0.00')

    @property
    def balance(self):
        return self.opening_balance + self.total_income - self.total_expenses

class FinancialTransaction(SoftDeleteModel):
    """
    One financial record of a branch or of the Jimbo (SRS 14, 53).

    The 10% / 90% split is always calculated by the backend when the
    transaction is recorded; the frontend is never trusted with the final
    financial values (SRS 57) and the cashier cannot change them (SRS 83
    Rule 6).
    """

    TRANSACTION_TYPES = [('INCOME', 'Income'), ('EXPENSE', 'Expense')]

    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('RECORDED', 'Recorded'),
        ('PENDING_VERIFICATION', 'Pending verification'),
        ('APPROVED', 'Approved'),
        ('PENDING_REMITTANCE', 'Pending remittance'),
        ('REMITTED', 'Remitted'),
        ('RECEIVED', 'Received'),
        ('RECONCILED', 'Reconciled'),
        ('REJECTED', 'Rejected'),
        ('REVERSED', 'Reversed'),
    ]

    #: statuses that count as real money movements in the ledger
    POSTED_STATUSES = (
        'RECORDED', 'PENDING_VERIFICATION', 'APPROVED', 'PENDING_REMITTANCE',
        'REMITTED', 'RECEIVED', 'RECONCILED',
    )

    PAYMENT_METHODS = [
        ('CASH', 'Cash (Fedha taslimu)'),
        ('BANK', 'Bank transfer'),
        ('MOBILE_MONEY', 'Mobile money'),
        ('CHEQUE', 'Cheque'),
        ('OTHER', 'Other approved method'),
    ]

    transaction_id = models.CharField(max_length=40, unique=True, blank=True, db_index=True)
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.PROTECT, related_name='transactions',
        null=True, blank=True, help_text='Empty for Jimbo level transactions.',
    )
    account = models.ForeignKey(
        FinancialAccount, on_delete=models.PROTECT, null=True, blank=True, related_name='transactions',
    )
    cashier = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='recorded_transactions',
        help_text='Cashier who recorded the transaction.',
    )
    category = models.ForeignKey(TransactionCategory, on_delete=models.PROTECT, related_name='transactions')
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES, default='INCOME')
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=16, decimal_places=2)

    subject_to_jimbo_10 = models.BooleanField(default=False, editable=False)
    jimbo_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'), editable=False)
    jimbo_amount = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0.00'), editable=False)
    branch_amount = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0.00'), editable=False)

    transaction_date = models.DateField(default=timezone.localdate, db_index=True)
    payment_method = models.CharField(max_length=15, choices=PAYMENT_METHODS, default='CASH')
    reference_number = models.CharField(max_length=80, blank=True)
    receipt_number = models.CharField(max_length=80, blank=True)
    attachment = models.FileField(upload_to='finance/evidence/', blank=True, null=True)

    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='RECORDED', db_index=True)
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_transactions',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_transactions',
    )
    received_at = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    # Reversal instead of deletion (SRS 19, 83 Rule 8)
    is_reversal = models.BooleanField(default=False)
    reversal_of = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True, related_name='reversed_by',
    )
    reversal_reason = models.TextField(blank=True)

    # Optional links that make reporting richer without duplicating data
    source_event = models.ForeignKey(
        'events.Event', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions',
    )
    ministry = models.ForeignKey(
        'ministries.Ministry', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions',
    )
    source = models.CharField(max_length=60, blank=True, help_text='e.g. Event registration, manual entry.')

    class Meta:
        ordering = ['-transaction_date', '-id']
        verbose_name = 'Financial transaction'
        verbose_name_plural = 'Financial transactions'
        constraints = [
            models.CheckConstraint(check=models.Q(amount__gt=0), name='transaction_amount_positive'),
        ]
        indexes = [
            models.Index(fields=['branch', 'status']),
            models.Index(fields=['transaction_date', 'transaction_type']),
        ]

    def __str__(self):
        return f'{self.transaction_id} - {self.description} ({self.amount})'

    # -- validation ---------------------------------------------------------

    def clean(self):
        """SRS 78: an amount of zero or less is rejected with a clear message."""
        if self.amount is None or self.amount <= 0:
            raise ValidationError({'amount': 'Amount must be greater than zero. (Kiasi kiwe zaidi ya sifuri.)'})
        if self.transaction_type == 'INCOME' and self.subject_to_jimbo_10:
            if self.jimbo_amount + self.branch_amount != self.amount:
                raise ValidationError({
                    'amount': 'The Jimbo and branch allocations must add up to the gross amount.',
                })

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = self._generate_transaction_id()
        return super().save(*args, **kwargs)

    def _generate_transaction_id(self):
        year = (self.transaction_date or timezone.localdate()).year
        prefix = f'CZ-TXN-{year}-'
        last = (
            FinancialTransaction.objects.filter(transaction_id__startswith=prefix)
            .order_by('-transaction_id')
            .values_list('transaction_id', flat=True)
            .first()
        )
        sequence = int(last.split('-')[-1]) + 1 if last else 1
        candidate = f'{prefix}{sequence:06d}'
        while FinancialTransaction.objects.filter(transaction_id=candidate).exists():
            sequence += 1
            candidate = f'{prefix}{sequence:06d}'
        return candidate

    # -- helpers ------------------------------------------------------------

    @property
    def currency(self):
        return (self.account.currency if self.account_id else None) or default_currency()

    @property
    def is_income(self):
        return self.transaction_type == 'INCOME'

    @property
    def jimbo_obligation(self):
        """Jimbo contribution created by this transaction, when applicable."""
        return getattr(self, 'jimbo_contribution', None)

    def can_be_reversed(self):
        return self.status not in {'REVERSED', 'REJECTED'} and not self.is_reversal

    def can_be_deleted(self):
        """Financial transactions are never deleted (SRS 18, 83 Rule 7)."""
        return False


class JimboContribution(TimeStampedModel):
    """
    The 10% obligation created automatically for every eligible branch income
    (SRS 9, 11, 53, 60).

    A transaction has one obligation; a partial remittance can pay part of it,
    which is why ``amount_paid`` is tracked separately (SRS 61).
    """

    STATUS_CHOICES = [
        ('PENDING_REMITTANCE', 'Pending remittance'),
        ('PARTIAL', 'Partially paid'),
        ('REMITTED', 'Remitted (awaiting confirmation)'),
        ('RECEIVED', 'Received by Jimbo'),
        ('RECONCILED', 'Reconciled'),
        ('OVERDUE', 'Overdue'),
        ('CANCELLED', 'Cancelled (reversal)'),
    ]

    transaction = models.OneToOneField(
        FinancialTransaction, on_delete=models.CASCADE, related_name='jimbo_contribution',
    )
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='jimbo_contributions')
    amount_due = models.DecimalField(max_digits=16, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0.00'))
    percentage_applied = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('10.00'))
    due_date = models.DateField(default=contribution_due_date, db_index=True)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='PENDING_REMITTANCE', db_index=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_contributions',
    )
    received_at = models.DateTimeField(null=True, blank=True)
    reconciled_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciled_contributions',
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Jimbo contribution'
        verbose_name_plural = 'Jimbo contributions'
        indexes = [models.Index(fields=['branch', 'status'])]

    def __str__(self):
        return f'{self.branch.code} - {self.amount_due} ({self.get_status_display()})'

    @property
    def balance(self):
        return max(self.amount_due - self.amount_paid, Decimal('0.00'))

    @property
    def is_settled(self):
        return self.amount_paid >= self.amount_due

    @property
    def is_overdue(self):
        if self.is_settled or self.status in {'CANCELLED', 'RECONCILED'}:
            return False
        return self.due_date < timezone.localdate()

    def refresh_status(self):
        """Recompute PENDING / PARTIAL / OVERDUE from the recorded amounts."""
        if self.status in {'CANCELLED', 'RECONCILED'}:
            return self
        if self.amount_paid <= 0:
            self.status = 'OVERDUE' if self.is_overdue else 'PENDING_REMITTANCE'
        elif self.amount_paid < self.amount_due:
            self.status = 'PARTIAL'
        else:
            self.status = 'RECEIVED'
        self.save(update_fields=['status', 'updated_at'])
        return self


class Remittance(TimeStampedModel):
    """
    A payment from a branch to the Jimbo covering its 10% obligations
    (SRS 60, 61).

    The Jimbo cashier verifies and confirms receipt; partial payments are
    supported and explicitly flagged (SRS 61).
    """

    STATUS_CHOICES = [
        ('SUBMITTED', 'Submitted'),
        ('VERIFIED', 'Verified'),
        ('PARTIAL', 'Partial payment'),
        ('RECEIVED', 'Received'),
        ('RECONCILED', 'Reconciled'),
        ('REJECTED', 'Rejected'),
    ]

    remittance_number = models.CharField(max_length=40, unique=True, blank=True)
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='remittances')
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    payment_method = models.CharField(max_length=15, choices=FinancialTransaction.PAYMENT_METHODS, default='BANK')
    reference_number = models.CharField(max_length=80, blank=True)
    receipt_number = models.CharField(max_length=80, blank=True)
    evidence = models.FileField(upload_to='finance/remittance_evidence/', blank=True, null=True)
    payment_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='SUBMITTED', db_index=True)

    submitted_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='submitted_remittances')
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_remittances',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_remittances',
    )
    received_at = models.DateTimeField(null=True, blank=True)
    reconciled_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reconciled_remittances',
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-payment_date', '-id']
        indexes = [models.Index(fields=['branch', 'status'])]

    def __str__(self):
        return f'{self.remittance_number or "REM"} - {self.branch.code} {self.amount}'

    def clean(self):
        if self.amount is None or self.amount <= 0:
            raise ValidationError({'amount': 'Amount must be greater than zero.'})

    def save(self, *args, **kwargs):
        if not self.remittance_number:
            year = (self.payment_date or timezone.localdate()).year
            prefix = f'CZ-REM-{year}-'
            count = Remittance.objects.filter(remittance_number__startswith=prefix).count() + 1
            candidate = f'{prefix}{count:05d}'
            while Remittance.objects.filter(remittance_number=candidate).exists():
                count += 1
                candidate = f'{prefix}{count:05d}'
            self.remittance_number = candidate
        return super().save(*args, **kwargs)

    @property
    def allocated_amount(self):
        return self.allocations.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')

    @property
    def unallocated_amount(self):
        return max(self.amount - self.allocated_amount, Decimal('0.00'))


class RemittanceAllocation(TimeStampedModel):
    """
    Links a remittance payment to the contribution(s) it settles (SRS 61).

    Allocations make "Expected 25,000 / Received 20,000 -> PARTIAL PAYMENT,
    balance 5,000" auditable instead of a manual note.
    """

    remittance = models.ForeignKey(Remittance, on_delete=models.CASCADE, related_name='allocations')
    contribution = models.ForeignKey(JimboContribution, on_delete=models.PROTECT, related_name='allocations')
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_allocations',
    )

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['remittance', 'contribution'], name='unique_allocation'),
        ]

    def __str__(self):
        return f'{self.remittance.remittance_number} -> {self.contribution.branch.code} {self.amount}'


class ReconciliationRecord(TimeStampedModel):
    """
    Monthly branch - Jimbo reconciliation (SRS 61).

    Expected 25,000 / Received 25,000  -> RECONCILED
    Expected 25,000 / Received 20,000  -> PARTIAL PAYMENT, balance 5,000
    """

    STATUS_CHOICES = [
        ('RECONCILED', 'Reconciled'),
        ('PARTIAL', 'Partial payment'),
        ('OVERDUE', 'Overdue'),
        ('PENDING', 'Pending'),
    ]

    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='reconciliations')
    period_year = models.PositiveSmallIntegerField()
    period_month = models.PositiveSmallIntegerField()
    expected_amount = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0.00'))
    received_amount = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal('0.00'))
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='PENDING')
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_reconciliations',
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-period_year', '-period_month']
        verbose_name = 'Reconciliation record'
        verbose_name_plural = 'Reconciliation records'
        constraints = [
            models.UniqueConstraint(fields=['branch', 'period_year', 'period_month'],
                                    name='unique_reconciliation_per_month'),
        ]

    def __str__(self):
        return f'{self.branch.code} {self.period_year}-{self.period_month:02d}'

    @property
    def difference(self):
        return self.expected_amount - self.received_amount

    @property
    def balance_due(self):
        return max(self.difference, Decimal('0.00'))

    def refresh(self, verified_by=None, notes=''):
        """Recompute the expected/actual position from remittances (SRS 61)."""
        from django.db.models.functions import TruncMonth

        allocations = RemittanceAllocation.objects.filter(
            contribution__branch=self.branch,
            remittance__payment_date__year=self.period_year,
            remittance__payment_date__month=self.period_month,
            remittance__status__in=['SUBMITTED', 'VERIFIED', 'PARTIAL', 'RECEIVED', 'RECONCILED'],
        )
        contributions = JimboContribution.objects.filter(
            branch=self.branch,
            transaction__transaction_date__year=self.period_year,
            transaction__transaction_date__month=self.period_month,
        ).exclude(status='CANCELLED')

        self.expected_amount = contributions.aggregate(total=models.Sum('amount_due'))['total'] or Decimal('0.00')
        self.received_amount = allocations.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')

        if self.expected_amount == 0:
            self.status = 'RECONCILED'
        elif self.received_amount >= self.expected_amount:
            self.status = 'RECONCILED'
        elif self.received_amount > 0:
            self.status = 'PARTIAL'
        else:
            self.status = 'OVERDUE'

        if verified_by is not None and getattr(verified_by, 'is_authenticated', False):
            self.verified_by = verified_by
        self.reconciled_at = timezone.now()
        if notes:
            self.notes = notes
        self.save()
        return self


class ReversalRequest(TimeStampedModel):
    """
    Correction workflow: original transaction -> reversal request ->
    authorization -> reversal transaction -> audit record (SRS 19).

    Financial records are never deleted; a reversal creates a new,
    opposite financial record that references the original one.
    """

    STATUS_CHOICES = [
        ('REQUESTED', 'Requested'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]

    transaction = models.ForeignKey(FinancialTransaction, on_delete=models.CASCADE, related_name='reversal_requests')
    reason = models.TextField(help_text='Why the transaction must be reversed.')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='REQUESTED', db_index=True)
    requested_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='requested_reversals',
    )
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_reversals',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    reversal_transaction = models.OneToOneField(
        FinancialTransaction, on_delete=models.SET_NULL, null=True, blank=True, related_name='reversal_request',
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Reversal request'
        verbose_name_plural = 'Reversal requests'

    def __str__(self):
        return f'Reversal of {self.transaction.transaction_id} ({self.get_status_display()})'

