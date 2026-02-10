from rest_framework import serializers
from django.contrib.auth.models import User
from .models import ShareLink, ShareMember, ShareInvite
from notes.models import Note


class UserSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username"]


class ShareMemberSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)

    class Meta:
        model = ShareMember
        fields = ["user", "role", "added_at"]


class ShareLinkSerializer(serializers.ModelSerializer):
    members = ShareMemberSerializer(many=True, read_only=True)

    class Meta:
        model = ShareLink
        fields = ["token", "resource_type", "session_id", "note", "permission", "created_at", "members"]


class ShareInviteSerializer(serializers.ModelSerializer):
    share = ShareLinkSerializer(read_only=True)
    invited_by = UserSummarySerializer(read_only=True)

    class Meta:
        model = ShareInvite
        fields = ["id", "share", "invited_by", "status", "created_at"]


class NoteSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Note
        fields = ["id", "title", "subject", "category", "tags", "content", "created_at"]
