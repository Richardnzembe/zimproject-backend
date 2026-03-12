from django.utils import timezone
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from django.contrib.auth.models import User
from notifications.models import Notification
from notifications.services import create_notification
from sharing.models import ShareLink, ShareMember
from .models import Note
from .serializers import NoteSerializer


def _notify_note_share_members(note, actor):
    shares = ShareLink.objects.filter(
        resource_type="note",
        note=note,
        revoked_at__isnull=True,
        expires_at__gt=timezone.now(),
    )
    if not shares.exists():
        return

    member_ids = ShareMember.objects.filter(share__in=shares).values_list("user_id", flat=True)
    recipient_ids = set(member_ids)
    recipient_ids.add(note.user_id)
    if actor:
        recipient_ids.discard(actor.id)

    if not recipient_ids:
        return

    share_tokens = [str(token) for token in shares.values_list("token", flat=True)]
    payload = {
        "resource_type": "note",
        "note_id": note.id,
        "share_tokens": share_tokens,
    }

    recipients = User.objects.filter(id__in=recipient_ids)
    for user in recipients:
        create_notification(
            user=user,
            kind=Notification.KIND_SHARE_ACTIVITY,
            title="Shared note updated",
            message=f"{actor.username} updated a shared note.",
            data=payload,
            source_key=f"share-note:{note.id}:{note.updated_at.isoformat()}",
        )


class NoteListCreateView(generics.ListCreateAPIView):
    serializer_class = NoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Note.objects.filter(user=self.request.user).order_by("-updated_at", "-created_at")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, last_edited_by=self.request.user)


class NoteDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = NoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Note.objects.filter(user=self.request.user)

    def perform_update(self, serializer):
        # Extra security: verify the note belongs to the current user
        if serializer.instance.user != self.request.user:
            raise PermissionDenied("You do not have permission to edit this note.")
        note = serializer.save(last_edited_by=self.request.user)
        _notify_note_share_members(note, self.request.user)

    def perform_destroy(self, instance):
        # Extra security: verify the note belongs to the current user
        if instance.user != self.request.user:
            raise PermissionDenied("You do not have permission to delete this note.")
        instance.delete()
