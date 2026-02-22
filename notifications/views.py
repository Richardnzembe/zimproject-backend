from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .serializers import NotificationSerializer
from .services import sync_notifications_for_user


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sync_notifications_for_user(request.user)

        limit_raw = request.query_params.get("limit")
        try:
            limit = int(limit_raw) if limit_raw is not None else 50
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 200))

        unread_only = request.query_params.get("unread_only") in {"1", "true", "True"}

        qs = Notification.objects.filter(user=request.user)
        if unread_only:
            qs = qs.filter(read_at__isnull=True)
        items = qs.order_by("-created_at", "-id")[:limit]
        unread_count = Notification.objects.filter(user=request.user, read_at__isnull=True).count()

        return Response(
            {
                "items": NotificationSerializer(items, many=True).data,
                "unread_count": unread_count,
            }
        )


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id):
        notification = Notification.objects.filter(user=request.user, id=notification_id).first()
        if not notification:
            return Response({"detail": "Notification not found."}, status=status.HTTP_404_NOT_FOUND)

        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])

        return Response({"detail": "Marked as read."})


class NotificationReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
        return Response({"detail": "All notifications marked as read."})


class NotificationClearView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        Notification.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

