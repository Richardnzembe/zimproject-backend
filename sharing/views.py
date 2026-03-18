from django.utils import timezone
from django.contrib.auth.models import User
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from ai.models import ChatHistory
from notes.models import Note
from tasks.models import Task
from .models import ShareLink, ShareMember, ShareInvite
from .serializers import (
    ShareLinkSerializer,
    ShareMemberSerializer,
    NoteSummarySerializer,
    TaskSummarySerializer,
    ShareInviteSerializer,
)
from ai.views import (
    _chat,
    _extract_text,
    _ree_identity,
)
from notifications.models import Notification
from notifications.services import create_notification


def _share_not_found():
    return Response({"detail": "Share link not found."}, status=status.HTTP_404_NOT_FOUND)


def _get_active_share(token):
    try:
        share = ShareLink.objects.get(
            token=token,
            revoked_at__isnull=True,
        )
    except ShareLink.DoesNotExist:
        return None
    if share.expires_at and share.expires_at <= timezone.now():
        return None
    return share


def _share_members_payload(share):
    members = ShareMember.objects.filter(share=share).select_related("user").order_by("added_at")
    return ShareMemberSerializer(members, many=True).data


def _notify_share_activity(*, share, actor, title, message, data=None, source_key=None):
    member_ids = ShareMember.objects.filter(share=share).values_list("user_id", flat=True)
    recipient_ids = set(member_ids)
    recipient_ids.add(share.created_by_id)
    if actor:
        recipient_ids.discard(actor.id)

    if not recipient_ids:
        return

    payload = {
        "resource_type": share.resource_type,
        "share_token": str(share.token),
        **(data or {}),
    }

    recipients = User.objects.filter(id__in=recipient_ids)
    for user in recipients:
        create_notification(
            user=user,
            kind=Notification.KIND_SHARE_ACTIVITY,
            title=title,
            message=message,
            data=payload,
            source_key=source_key,
        )


def _chat_messages_for_session(share):
    items = (
        ChatHistory.objects.filter(
            user=share.created_by,
            input_data__session_id=share.session_id,
        )
        .select_related("user")
        .order_by("created_at")
    )
    messages = []
    for item in items:
        sender_name = item.input_data.get("shared_by") or item.user.username
        sender_id = item.input_data.get("shared_by_id") or item.user_id
        messages.append(
            {
                "id": item.id,
                "role": "user",
                "content": item.input_data.get("question")
                or item.input_data.get("notes")
                or item.input_data.get("project_name")
                or "",
                "created_at": item.created_at,
                "username": sender_name,
                "user_id": sender_id,
            }
        )
        messages.append(
            {
                "id": f"{item.id}-assistant",
                "role": "assistant",
                "content": item.response_text,
                "created_at": item.created_at,
                "username": "REE AI",
            }
        )
    return messages


class ShareLinkCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        resource_type = request.data.get("resource_type")
        permission = request.data.get("permission", "read")
        session_id = request.data.get("session_id")
        note_id = request.data.get("note_id")
        task_id = request.data.get("task_id")

        if resource_type not in ("chat", "note", "task"):
            return Response({"detail": "Invalid resource_type."}, status=400)
        if permission not in ("read", "collab"):
            return Response({"detail": "Invalid permission."}, status=400)

        if resource_type == "chat":
            if not session_id:
                return Response({"detail": "session_id is required for chat."}, status=400)
            if not ChatHistory.objects.filter(user=request.user, input_data__session_id=session_id).exists():
                history_ids = request.data.get("history_ids") or []
                if history_ids:
                    histories = ChatHistory.objects.filter(user=request.user, id__in=history_ids)
                    for item in histories:
                        input_data = dict(item.input_data or {})
                        input_data["session_id"] = session_id
                        item.input_data = input_data
                        item.save(update_fields=["input_data"])
                if not ChatHistory.objects.filter(user=request.user, input_data__session_id=session_id).exists():
                    return Response({"detail": "Chat session not found."}, status=404)
            share = ShareLink.objects.filter(
                created_by=request.user,
                resource_type="chat",
                session_id=session_id,
                permission=permission,
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            ).first()
            if not share:
                share = ShareLink.objects.create(
                    created_by=request.user,
                    resource_type="chat",
                    session_id=session_id,
                    permission=permission,
                )
        elif resource_type == "note":
            if not note_id:
                return Response({"detail": "note_id is required for note."}, status=400)
            try:
                note = Note.objects.get(id=note_id, user=request.user)
            except Note.DoesNotExist:
                return Response({"detail": "Note not found."}, status=404)
            share = ShareLink.objects.filter(
                created_by=request.user,
                resource_type="note",
                note=note,
                permission=permission,
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            ).first()
            if not share:
                share = ShareLink.objects.create(
                    created_by=request.user,
                    resource_type="note",
                    note=note,
                    permission=permission,
                )
        else:
            if not task_id:
                return Response({"detail": "task_id is required for task."}, status=400)
            try:
                task = Task.objects.get(id=task_id, user=request.user)
            except Task.DoesNotExist:
                return Response({"detail": "Task not found."}, status=404)
            share = ShareLink.objects.filter(
                created_by=request.user,
                resource_type="task",
                task=task,
                permission=permission,
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            ).first()
            if not share:
                share = ShareLink.objects.create(
                    created_by=request.user,
                    resource_type="task",
                    task=task,
                    permission=permission,
                )

        data = ShareLinkSerializer(share).data
        data["members"] = _share_members_payload(share)
        return Response(data, status=201)


class ShareLinkListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        resource_type = request.query_params.get("resource_type")
        session_id = request.query_params.get("session_id")
        note_id = request.query_params.get("note_id")
        task_id = request.query_params.get("task_id")

        qs = ShareLink.objects.filter(created_by=request.user, revoked_at__isnull=True)
        if resource_type:
            qs = qs.filter(resource_type=resource_type)
        if session_id:
            qs = qs.filter(session_id=session_id)
        if note_id:
            qs = qs.filter(note_id=note_id)
        if task_id:
            qs = qs.filter(task_id=task_id)

        data = ShareLinkSerializer(qs, many=True).data
        return Response(data)


class ShareLinkDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, token):
        share = _get_active_share(token)
        if not share:
            return _share_not_found()

        if share.created_by != request.user and not ShareMember.objects.filter(share=share, user=request.user).exists():
            invite = ShareInvite.objects.filter(share=share, invited_user=request.user, status="pending").first()
            if invite:
                return Response(
                    {"detail": "Invite required.", "invite": True, "invite_id": invite.id},
                    status=status.HTTP_403_FORBIDDEN,
                )
            return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)

        payload = ShareLinkSerializer(share).data
        payload["members"] = _share_members_payload(share)

        if share.resource_type == "chat":
            payload["messages"] = _chat_messages_for_session(share)
        elif share.resource_type == "note":
            note = share.note
            payload["note"] = NoteSummarySerializer(note).data if note else None
        else:
            task = share.task
            payload["task"] = TaskSummarySerializer(task).data if task else None

        payload["owner"] = {"id": share.created_by.id, "username": share.created_by.username}
        return Response(payload)


class ShareLinkRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, token):
        share = _get_active_share(token)
        if not share or share.created_by != request.user:
            return _share_not_found()
        share.revoked_at = timezone.now()
        share.save(update_fields=["revoked_at"])
        return Response({"detail": "Share link revoked."})


class ShareMembersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, token):
        share = _get_active_share(token)
        if not share:
            return _share_not_found()

        if share.created_by != request.user and not ShareMember.objects.filter(
            share=share, user=request.user
        ).exists():
            return Response({"detail": "Not allowed."}, status=403)

        return Response(_share_members_payload(share))

    def delete(self, request, token, user_id):
        share = _get_active_share(token)
        if not share or share.created_by != request.user:
            return _share_not_found()
        ShareMember.objects.filter(share=share, user_id=user_id).delete()
        ShareInvite.objects.filter(share=share, invited_user_id=user_id).update(status="revoked", responded_at=timezone.now())
        return Response({"detail": "Member removed."})


class SharedChatView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, token):
        share = _get_active_share(token)
        if not share or share.resource_type != "chat":
            return _share_not_found()
        if share.created_by != request.user and not ShareMember.objects.filter(share=share, user=request.user).exists():
            return Response({"detail": "Not allowed."}, status=403)
        return Response({
            "messages": _chat_messages_for_session(share),
            "permission": share.permission,
        })

    def post(self, request, token):
        share = _get_active_share(token)
        if not share or share.resource_type != "chat":
            return _share_not_found()
        if share.permission != "collab":
            return Response({"detail": "Read-only share."}, status=403)
        if share.created_by != request.user and not ShareMember.objects.filter(share=share, user=request.user).exists():
            return Response({"detail": "Not allowed."}, status=403)

        message = request.data.get("message", "").strip()
        mode = (request.data.get("mode", "general") or "general").strip().lower()
        if mode in ("study", "project"):
            mode = "research"

        if not message:
            return Response({"detail": "Message is required."}, status=400)

        history_items = (
            ChatHistory.objects.filter(
                user=share.created_by,
                input_data__session_id=share.session_id,
            )
            .order_by("created_at")
        )
        history = []
        for item in history_items:
            history.append({"role": "user", "content": item.input_data.get("question") or item.input_data.get("notes") or item.input_data.get("project_name") or ""})
            history.append({"role": "assistant", "content": item.response_text})

        if mode == "research":
            system_prompt = (
                f"{_ree_identity()} "
                "Mode: DEEP RESEARCH. Explore the request from multiple angles, explain tradeoffs, "
                "and keep the answer structured and easy to follow."
            )
        elif mode == "writing":
            system_prompt = (
                f"{_ree_identity()} "
                "Mode: WRITING. Help with drafting, rewriting, improving tone, and polishing clarity."
            )
        else:
            system_prompt = (
                f"{_ree_identity()} "
                "Mode: GENERAL. Provide direct, useful answers with simple explanations and minimal overhead."
            )

        completion = _chat(
            [
                {"role": "system", "content": system_prompt},
                *history,
                {"role": "user", "content": message},
            ]
        )
        response_text = _extract_text(completion)

        history = ChatHistory.objects.create(
            user=share.created_by,
            mode=mode,
            input_data={
                "question": message,
                "session_id": share.session_id,
                "shared_by": request.user.username,
                "shared_by_id": request.user.id,
            },
            response_text=response_text,
        )

        _notify_share_activity(
            share=share,
            actor=request.user,
            title="Shared chat updated",
            message=f"{request.user.username} sent a message in a shared chat.",
            data={"session_id": share.session_id},
            source_key=f"share-chat:{share.session_id}:{history.id}",
        )

        return Response({"answer": response_text})


class SharedNoteView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, token):
        share = _get_active_share(token)
        if not share or share.resource_type != "note" or not share.note:
            return _share_not_found()
        if share.created_by != request.user and not ShareMember.objects.filter(share=share, user=request.user).exists():
            return Response({"detail": "Not allowed."}, status=403)
        note = share.note
        return Response({
            "note": NoteSummarySerializer(note).data,
            "permission": share.permission,
        })

    def put(self, request, token):
        share = _get_active_share(token)
        if not share or share.resource_type != "note" or not share.note:
            return _share_not_found()
        if share.permission != "collab":
            return Response({"detail": "Read-only share."}, status=403)
        if share.created_by != request.user and not ShareMember.objects.filter(share=share, user=request.user).exists():
            return Response({"detail": "Not allowed."}, status=403)

        note = share.note
        data = request.data or {}
        note.title = data.get("title", note.title)
        note.subject = data.get("subject", note.subject)
        note.category = data.get("category", note.category)
        note.tags = data.get("tags", note.tags)
        note.content = data.get("content", note.content)
        note.last_edited_by = request.user
        note.save()

        _notify_share_activity(
            share=share,
            actor=request.user,
            title="Shared note updated",
            message=f"{request.user.username} updated a shared note.",
            data={"note_id": note.id},
            source_key=f"share-note:{note.id}:{note.updated_at.isoformat()}",
        )

        return Response({"note": NoteSummarySerializer(note).data})


class SharedTaskView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, token):
        share = _get_active_share(token)
        if not share or share.resource_type != "task" or not share.task:
            return _share_not_found()
        if share.created_by != request.user and not ShareMember.objects.filter(share=share, user=request.user).exists():
            return Response({"detail": "Not allowed."}, status=403)
        task = share.task
        return Response({
            "task": TaskSummarySerializer(task).data,
            "permission": share.permission,
        })

    def put(self, request, token):
        share = _get_active_share(token)
        if not share or share.resource_type != "task" or not share.task:
            return _share_not_found()
        if share.permission != "collab":
            return Response({"detail": "Read-only share."}, status=403)
        if share.created_by != request.user and not ShareMember.objects.filter(share=share, user=request.user).exists():
            return Response({"detail": "Not allowed."}, status=403)

        task = share.task
        data = request.data or {}
        task.title = data.get("title", task.title)
        task.description = data.get("description", task.description)
        task.is_completed = data.get("is_completed", task.is_completed)
        task.priority = data.get("priority", task.priority)
        task.due_date = data.get("due_date", task.due_date)
        task.save()

        _notify_share_activity(
            share=share,
            actor=request.user,
            title="Shared task updated",
            message=f"{request.user.username} updated a shared task.",
            data={"task_id": task.id},
            source_key=f"share-task:{task.id}:{task.updated_at.isoformat()}",
        )

        return Response({"task": TaskSummarySerializer(task).data})


class ShareInviteCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, token):
        share = _get_active_share(token)
        if not share or share.created_by != request.user:
            return _share_not_found()

        username = (request.data.get("username") or "").strip()
        if not username:
            return Response({"detail": "username is required."}, status=400)

        try:
            invited_user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response({"detail": "User not found."}, status=404)

        if invited_user == request.user:
            return Response({"detail": "You are already the owner."}, status=400)

        ShareMember.objects.filter(share=share, user=invited_user).delete()

        invite, _ = ShareInvite.objects.get_or_create(
            share=share,
            invited_user=invited_user,
            defaults={"invited_by": request.user},
        )
        if invite.status != "pending":
            invite.status = "pending"
            invite.invited_by = request.user
            invite.responded_at = None
            invite.save(update_fields=["status", "invited_by", "responded_at"])

        create_notification(
            user=invited_user,
            kind=Notification.KIND_SHARE_INVITE,
            title="New Share Invite",
            message=f"{request.user.username} invited you to a {share.resource_type}.",
            data={
                "invite_id": invite.id,
                "resource_type": share.resource_type,
                "share_token": str(share.token),
            },
            source_key=f"share-invite:{invite.id}",
            created_at=invite.created_at,
        )

        return Response({"detail": "Invite sent.", "invite_id": invite.id})


class ShareInviteListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        invites = ShareInvite.objects.filter(invited_user=request.user, status="pending").select_related("share", "invited_by")
        return Response(ShareInviteSerializer(invites, many=True).data)


class ShareInviteActionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, invite_id):
        action = request.data.get("action")
        try:
            invite = ShareInvite.objects.select_related("share").get(id=invite_id, invited_user=request.user)
        except ShareInvite.DoesNotExist:
            return Response({"detail": "Invite not found."}, status=404)

        if invite.status != "pending":
            return Response({"detail": "Invite already handled."}, status=400)

        if action == "accept":
            ShareMember.objects.get_or_create(
                share=invite.share,
                user=request.user,
                defaults={"added_by": invite.invited_by},
            )
            invite.status = "accepted"
            invite.responded_at = timezone.now()
            invite.save(update_fields=["status", "responded_at"])
            return Response({"detail": "Invite accepted."})

        if action == "decline":
            invite.status = "declined"
            invite.responded_at = timezone.now()
            invite.save(update_fields=["status", "responded_at"])
            return Response({"detail": "Invite declined."})

        return Response({"detail": "Invalid action."}, status=400)
