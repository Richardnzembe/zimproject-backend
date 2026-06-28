from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from urllib.parse import urlparse
from openai import OpenAI
from rest_framework.generics import ListAPIView, DestroyAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
import logging
from .models import ChatHistory, UserAIKey
from .serializers import ChatHistorySerializer
from .utils import normalize_ordered_list_numbering
from notifications.models import Notification
from notifications.services import create_notification
from sharing.models import ShareLink, ShareMember

logger = logging.getLogger(__name__)


def _validate_ai_base_url(base_url):
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise RuntimeError("AI base URL must use HTTPS.")
    allowed_hosts = set(getattr(settings, "ALLOWED_AI_HOSTS", []))
    if parsed.hostname not in allowed_hosts:
        raise RuntimeError("AI base URL host is not allowed.")


def _resolve_api_key(request):
    user_key = UserAIKey.objects.filter(user=request.user).first()
    if user_key:
        return user_key.get_api_key(), True
    server_key = (getattr(settings, "OPENROUTER_API_KEY", None) or "").strip()
    if not server_key:
        return None, False
    return server_key, False


def _get_client(request=None):
    base_url = getattr(settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    _validate_ai_base_url(base_url)

    api_key = None
    using_user_key = False
    if request is not None and getattr(request, "user", None) and request.user.is_authenticated:
        api_key, using_user_key = _resolve_api_key(request)
    else:
        api_key = (getattr(settings, "OPENROUTER_API_KEY", None) or "").strip()

    if not api_key:
        return None
    return OpenAI(api_key=api_key, base_url=base_url), using_user_key


def _chat(messages, model=None, temperature=0.7, request=None):
    result = _get_client(request=request)
    if result is None:
        raise RuntimeError("OpenRouter API key missing")
    client, using_user_key = result

    model = model or getattr(settings, "OPENROUTER_DEFAULT_MODEL", "openai/gpt-4o-mini")
    try:
        return client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
    except Exception:
        if using_user_key:
            logger.exception("AI request failed while using user API key.")
            raise RuntimeError("Your OpenRouter API key request failed.")
        raise


def _requested_model(request):
    if request is None:
        return ""
    return (
        request.headers.get("X-OpenRouter-Model")
        or request.headers.get("x-openrouter-model")
        or ""
    ).strip()


def _chat_with_fallback(messages, temperature=0.7, request=None):
    default_model = getattr(settings, "OPENROUTER_DEFAULT_MODEL", "openai/gpt-4o-mini")
    requested_model = _requested_model(request)

    if not requested_model or requested_model.lower() == "auto":
        completion = _chat(
            messages=messages,
            model=default_model,
            temperature=temperature,
            request=request,
        )
        return completion, {
            "requested_model": "auto",
            "used_model": default_model,
            "fallback_used": False,
            "request_message": f"Request success using Auto ({default_model}).",
        }

    try:
        completion = _chat(
            messages=messages,
            model=requested_model,
            temperature=temperature,
            request=request,
        )
        return completion, {
            "requested_model": requested_model,
            "used_model": requested_model,
            "fallback_used": False,
            "request_message": f"Request success using model: {requested_model}.",
        }
    except Exception:
        logger.exception(
            "AI request failed with selected model '%s'. Falling back to default model.",
            requested_model,
        )
        completion = _chat(
            messages=messages,
            model=default_model,
            temperature=temperature,
            request=request,
        )
        return completion, {
            "requested_model": requested_model,
            "used_model": default_model,
            "fallback_used": True,
            "request_message": (
                f"Model '{requested_model}' didn't work. Replied using Auto ({default_model})."
            ),
        }


def _extract_text(completion):
    if not completion or not completion.choices:
        return ""
    return completion.choices[0].message.content or ""


def _ree_identity():
    return (
        "You are REE (Research, Explain, Elevate), the user's reasoning, research, and writing companion. "
        "Adapt to the selected mode and stay clear, practical, and accurate."
    )


def _chat_input_from_request(data):
    if not isinstance(data, dict):
        return ""

    prompt = (data.get("question") or "").strip()
    notes = (data.get("notes") or "").strip()
    topic = (data.get("project_name") or "").strip()
    details = (data.get("details") or "").strip()
    subject = (data.get("subject") or "").strip()
    level = (data.get("level") or "").strip()

    parts = []
    if prompt:
        parts.append(prompt)
    if notes and notes != prompt:
        parts.append(notes)
    if topic:
        parts.append(f"Topic: {topic}")
    if subject:
        parts.append(f"Subject: {subject}")
    if level:
        parts.append(f"Level: {level}")
    if details:
        parts.append(f"Details: {details}")
    return "\n".join(parts).strip()


def _normalize_history(raw_history, max_items=10):
    if not isinstance(raw_history, list):
        return []
    cleaned = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        cleaned.append({"role": role, "content": content.strip()})
    return cleaned[-max_items:]


def _save_history(request, mode, input_data, response_text):
    try:
        history = ChatHistory.objects.create(
            user=request.user,
            mode=mode,
            input_data=input_data,
            response_text=response_text,
        )
        return history
    except Exception:
        logger.exception("Failed to save AI chat history")
        return None


def _classify_ai_error(exc):
    msg = str(exc).lower()
    if "api key" in msg or "authentication" in msg or "unauthorized" in msg:
        return (
            "AI service authentication failed. The API key may be missing or invalid.",
            502,
        )
    if "rate" in msg and "limit" in msg:
        return (
            "AI service rate limit reached. Please wait a moment and try again.",
            429,
        )
    if "timeout" in msg or "timed out" in msg:
        return (
            "AI service took too long to respond. Please try again.",
            504,
        )
    if "model" in msg and ("not found" in msg or "not available" in msg or "does not exist" in msg):
        return (
            "The selected AI model is not available. Try switching to a different model.",
            422,
        )
    if isinstance(exc, RuntimeError):
        return (str(exc), 502)
    return (
        "AI service is temporarily unavailable. Please try again in a moment.",
        502,
    )


def _respond_to_chat_mode(request, *, mode, system_prompt, user_content, response_key="answer"):
    session_id = request.data.get("session_id")
    history = _normalize_history(request.data.get("history"))

    try:
        completion, request_meta = _chat_with_fallback(
            [
                {"role": "system", "content": system_prompt},
                *history,
                {"role": "user", "content": user_content or "Help me with this request."},
            ],
            request=request,
        )
    except Exception as exc:
        logger.exception("AI request failed")
        error_message, status_code = _classify_ai_error(exc)
        return Response({"error": error_message, "retryable": status_code in (429, 502, 504)}, status=status_code)

    response_text = normalize_ordered_list_numbering(_extract_text(completion))
    history_row = _save_history(request, mode, request.data, response_text)
    if history_row:
        _notify_shared_chat_activity(
            session_id=session_id,
            actor=request.user,
            history_id=history_row.id,
        )

    return Response(
        {
            response_key: response_text,
            "history_id": history_row.id if history_row else None,
            **request_meta,
        }
    )


def _notify_shared_chat_activity(*, session_id, actor, history_id):
    if not session_id or not actor or not history_id:
        return
    shares = ShareLink.objects.filter(
        resource_type="chat",
        session_id=session_id,
        revoked_at__isnull=True,
        expires_at__gt=timezone.now(),
    )
    if not shares.exists():
        return

    member_ids = ShareMember.objects.filter(share__in=shares).values_list("user_id", flat=True)
    recipient_ids = set(member_ids)
    recipient_ids.update(shares.values_list("created_by_id", flat=True))
    recipient_ids.discard(actor.id)
    if not recipient_ids:
        return

    payload = {
        "resource_type": "chat",
        "session_id": session_id,
        "share_tokens": [str(token) for token in shares.values_list("token", flat=True)],
    }

    recipients = User.objects.filter(id__in=recipient_ids)
    for user in recipients:
        create_notification(
            user=user,
            kind=Notification.KIND_SHARE_ACTIVITY,
            title="Shared chat updated",
            message=f"{actor.username} added a message in a shared chat.",
            data=payload,
            source_key=f"share-chat:{session_id}:{history_id}",
        )


class StudyModeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        notes = request.data.get("notes", "")
        task = request.data.get("task", "explain")  # summarize / explain / quiz
        action = request.data.get("action", "")
        session_id = request.data.get("session_id")
        if action:
            task = action

        system_prompt = (
            f"{_ree_identity()} "
            "Mode: DEEP RESEARCH. Give a structured, thorough explanation, surface important assumptions, "
            "and keep the answer easy to follow."
        )
        if task == "summarize":
            system_prompt += " Summarize the following notes clearly and concisely."
        elif task == "explain":
            system_prompt += " Explain the notes in simple, understandable terms."
        elif task == "quiz":
            system_prompt += " Create a quiz with questions and answers from these notes."
        elif task == "simplify":
            system_prompt += " Simplify the topic into very easy language."

        return _respond_to_chat_mode(
            request,
            mode="research",
            system_prompt=system_prompt,
            user_content=notes,
            response_key="result",
        )


class ResearchModeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        question = _chat_input_from_request(request.data)
        system_prompt = (
            f"{_ree_identity()} "
            "Mode: DEEP RESEARCH. Explore the request from multiple angles, explain tradeoffs, "
            "organize the answer with short section headings, and be explicit about uncertainty when needed."
        )
        return _respond_to_chat_mode(
            request,
            mode="research",
            system_prompt=system_prompt,
            user_content=question,
        )


class WritingModeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        question = _chat_input_from_request(request.data)
        system_prompt = (
            f"{_ree_identity()} "
            "Mode: WRITING. Help with drafting, rewriting, improving tone, tightening structure, "
            "and polishing clarity while preserving the user's intent."
        )
        return _respond_to_chat_mode(
            request,
            mode="writing",
            system_prompt=system_prompt,
            user_content=question,
        )


class ProjectModeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        legacy_request = _chat_input_from_request(request.data)
        system_prompt = (
            f"{_ree_identity()} "
            "Mode: DEEP RESEARCH. The request may come from a legacy project workflow. "
            "Help with planning, research direction, structure, and next steps without relying on any fixed exam framework."
        )
        return _respond_to_chat_mode(
            request,
            mode="research",
            system_prompt=system_prompt,
            user_content=legacy_request,
            response_key="project",
        )


class GeneralModeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        question = request.data.get("question", "")
        system_prompt = (
            f"{_ree_identity()} "
            "Mode: GENERAL. Provide direct, useful answers with simple explanations and minimal overhead."
        )
        return _respond_to_chat_mode(
            request,
            mode="general",
            system_prompt=system_prompt,
            user_content=question,
        )


class NotesAIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        note_content = request.data.get("note_content", "")
        action = request.data.get("action", "summarize")  # summarize / explain / understandable
        session_id = request.data.get("session_id")

        system_prompt = (
            f"{_ree_identity()} Mode: STUDY (Notes Integration). "
            "Work only with the provided note. Be concise and helpful."
        )
        if action == "summarize":
            system_prompt += " Summarize the notes concisely."
        elif action == "explain":
            system_prompt += " Explain the notes in simple, understandable terms."
        elif action == "understandable":
            system_prompt += " Rewrite the notes to make them very easy to understand."
        elif action == "questions":
            system_prompt += " Turn the notes into study questions with short answers."

        try:
            completion, request_meta = _chat_with_fallback(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": note_content},
                ],
                request=request,
            )
        except Exception as exc:
            logger.exception("AI request failed")
            error_message, status_code = _classify_ai_error(exc)
            return Response({"error": error_message, "retryable": status_code in (429, 502, 504)}, status=status_code)

        updated_text = normalize_ordered_list_numbering(_extract_text(completion))
        history = _save_history(request, "notes", request.data, updated_text)
        if history:
            _notify_shared_chat_activity(
                session_id=session_id,
                actor=request.user,
                history_id=history.id,
            )
        return Response(
            {
                "updated_note": updated_text,
                "history_id": history.id if history else None,
                **request_meta,
            }
        )


class ChatHistoryListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatHistorySerializer

    def get_queryset(self):
        return ChatHistory.objects.filter(user=self.request.user).order_by("-created_at")


class DeleteAllHistoryView(DestroyAPIView):
    """Delete all chat history for the authenticated user"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        deleted_count, _ = ChatHistory.objects.filter(user=request.user).delete()
        return Response({
            "detail": f"Successfully deleted {deleted_count} history items.",
            "deleted_count": deleted_count
        })


class DeleteHistoryItemView(DestroyAPIView):
    """Delete a single chat history item"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        history_id = kwargs.get('id')
        deleted, _ = ChatHistory.objects.filter(id=history_id, user=request.user).delete()
        if deleted:
            return Response({"detail": "History item deleted successfully."})
        return Response({"detail": "History item not found."}, status=404)


class AiApiIndexView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "detail": "AI API root",
                "endpoints": {
                    "general": "/api/ai/general/",
                    "research": "/api/ai/research/",
                    "writing": "/api/ai/writing/",
                    "notes": "/api/ai/notes/",
                    "history": "/api/ai/history/",
                    "history_delete_all": "/api/ai/history/delete-all/",
                    "user_key": "/api/ai/user-key/",
                },
            }
        )


class UserAIKeyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        key_row = UserAIKey.objects.filter(user=request.user).first()
        return Response(
            {
                "configured": bool(key_row),
                "updated_at": key_row.updated_at if key_row else None,
            }
        )

    def post(self, request):
        api_key = (request.data.get("api_key") or "").strip()
        if not api_key:
            return Response({"detail": "api_key is required."}, status=400)
        key_row, _ = UserAIKey.objects.get_or_create(user=request.user)
        key_row.set_api_key(api_key)
        key_row.save(update_fields=["encrypted_api_key", "updated_at"])
        return Response({"detail": "AI key saved.", "configured": True})

    def delete(self, request):
        UserAIKey.objects.filter(user=request.user).delete()
        return Response({"detail": "AI key removed.", "configured": False})
