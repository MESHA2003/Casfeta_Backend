"""
Seed the default CZDMP catalogue data (SRS sections 6, 16, 19, 25, 29, 47, 85, 86).

The command is idempotent: existing records are never modified, only missing
defaults are created, so it is safe to run repeatedly::

    python manage.py seed_czdmp
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Role
from branches.models import Branch
from core import roles as role_catalogue
from core.models import AcademicYear, District, FinancialPolicy, Organization, SystemSetting
from events.models import EventCategory
from finance.models import TransactionCategory
from reports.models import ReportType
from resources.models import ResourceCategory

# The two Zanzibar islands with their standard districts (SRS 2.1). The
# District model is configurable, these rows are only the starting catalogue.
ZANZIBAR_DISTRICTS = {
    'Unguja': [
        ('Kaskazini A', 'KASKAZINI_A'),
        ('Kaskazini B', 'KASKAZINI_B'),
        ('Kati', 'KATI'),
        ('Kusini A', 'KUSINI_A'),
        ('Kusini B', 'KUSINI_B'),
        ('Mjini', 'MJINI'),
        ('Magharibi', 'MAGHARIBI'),
    ],
    'Pemba': [
        ('Chake Chake', 'CHAKE_CHAKE'),
        ('Micheweni', 'MICHEWENI'),
        ('Mkoani', 'MKOANI'),
        ('Wete', 'WETE'),
    ],
}

# Starter branch catalogue (SRS 22, 37): real higher learning institutions in
# Zanzibar. These rows only make the public branch directory and the
# registration form work on a fresh database; administrators manage branches
# afterwards through the Branches module (add, rename, deactivate, districts).
DEFAULT_BRANCHES = [
    'SUZA - State University of Zanzibar',
    'SUZA Pemba Campus',
    'Zanzibar University (ZU)',
    'OUT Zanzibar Centre',
    'College of Health Sciences - Mnazi Mmoja',
    'Zanzibar School of Health (ZSH)',
    'Nkrumah Teachers Training College',
    'Institute of Public Administration (IPA)',
    'Zanzibar Institute of Financial Administration (ZIFA)',
    'Karume Institute of Science and Technology (KIST)',
    'VETA Zanzibar',
    'Pemba School of Health Sciences',
    'Pemba Teachers Training College',
    'Pemba VETA College',
]

# Minimal public platform settings - administrators can edit them afterwards
# in /admin/core/systemsetting/.
DEFAULT_SETTINGS = [
    {'key': 'platform_name', 'value': 'CASFETA Zanzibar', 'label': 'Platform name'},
    {'key': 'default_currency', 'value': 'TZS', 'label': 'Default currency'},
]


class Command(BaseCommand):
    help = 'Seed default CZDMP catalogues (organisation, roles, districts, branches, policies, categories).'

    def handle(self, *args, **options):
        with transaction.atomic():
            steps = [
                ('organisation', self._seed_organization()),
                ('academic year', self._seed_academic_year()),
                ('financial policy', self._seed_financial_policy()),
                ('roles', self._seed_roles()),
                ('system settings', self._seed_settings()),
                ('districts', self._seed_districts()),
                ('branches', self._seed_branches()),
                ('event categories', EventCategory.seed_defaults()),
                ('report types', ReportType.seed_defaults()),
                ('transaction categories', TransactionCategory.seed_defaults()),
                ('resource categories', ResourceCategory.seed_defaults()),
            ]
        for label, created in steps:
            self.stdout.write(f'  {label}: {created} created')
        self.stdout.write(self.style.SUCCESS('CZDMP seed data ready.'))

    # === SEED METHODS ===

    def _seed_organization(self):
        """The Jimbo profile is a single record (SRS 2.1)."""
        existed = Organization.objects.count()
        Organization.get_solo()
        return 1 if existed == 0 else 0

    def _seed_academic_year(self):
        """Create the current academic / membership year (SRS 86).

        Academic years run 1 August - 31 July and are named ``2025/2026``.
        """
        if AcademicYear.objects.filter(is_current=True).exists():
            return 0
        today = date.today()
        start_year = today.year if today.month >= 8 else today.year - 1
        name = f'{start_year}/{start_year + 1}'
        if AcademicYear.objects.filter(name=name).exists():
            return 0
        AcademicYear.objects.create(
            name=name,
            start_date=date(start_year, 8, 1),
            end_date=date(start_year + 1, 7, 31),
            is_current=True,
            is_membership_year=True,
        )
        return 1

    def _seed_financial_policy(self):
        """Initial Jimbo contribution policy (SRS 85)."""
        if FinancialPolicy.objects.exists():
            return 0
        FinancialPolicy.objects.create(
            name='Jimbo Branch Contribution',
            contribution_percentage=FinancialPolicy.default_percentage(),
            effective_date=date.today(),
            status='ACTIVE',
            description='Initial policy created by seed_czdmp.',
        )
        return 1

    def _seed_roles(self):
        """Create the canonical role catalogue (SRS 6, 7)."""
        created = 0
        for entry in role_catalogue.ROLE_CATALOGUE:
            _, was_created = Role.objects.get_or_create(
                code=entry['code'],
                defaults={
                    'name': entry['name'],
                    'name_sw': entry['name_sw'],
                    'scope': entry['scope'],
                    'level': role_catalogue.LEVELS.get(entry['code'], 0),
                    'description': entry['description'],
                    'is_system': True,
                },
            )
            created += 1 if was_created else 0
        return created

    def _seed_branches(self):
        """Create the starter branch directory (SRS 22, 37).

        The public branch directory and the registration form need at least
        one ACTIVE branch, so a fresh database is never empty here. Existing
        branches are never modified, only missing ones are created.
        """
        created = 0
        organization = Organization.get_solo()
        for name in DEFAULT_BRANCHES:
            _, was_created = Branch.objects.get_or_create(
                name=name,
                defaults={'organization': organization, 'status': 'ACTIVE'},
            )
            created += 1 if was_created else 0
        return created

    def _seed_settings(self):
        """Create the minimal public platform settings (SRS 86)."""
        created = 0
        for setting in DEFAULT_SETTINGS:
            _, was_created = SystemSetting.objects.get_or_create(
                key=setting['key'],
                defaults={
                    'value': setting['value'],
                    'value_type': 'STRING',
                    'group': 'general',
                    'label': setting['label'],
                    'is_public': True,
                },
            )
            created += 1 if was_created else 0
        return created

    def _seed_districts(self):
        """Create the island parents and their standard districts (SRS 2.1)."""
        created = 0
        for island, districts in ZANZIBAR_DISTRICTS.items():
            island_row, was_created = District.objects.get_or_create(
                name=island, region='Zanzibar', defaults={'code': island.upper()},
            )
            created += 1 if was_created else 0
            for name, code in districts:
                _, was_created = District.objects.get_or_create(
                    name=name, region='Zanzibar',
                    defaults={'code': code, 'parent': island_row},
                )
                created += 1 if was_created else 0
        return created
