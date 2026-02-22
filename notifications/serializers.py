from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "kind",
            "title",
            "message",
            "data",
            "created_at",
            "read_at",
            "is_read",
        ]

    def get_is_read(self, obj):
        return bool(obj.read_at)

