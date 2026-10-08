from django.db import models
from django.contrib.auth.models import User

class Member(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='legacy_member_profile',
        null=True,
        blank=True,
        default=None,
        help_text='Legacy CASFETA profile. CZDMP membership lives in members.Member.',
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=15)
    gender = models.CharField(
        max_length=10,
        choices=[('Male', 'Male'), ('Female', 'Female')],
    )
    institution = models.CharField(max_length=150)
    profile_picture = models.ImageField(
        upload_to='profile_pictures/',
        blank=True,
        null=True,
    )
    date_joined = models.DateField(auto_now_add=True)
    branch_name = models.CharField(max_length=100)
    branch_location = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Announcement(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    posted_by = models.CharField(
        max_length=100,
        help_text="Name of the person posting the announcement"
    )

    def __str__(self):
        return self.title


class PublicOpinion(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)  # Changed from submitted_at for consistency

    def __str__(self):
        return f"Opinion from {self.user.username if self.user else 'Anonymous'}"


class Leaderboard(models.Model):
    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name='leaderboard_entries',
    )
    score = models.IntegerField(default=0)
    rank = models.IntegerField(default=0)

    class Meta:
        ordering = ['-score', 'rank']

    def __str__(self):
        return f"{self.member.first_name} {self.member.last_name} - Score: {self.score}, Rank: {self.rank}"