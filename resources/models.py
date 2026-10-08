"""
Digital library, academic hub, document management and website content
(SRS 31, 32, 43, 67).

Access levels (SRS 43): PUBLIC, MEMBERS, LEADERS, FINANCE, ADMIN.
"""

from django.contrib.auth.models import User
from django.db import models

from core.models import SoftDeleteModel, TimeStampedModel

ACCESS_LEVELS = [
    ('PUBLIC', 'Public'),
    ('MEMBERS', 'Members only'),
    ('LEADERS', 'Leaders only'),
    ('FINANCE', 'Finance only'),
    ('ADMIN', 'Admin only'),
]


class ResourceCategory(TimeStampedModel):
    """Categories from SRS 32 (configurable, SRS 86)."""

    name = models.CharField(max_length=120, unique=True)
    name_sw = models.CharField(max_length=120, blank=True)
    group = models.CharField(max_length=40, default='LIBRARY')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['group', 'name']

    def __str__(self):
        return self.name

    @classmethod
    def seed_defaults(cls):
        defaults = [
            ('Bible Study', 'Masomo ya Bibilia', 'LIBRARY'),
            ('Leadership', 'Uongozi', 'LIBRARY'),
            ('Evangelism', 'Uinjilisti', 'LIBRARY'),
            ('Academic', 'Taaluma', 'ACADEMIC'),
            ('Career', 'Kazi', 'ACADEMIC'),
            ('Entrepreneurship', 'Ujasiriamali', 'ACADEMIC'),
            ('Policies', 'Sera', 'DOCUMENTS'),
            ('Constitution', 'Katiba', 'DOCUMENTS'),
            ('Reports', 'Taarifa', 'DOCUMENTS'),
            ('Training Materials', 'Vifaa vya Mafunzo', 'LIBRARY'),
        ]
        created = 0
        for name, name_sw, group in defaults:
            _, was_created = cls.objects.get_or_create(
                name=name, defaults={'name_sw': name_sw, 'group': group},
            )
            created += 1 if was_created else 0
        return created


class Resource(SoftDeleteModel):
    """
    A file or link in the digital library / academic hub (SRS 31, 32).

    ``resource_type`` also covers scholarships, internships, study groups and
    career opportunities from the academic hub.
    """

    TYPE_CHOICES = [
        ('DOCUMENT', 'Document'),
        ('VIDEO', 'Video'),
        ('AUDIO', 'Audio'),
        ('LINK', 'External link'),
        ('SCHOLARSHIP', 'Scholarship'),
        ('CAREER', 'Career opportunity'),
        ('INTERNSHIP', 'Internship'),
        ('STUDY_GROUP', 'Study group'),
        ('PAST_PAPER', 'Past paper'),
        ('MATERIAL', 'Study material'),
    ]

    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    resource_type = models.CharField(max_length=15, choices=TYPE_CHOICES, default='DOCUMENT')
    category = models.ForeignKey(
        ResourceCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='resources',
    )
    description = models.TextField(blank=True)
    file = models.FileField(upload_to='resources/%Y/%m/', blank=True, null=True)
    external_url = models.URLField(blank=True, default='')
    thumbnail = models.ImageField(upload_to='resources/thumbnails/', blank=True, null=True)

    access_level = models.CharField(max_length=10, choices=ACCESS_LEVELS, default='MEMBERS')
    organisation = models.CharField(max_length=200, blank=True, help_text='Scholarship / employer / host.')
    deadline = models.DateField(null=True, blank=True, help_text='Application deadline, when relevant.')
    amount = models.CharField(max_length=100, blank=True, help_text='Scholarship amount / salary, free text.')
    location = models.CharField(max_length=200, blank=True)

    author = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resources',
    )
    status = models.CharField(max_length=12, choices=[('DRAFT', 'Draft'), ('PUBLISHED', 'Published'),
                                                      ('ARCHIVED', 'Archived')], default='PUBLISHED')
    is_featured = models.BooleanField(default=False)
    download_count = models.PositiveIntegerField(default=0)
    tags = models.CharField(max_length=255, blank=True, help_text='Comma separated tags for search.')

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'access_level'])]

    def __str__(self):
        return self.title

    @property
    def is_public(self):
        return self.access_level == 'PUBLIC'

    @property
    def file_extension(self):
        if not self.file:
            return ''
        return self.file.name.rsplit('.', 1)[-1].lower() if '.' in self.file.name else ''

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify

            base = slugify(self.title) or 'resource'
            slug = base
            counter = 1
            while Resource.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                counter += 1
                slug = f'{base}-{counter}'
            self.slug = slug
        return super().save(*args, **kwargs)


class NewsArticle(SoftDeleteModel):
    """News / publications for the public website (SRS 37, 67)."""

    STATUS_CHOICES = [('DRAFT', 'Draft'), ('PUBLISHED', 'Published'),
                      ('ARCHIVED', 'Archived'), ('SCHEDULED', 'Scheduled')]

    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    excerpt = models.CharField(max_length=300, blank=True)
    body = models.TextField()
    cover_image = models.ImageField(upload_to='news/%Y/%m/', blank=True, null=True)
    author_name = models.CharField(max_length=150, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='DRAFT')
    published_at = models.DateTimeField(null=True, blank=True)
    is_featured = models.BooleanField(default=False)
    views_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-published_at', '-created_at']

    def __str__(self):
        return self.title

    @property
    def is_live(self):
        if self.status != 'PUBLISHED' or not self.published_at:
            return False
        from django.utils import timezone

        return self.published_at <= timezone.now()

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify

            base = slugify(self.title) or 'news'
            slug = base
            counter = 1
            while NewsArticle.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                counter += 1
                slug = f'{base}-{counter}'
            self.slug = slug
        if self.status == 'PUBLISHED' and self.published_at is None:
            from django.utils import timezone

            self.published_at = timezone.now()
        return super().save(*args, **kwargs)

