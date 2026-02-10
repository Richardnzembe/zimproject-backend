import uuid
from django.db import models
from django.contrib.auth.models import User
from notes.models import Note


class ShareLink(models.Model):
    RESOURCE_CHOICES = (
        ("chat", "Chat"),
        ("note", "Note"),
    )
    PERMISSION_CHOICES = (
        ("read", "Read"),
        ("collab", "Collaborate"),
    )

    token = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resource_type = models.CharField(max_length=12, choices=RESOURCE_CHOICES)
    session_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    note = models.ForeignKey(Note, null=True, blank=True, on_delete=models.CASCADE)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="share_links")
    permission = models.CharField(max_length=12, choices=PERMISSION_CHOICES, default="read")
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["resource_type", "session_id"]),
        ]

    @property
    def is_active(self):
        return self.revoked_at is None


class ShareMember(models.Model):
    share = models.ForeignKey(ShareLink, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    added_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="added_members")
    role = models.CharField(max_length=20, default="collaborator")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["share", "user"], name="uniq_share_member")
        ]


class ShareInvite(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("declined", "Declined"),
        ("revoked", "Revoked"),
    )

    share = models.ForeignKey(ShareLink, on_delete=models.CASCADE, related_name="invites")
    invited_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="share_invites")
    invited_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_invites")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["share", "invited_user"], name="uniq_share_invite"),
        ]
