from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from sharing.models import ShareLink, ShareMember
from tasks.models import Task
from notifications.models import Notification


@override_settings(SECURE_SSL_REDIRECT=False)
class TaskSharingTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="secret12345")
        self.collaborator = User.objects.create_user(username="collab", password="secret12345")
        self.other = User.objects.create_user(username="other", password="secret12345")
        self.task = Task.objects.create(user=self.owner, title="Owner task")

    def test_owner_can_create_task_share_link(self):
        self.client.force_authenticate(self.owner)
        res = self.client.post(
            "/api/share/links/create/",
            {"resource_type": "task", "task_id": self.task.id, "permission": "read"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["resource_type"], "task")
        self.assertEqual(str(res.data["task"]), str(self.task.id))

    def test_user_cannot_create_share_for_someone_else_task(self):
        self.client.force_authenticate(self.other)
        res = self.client.post(
            "/api/share/links/create/",
            {"resource_type": "task", "task_id": self.task.id, "permission": "read"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_collaborator_can_update_shared_task(self):
        share = ShareLink.objects.create(
            resource_type="task",
            task=self.task,
            permission="collab",
            created_by=self.owner,
        )
        ShareMember.objects.create(share=share, user=self.collaborator, added_by=self.owner)

        self.client.force_authenticate(self.collaborator)
        res = self.client.put(
            f"/api/share/links/{share.token}/task/",
            {
                "title": "Updated by collaborator",
                "description": "Shared edit",
                "is_completed": True,
                "priority": "high",
            },
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Updated by collaborator")
        self.assertTrue(self.task.is_completed)
        self.assertEqual(self.task.priority, "high")

    def test_invite_creates_recipient_notification(self):
        share = ShareLink.objects.create(
            resource_type="task",
            task=self.task,
            permission="read",
            created_by=self.owner,
        )
        self.client.force_authenticate(self.owner)
        res = self.client.post(
            f"/api/share/links/{share.token}/invite/",
            {"username": self.collaborator.username},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(
            Notification.objects.filter(
                user=self.collaborator,
                kind=Notification.KIND_SHARE_INVITE,
            ).exists()
        )
