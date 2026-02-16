from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Task


@override_settings(SECURE_SSL_REDIRECT=False)
class TaskApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="secret12345")
        self.other = User.objects.create_user(username="bob", password="secret12345")
        self.client.force_authenticate(self.user)

    def test_list_returns_only_owned_tasks(self):
        own = Task.objects.create(user=self.user, title="My task")
        Task.objects.create(user=self.other, title="Other task")

        res = self.client.get("/api/tasks/")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]["id"], own.id)

    def test_create_is_idempotent_by_client_id_for_same_user(self):
        payload = {
            "client_id": "abc-123",
            "title": "Initial task",
            "description": "desc",
            "priority": "high",
        }

        first = self.client.post("/api/tasks/", payload, format="json")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Task.objects.filter(user=self.user, client_id="abc-123").count(), 1)

        second = self.client.post(
            "/api/tasks/",
            {
                **payload,
                "title": "Updated title",
                "is_completed": True,
            },
            format="json",
        )

        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        task = Task.objects.get(user=self.user, client_id="abc-123")
        self.assertEqual(task.title, "Updated title")
        self.assertTrue(task.is_completed)
        self.assertEqual(Task.objects.filter(user=self.user, client_id="abc-123").count(), 1)

    def test_user_cannot_access_other_users_task(self):
        other_task = Task.objects.create(user=self.other, title="private")
        res = self.client.get(f"/api/tasks/{other_task.id}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
