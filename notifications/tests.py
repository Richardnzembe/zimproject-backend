from datetime import timedelta

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from sharing.models import ShareInvite, ShareLink
from tasks.models import Task

from .models import Notification


@override_settings(SECURE_SSL_REDIRECT=False, NOTIFICATIONS_STUDY_REMINDER_MINUTES=90, NOTIFICATIONS_TASK_DUE_SOON_MINUTES=15)
class NotificationApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="secret12345")
        self.owner = User.objects.create_user(username="owner", password="secret12345")
        self.client.force_authenticate(self.user)

    def test_list_generates_share_task_and_study_notifications(self):
        task_due = Task.objects.create(
            user=self.user,
            title="Due now",
            due_date=timezone.now() - timedelta(minutes=2),
        )
        task_due_soon = Task.objects.create(
            user=self.user,
            title="Due soon",
            due_date=timezone.now() + timedelta(minutes=5),
        )
        share = ShareLink.objects.create(resource_type="task", task=task_due, created_by=self.owner, permission="read")
        ShareInvite.objects.create(share=share, invited_user=self.user, invited_by=self.owner, status="pending")

        res = self.client.get("/api/notifications/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("items", res.data)
        self.assertIn("unread_count", res.data)
        self.assertGreaterEqual(len(res.data["items"]), 4)

        kinds = {item["kind"] for item in res.data["items"]}
        self.assertIn(Notification.KIND_SHARE_INVITE, kinds)
        self.assertIn(Notification.KIND_TASK_DUE, kinds)
        self.assertIn(Notification.KIND_TASK_DUE_SOON, kinds)
        self.assertIn(Notification.KIND_STUDY_REMINDER, kinds)

    def test_mark_read_read_all_and_clear(self):
        note = Notification.objects.create(
            user=self.user,
            kind=Notification.KIND_SYSTEM,
            title="One",
            message="Message",
        )
        Notification.objects.create(
            user=self.user,
            kind=Notification.KIND_SYSTEM,
            title="Two",
            message="Message",
        )

        mark_one = self.client.post(f"/api/notifications/{note.id}/read/")
        self.assertEqual(mark_one.status_code, status.HTTP_200_OK)
        note.refresh_from_db()
        self.assertIsNotNone(note.read_at)

        mark_all = self.client.post("/api/notifications/read-all/")
        self.assertEqual(mark_all.status_code, status.HTTP_200_OK)
        self.assertEqual(Notification.objects.filter(user=self.user, read_at__isnull=True).count(), 0)

        clear = self.client.delete("/api/notifications/clear/")
        self.assertEqual(clear.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 0)

    def test_sync_is_idempotent_for_same_events(self):
        task = Task.objects.create(
            user=self.user,
            title="Soon",
            due_date=timezone.now() + timedelta(minutes=10),
        )
        share = ShareLink.objects.create(resource_type="task", task=task, created_by=self.owner, permission="read")
        invite = ShareInvite.objects.create(share=share, invited_user=self.user, invited_by=self.owner, status="pending")

        first = self.client.get("/api/notifications/")
        second = self.client.get("/api/notifications/")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(Notification.objects.filter(user=self.user, source_key=f"share-invite:{invite.id}").count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.user, source_key=f"task-due-soon:{task.id}").count(), 1)

