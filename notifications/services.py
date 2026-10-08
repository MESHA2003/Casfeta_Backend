"""
Notification services (SRS 11, 35, 36, 44, 59, 60, 69).

``notify_user`` is the single funnel for in-system notifications; the
specialised helpers below build the financial and reporting messages
described in the SRS. Delivery failures never break the business operation
that triggered them - they are logged instead.
"""

import logging

from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger('czdmp.notifications')


def notify_user(recipient, title, body='', category='SYSTEM', priority='NORMAL',
                branch=None, related_entity='', related_object_id='', action_url='', payload=None):
    """Create one in-system notification for one user (SRS 36, 69)."""
    if recipient is None or not getattr(recipient, 'is_active', False):
        return None

    from .models import Notification, NotificationPreference

    preference, _ = NotificationPreference.objects.get_or_create(user=recipient)
    if not preference.in_system:
        return None

    return Notification.objects.create(
        recipient=recipient,
        title=title[:200],
        body=body or '',
        category=category,
        priority=priority,
        branch=branch,
        related_entity=related_entity or '',
        related_object_id=str(related_object_id or ''),
        action_url=action_url or '',
        payload=payload or None,
        sent_at=timezone.now(),
    )


def recipients_for_role(role_code, branch=None):
    """
    Users holding ``role_code`` (SRS 6, 35).

    Branch scoped roles are limited to the given branch when one is provided.
    """
    from accounts.models import RoleAssignment

    queryset = (
        RoleAssignment.objects
        .filter(is_active=True, role__code=role_code, role__is_active=True, user__is_active=True)
        .select_related('user')
    )
    if branch is not None:
        queryset = queryset.filter(Q(branch=branch) | Q(branch__isnull=True))
    return [assignment.user for assignment in queryset]


def notify_role(role_code, title, body='', branch=None, **kwargs):
    """Notify every user that holds a role (e.g. all Jimbo cashiers)."""
    created = []
    for recipient in recipients_for_role(role_code, branch=branch):
        notification = notify_user(recipient, title, body, **kwargs)
        if notification:
            created.append(notification)
    return created

def notify_announcement_recipients(announcement):
    """
    Fan an announcement out to the audience selected in SRS 35.

    A branch may only reach users inside its own scope, so the branch filter
    is always applied when the announcement belongs to a branch.
    """
    queryset = User.objects.filter(is_active=True)
    audience = announcement.audience

    if audience in {'ALL_MEMBERS', 'BRANCH'}:
        queryset = queryset.filter(role_assignments__is_active=True, role_assignments__role__code='MEMBER')
    elif audience == 'LEADERS':
        queryset = queryset.filter(
            role_assignments__is_active=True,
            role_assignments__role__code__in=['BRANCH_LEADER', 'BRANCH_SECRETARY', 'MINISTRY_LEADER'],
        )
    elif audience == 'CASHIERS':
        queryset = queryset.filter(
            role_assignments__is_active=True, role_assignments__role__code='BRANCH_CASHIER',
        )
    elif audience == 'FINANCE':
        queryset = queryset.filter(
            role_assignments__is_active=True,
            role_assignments__role__code__in=['JIMBO_CASHIER', 'JIMBO_FINANCE_OFFICER'],
        )
    elif audience == 'MINISTRY' and announcement.ministry_id:
        queryset = queryset.filter(role_assignments__ministry=announcement.ministry)
    elif audience == 'PUBLIC':
        return 0  # public content is read from the website, not pushed to users

    if announcement.branch_id:
        # Branch scope is always enforced (SRS 35, 83 Rule 14).
        queryset = queryset.filter(role_assignments__branch=announcement.branch)

    created = 0
    for recipient in queryset.distinct():
        notification = notify_user(
            recipient,
            title=announcement.title,
            body=(announcement.summary or announcement.body)[:500],
            category='ANNOUNCEMENT',
            branch=announcement.branch,
            related_entity='Announcement',
            related_object_id=announcement.pk,
            action_url=f'/announcements/{announcement.pk}',
        )
        if notification:
            created += 1
    return created


def notify_announcement(announcement):
    """Convenience wrapper used by the announcement viewset."""
    try:
        return notify_announcement_recipients(announcement)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning('Announcement %s could not be fanned out: %s', announcement.pk, exc)
        return 0

def notify_new_contribution(contribution):
    """
    SRS 11 - notify the Jimbo cashier about a new branch contribution.

    NEW BRANCH CONTRIBUTION
    Branch: SUZA Branch
    Transaction: Event Registration
    Amount: TZS 100,000
    Jimbo Contribution (10%): TZS 10,000
    Branch Share (90%): TZS 90,000
    Transaction ID: CZ-TXN-2026-000145
    Status: PENDING REMITTANCE
    """
    transaction = contribution.transaction
    title = f'NEW BRANCH CONTRIBUTION - {contribution.branch.name}'
    body = (
        f'Branch: {contribution.branch.name}\n'
        f'Transaction: {transaction.category.name}\n'
        f'Amount: TZS {transaction.amount:,.0f}\n'
        f'\n'
        f'Jimbo Contribution ({contribution.percentage_applied}%): TZS {contribution.amount_due:,.0f}\n'
        f'Branch Share ({100 - contribution.percentage_applied}%): TZS {transaction.branch_amount:,.0f}\n'
        f'\n'
        f'Transaction ID: {transaction.transaction_id}\n'
        f'Due: {contribution.due_date:%d/%m/%Y}\n'
        f'Status: PENDING REMITTANCE'
    )
    payload = {
        'transaction_id': transaction.transaction_id,
        'branch': contribution.branch.name,
        'amount': str(transaction.amount),
        'jimbo_amount': str(contribution.amount_due),
        'branch_amount': str(transaction.branch_amount),
        'percentage': str(contribution.percentage_applied),
        'due_date': str(contribution.due_date),
    }
    return notify_role(
        'JIMBO_CASHIER', title=title, body=body, category='FINANCE', priority='HIGH',
        branch=contribution.branch, related_entity='JimboContribution',
        related_object_id=contribution.pk, action_url='/finance/jimbo-contributions', payload=payload,
    )


def notify_remittance_submitted(remittance):
    title = f'REMITTANCE SUBMITTED - {remittance.branch.name}'
    body = (
        f'Remittance: {remittance.remittance_number}\n'
        f'Branch: {remittance.branch.name}\n'
        f'Amount: TZS {remittance.amount:,.0f}\n'
        f'Method: {remittance.get_payment_method_display()}\n'
        f'Reference: {remittance.reference_number or "-"}\n'
        f'Status: SUBMITTED (awaiting confirmation)'
    )
    return notify_role(
        'JIMBO_CASHIER', title=title, body=body, category='FINANCE', priority='HIGH',
        branch=remittance.branch, related_entity='Remittance', related_object_id=remittance.pk,
        action_url='/finance/remittances', payload={'remittance': remittance.remittance_number},
    )


def notify_remittance_confirmed(remittance):
    title = f'REMITTANCE RECEIVED - {remittance.branch.name}'
    body = (
        f'Remittance: {remittance.remittance_number}\n'
        f'Branch: {remittance.branch.name}\n'
        f'Amount received: TZS {remittance.amount:,.0f}\n'
        f'Confirmed by: {remittance.received_by.username if remittance.received_by else "-"}\n'
        f'Status: RECEIVED'
    )
    return notify_role(
        'BRANCH_CASHIER', title=title, body=body, category='FINANCE', priority='NORMAL',
        branch=remittance.branch, related_entity='Remittance', related_object_id=remittance.pk,
        action_url='/finance/remittances',
    )

def notify_report_reminder(report, recipients):
    """
    SRS 59 - remind the branch secretary, branch leader and Jimbo
    administration when a report was not submitted.
    """
    title = f'REPORT REMINDER - {report.branch.name}'
    body = (
        f'{report.branch.name} has not submitted the '
        f'{report.period_label or report.period_year} {report.report_type.name}.\n'
        f'\nDeadline: {report.deadline:%d %B %Y}\nStatus: NOT SUBMITTED'
    )
    created = []
    for recipient in recipients:
        notification = notify_user(
            recipient, title=title, body=body, category='REPORT', priority='HIGH',
            branch=report.branch, related_entity='BranchReport', related_object_id=report.pk,
            action_url=f'/branch/reports/{report.pk}',
        )
        if notification:
            created.append(notification)
    return created


def notify_remittance_overdue(contribution):
    """SRS 60 - overdue contribution reminder to all four roles."""
    title = f'PENDING JIMBO REMITTANCE - {contribution.branch.name}'
    body = (
        f'Branch: {contribution.branch.name}\n'
        f'Amount: TZS {contribution.balance:,.0f}\n'
        f'Due: {contribution.due_date:%d %B %Y}\n'
        f'Status: OVERDUE\n'
        f'Transaction: {contribution.transaction.transaction_id}'
    )
    created = []
    for role_code in ['BRANCH_CASHIER', 'BRANCH_LEADER', 'JIMBO_CASHIER', 'JIMBO_FINANCE_OFFICER']:
        created.extend(
            notify_role(
                role_code, title=title, body=body, category='FINANCE', priority='URGENT',
                branch=contribution.branch, related_entity='JimboContribution',
                related_object_id=contribution.pk, action_url='/finance/jimbo-contributions',
            )
        )
    return created
