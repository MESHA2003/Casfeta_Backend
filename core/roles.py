"""
Role catalogue and role hierarchy for CZDMP (SRS sections 6, 7, 83).

Roles are stored in the database (accounts.Role) and granted through
accounts.RoleAssignment, which is optionally scoped to a single branch.
This module only defines the canonical codes, human readable names and the
hierarchy level used for "at least this role" checks.
"""

# --- Role codes -------------------------------------------------------------

PUBLIC_USER = 'PUBLIC_USER'
MEMBER = 'MEMBER'
MINISTRY_LEADER = 'MINISTRY_LEADER'
BRANCH_CASHIER = 'BRANCH_CASHIER'
BRANCH_SECRETARY = 'BRANCH_SECRETARY'
BRANCH_LEADER = 'BRANCH_LEADER'
JIMBO_CASHIER = 'JIMBO_CASHIER'
JIMBO_FINANCE_OFFICER = 'JIMBO_FINANCE_OFFICER'
JIMBO_ADMIN = 'JIMBO_ADMIN'
SUPER_ADMIN = 'SUPER_ADMIN'

# --- Hierarchy levels -------------------------------------------------------
# Higher number == more authority. Only the order matters, not the exact value.

LEVELS = {
    PUBLIC_USER: 0,
    MEMBER: 10,
    MINISTRY_LEADER: 20,
    BRANCH_CASHIER: 30,
    BRANCH_SECRETARY: 30,
    BRANCH_LEADER: 40,
    JIMBO_CASHIER: 60,
    JIMBO_FINANCE_OFFICER: 65,
    JIMBO_ADMIN: 80,
    SUPER_ADMIN: 100,
}

# --- Display data used by the seeding command and the frontend --------------

ROLE_CATALOGUE = [
    {
        'code': SUPER_ADMIN,
        'name': 'Super Administrator',
        'name_sw': 'Msimamizi Mkuu wa Mfumo',
        'scope': 'SYSTEM',
        'description': 'Highest technical role: system configuration, security, backups, integrations and audit.',
    },
    {
        'code': JIMBO_ADMIN,
        'name': 'Jimbo Administrator',
        'name_sw': 'Msimamizi wa Jimbo',
        'scope': 'JIMBO',
        'description': 'Manages branches, users, roles, leaders, ministries, organisational structure and announcements.',
    },
    {
        'code': JIMBO_FINANCE_OFFICER,
        'name': 'Jimbo Finance Officer',
        'name_sw': 'Afisa Fedha wa Jimbo',
        'scope': 'JIMBO',
        'description': 'Monitors all transactions, reviews branch income/expenses, monitors the 10% contributions and approves adjustments.',
    },
    {
        'code': JIMBO_CASHIER,
        'name': 'Jimbo Cashier',
        'name_sw': 'Mhazini wa Jimbo',
        'scope': 'JIMBO',
        'description': 'Receives 10% contribution notifications, verifies payments, confirms funds and reconciles remittances.',
    },
    {
        'code': BRANCH_LEADER,
        'name': 'Branch Leader',
        'name_sw': 'Kiongozi wa Tawi',
        'scope': 'BRANCH',
        'description': 'Approves membership applications, manages branch activities, events, ministries and reports.',
    },
    {
        'code': BRANCH_SECRETARY,
        'name': 'Branch Secretary',
        'name_sw': 'Katibu wa Tawi',
        'scope': 'BRANCH',
        'description': 'Maintains branch records, minutes, reports, announcements and branch documents.',
    },
    {
        'code': BRANCH_CASHIER,
        'name': 'Branch Cashier',
        'name_sw': 'Mhazini wa Tawi',
        'scope': 'BRANCH',
        'description': 'Records branch income and expenses, uploads receipts and requests reversals. Cannot change the 10%.',
    },
    {
        'code': MINISTRY_LEADER,
        'name': 'Ministry Leader',
        'name_sw': 'Kiongozi wa Huduma',
        'scope': 'MINISTRY',
        'description': 'Leads a ministry, its members, activities, events and reports.',
    },
    {
        'code': MEMBER,
        'name': 'Member',
        'name_sw': 'Mwanachama',
        'scope': 'SELF',
        'description': 'Approved CASFETA member: profile, membership card, events, attendance, resources and prayer requests.',
    },
    {
        'code': PUBLIC_USER,
        'name': 'Public User',
        'name_sw': 'Mtumiaji wa Umma',
        'scope': 'PUBLIC',
        'description': 'Registered account without an approved membership (applicant).',
    },
]

# Roles allowed to define which financial categories are subject to the
# Jimbo 10% (SRS sections 15, 83 Rule 6+10).
FINANCE_POLICY_ROLES = [SUPER_ADMIN, JIMBO_ADMIN]

# Roles that can see consolidated Jimbo finances.
JIMBO_FINANCE_ROLES = [SUPER_ADMIN, JIMBO_ADMIN, JIMBO_FINANCE_OFFICER, JIMBO_CASHIER]

# Roles that operate at branch level and therefore need a branch scope.
BRANCH_SCOPED_ROLES = [BRANCH_LEADER, BRANCH_SECRETARY, BRANCH_CASHIER, MINISTRY_LEADER, MEMBER]


def level_of(role_code):
    """Return the hierarchy level of a role code (0 when unknown)."""
    return LEVELS.get(role_code, 0)


def role_label(role_code):
    for entry in ROLE_CATALOGUE:
        if entry['code'] == role_code:
            return entry['name']
    return role_code
