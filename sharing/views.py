from django.utils import timezone
from django.contrib.auth.models import User
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from ai.models import ChatHistory
from notes.models import Note
from .models import ShareLink, ShareMember, ShareInvite
from .serializers import ShareLinkSerializer, ShareMemberSerializer, NoteSummarySerializer, ShareInviteSerializer
from ai.views import (
    _chat,
    _extract_text,
    _ree_identity,
    _project_template,
    _project_formatting_rules,
    _originality_rules,
    _project_subject_rules,
)


def _share_not_found():
    return Response({"detail": "Share link not found."}, status=status.HTTP_404_NOT_FOUND)


def _get_active_share(token):
    try:
        share = ShareLink.objects.get(token=token, revoked_at__isnull=True)
    except ShareLink.DoesNotExist:
        return None
    return share


def _share_members_payload(share):
    members = ShareMember.objects.filter(share=share).select_related("user").order_by("added_at")
    return ShareMemberSerializer(members, many=True).data


def _chat_messages_for_session(session_id):
    items = (
        ChatHistory.objects.filter(input_data__session_id=session_id)
        .select_related("user")
        .order_by("created_at")
    )
    messages = []
    for item in items:
        messages.append(
            {
                "id": item.id,
                "role": "user",
                "content": item.input_data.get("question")
                or item.input_data.get("notes")
                or item.input_data.get("project_name")
                or "",
                "created_at": item.created_at,
                "username": item.user.username,
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

        if resource_type not in ("chat", "note"):
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
            ).first()
            if not share:
                share = ShareLink.objects.create(
                    created_by=request.user,
                    resource_type="chat",
                    session_id=session_id,
                    permission=permission,
                )
        else:
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
            ).first()
            if not share:
                share = ShareLink.objects.create(
                    created_by=request.user,
                    resource_type="note",
                    note=note,
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

        qs = ShareLink.objects.filter(created_by=request.user, revoked_at__isnull=True)
        if resource_type:
            qs = qs.filter(resource_type=resource_type)
        if session_id:
            qs = qs.filter(session_id=session_id)
        if note_id:
            qs = qs.filter(note_id=note_id)

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
            payload["messages"] = _chat_messages_for_session(share.session_id)
        else:
            note = share.note
            payload["note"] = NoteSummarySerializer(note).data if note else None

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
            "messages": _chat_messages_for_session(share.session_id),
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
        mode = request.data.get("mode", "general")
        subject = request.data.get("subject", "")
        project_mode = request.data.get("project_mode", "guided")

        if not message:
            return Response({"detail": "Message is required."}, status=400)

        history_items = (
            ChatHistory.objects.filter(input_data__session_id=share.session_id)
            .order_by("created_at")
        )
        history = []
        for item in history_items:
            history.append({"role": "user", "content": item.input_data.get("question") or item.input_data.get("notes") or item.input_data.get("project_name") or ""})
            history.append({"role": "assistant", "content": item.response_text})

        if mode == "study":
            system_prompt = (
                f"{_ree_identity()} "
                "Mode: STUDY. Behave Socratically: ask guiding questions, explain step-by-step, "
                "and break content into small chunks. Explain the notes in simple, understandable terms."
            )
        elif mode == "project":
            subject_rules = _project_subject_rules(subject)
            prompt = (
                "Guided Project Mode: ask step-by-step questions to build the project. "
                "Ask for subject, topic, and school level if missing. "
                "Build each section with the student."
            )
            if project_mode != "guided":
                prompt = (
                    "Fast Project Mode: generate a complete project using the ZIMSEC template. "
                    "If the user says 'do everything' or topic is missing, choose a suitable topic yourself. "
                    "Use subject-specific rules. Localize examples. Examiner-safe language."
                )
            system_prompt = (
                f"{_ree_identity()} "
                "Mode: PROJECT (ZIMSEC). "
                f"{_project_template()} "
                f"{_project_formatting_rules()} "
                f"{_originality_rules()} "
                f"{subject_rules}"
            )
            history.append({"role": "user", "content": prompt})
        else:
            system_prompt = (
                f"{_ree_identity()} "
                "Mode: GENERAL. Provide direct answers with simple explanations. "
                "Ask a brief follow-up question if needed."
            )

        completion = _chat(
            [
                {"role": "system", "content": system_prompt},
                *history,
                {"role": "user", "content": message},
            ]
        )
        response_text = _extract_text(completion)

        ChatHistory.objects.create(
            user=request.user,
            mode=mode,
            input_data={"question": message, "session_id": share.session_id},
            response_text=response_text,
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
        note.save()

        return Response({"note": NoteSummarySerializer(note).data})


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
