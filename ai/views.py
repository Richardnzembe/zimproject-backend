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
        "You are REE (Research, Explain, Elevate), the user's study, project, and exam companion. "
        "You must follow the selected mode rules strictly."
    )


def _is_project_request(text):
    if not text:
        return False
    lowered = text.lower()
    keywords = ["project", "zimsec", "proposal", "title page", "abstract", "literature review", "methodology"]
    return any(k in lowered for k in keywords)


def _project_formatting_rules():
    return (
        "Formatting rules (Project Mode only): A4 paper, Times New Roman, font size 12, "
        "line spacing 1.5, margins: left 1.5\", right 1\", top 1\", bottom 1\"."
    )


def _project_template():
    return (
        "Use ONLY the Standard ZIMSEC Project Framework and report structure. "
        "Include all mandatory stages and headings.\n"
        "Mandatory stages (include in order with typical marks):\n"
        "1) Problem Identification (5 marks)\n"
        "2) Investigation of Ideas (10 marks)\n"
        "3) Generation of Ideas (10 marks)\n"
        "4) Development/Refinement (10 marks)\n"
        "5) Presentation of Results (10 marks)\n"
        "6) Evaluation & Recommendations (5 marks)\n"
        "General report structure (use these formal headings):\n"
        "Title Page\n"
        "Table of Contents\n"
        "Introduction\n"
        "Research Methodology\n"
        "Findings & Analysis\n"
        "Appendices"
    )


def _project_subject_rules(subject):
    subject_lower = (subject or "").lower()
    if "science" in subject_lower:
        return (
            "Science/Geography: expand Research Methodology and Findings & Analysis with clear "
            "environmental or experimental evidence. Use the 6 stages."
        )
    if "math" in subject_lower:
        return (
            "Mathematics: include relevant calculations, formulas, and worked examples tied to "
            "real-life data (profits, surveys, measurements, modeling)."
        )
    if "computer" in subject_lower or "ict" in subject_lower:
        return (
            "Computer Science/ICT (4021): include system analysis approach with Section A "
            "(Investigation), Section B (Design), Section C (Development), and Section D "
            "(Testing/Evaluation)."
        )
    if "english" in subject_lower or "shona" in subject_lower:
        return (
            "Languages: focus on communication strategies, literacy improvements, or cultural "
            "preservation as appropriate."
        )
    if "heritage" in subject_lower:
        return "Include local history, culture, traditions, and community knowledge."
    return ""


def _originality_rules():
    return (
        "Originality and safety rules: Never copy content directly. Rewrite everything originally. "
        "Localize examples. Avoid plagiarism. Match ZIMSEC expectations."
    )


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
        history = _normalize_history(request.data.get("history"))

        system_prompt = (
            f"{_ree_identity()} "
            "Mode: STUDY. Behave Socratically: ask guiding questions, explain step-by-step, "
            "and break content into small chunks."
        )
        if task == "summarize":
            system_prompt += " Summarize the following notes clearly and concisely."
        elif task == "explain":
            system_prompt += " Explain the notes in simple, understandable terms."
        elif task == "quiz":
            system_prompt += " Create a quiz with questions and answers from these notes."
        elif task == "simplify":
            system_prompt += " Simplify the topic into very easy language."

        try:
            completion, request_meta = _chat_with_fallback(
                [
                    {"role": "system", "content": system_prompt},
                    *history,
                    {"role": "user", "content": notes},
                ],
                request=request,
            )
        except Exception:
            logger.exception("AI request failed")
            return Response({"error": "AI service error"}, status=502)

        result_text = _extract_text(completion)
        history = _save_history(request, "study", request.data, result_text)
        if history:
            _notify_shared_chat_activity(
                session_id=session_id,
                actor=request.user,
                history_id=history.id,
            )
        return Response(
            {
                "result": result_text,
                "history_id": history.id if history else None,
                **request_meta,
            }
        )


class ProjectModeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        mode = request.data.get("mode", "guided")  # guided / fast
        project_name = request.data.get("project_name", "")
        details = request.data.get("details", "")
        subject = request.data.get("subject", "")
        level = request.data.get("level", "")
        session_id = request.data.get("session_id")
        history = _normalize_history(request.data.get("history"))

        if mode == "guided":
            prompt = (
                "Guided Project Mode: ask step-by-step questions to build the project. "
                "Ask for subject, topic, and school level if missing. "
                "Build each section with the student."
            )
        else:
            prompt = (
                "Fast Project Mode: generate a complete project using the ZIMSEC template. "
                "If the user says 'do everything' or topic is missing, choose a suitable topic yourself. "
                "Use subject-specific rules. Localize examples. Examiner-safe language."
            )

        subject_rules = _project_subject_rules(subject)

        user_context = []
        if project_name:
            user_context.append(f"Project topic: {project_name}")
        if subject:
            user_context.append(f"Subject: {subject}")
        if level:
            user_context.append(f"School level: {level}")
        if details:
            user_context.append(f"Additional info: {details}")

        try:
            completion, request_meta = _chat_with_fallback(
                [
                    {
                        "role": "system",
                        "content": (
                            f"{_ree_identity()} "
                            "Mode: PROJECT (ZIMSEC). "
                            f"{_project_template()} "
                            f"{_project_formatting_rules()} "
                            f"{_originality_rules()} "
                            f"{subject_rules}"
                        ),
                    },
                    *history,
                    {"role": "user", "content": prompt},
                    {"role": "user", "content": "\n".join(user_context) if user_context else "No extra context provided."},
                ],
                request=request,
            )
        except Exception:
            logger.exception("AI request failed")
            return Response({"error": "AI service error"}, status=502)

        project_text = _extract_text(completion)
        history = _save_history(request, "project", request.data, project_text)
        if history:
            _notify_shared_chat_activity(
                session_id=session_id,
                actor=request.user,
                history_id=history.id,
            )
        return Response(
            {
                "project": project_text,
                "history_id": history.id if history else None,
                **request_meta,
            }
        )


class GeneralModeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        question = request.data.get("question", "")
        session_id = request.data.get("session_id")
        history = _normalize_history(request.data.get("history"))
        if _is_project_request(question):
            return Response(
                {
                    "answer": (
                        "This looks like a project request. Please switch to Project Mode so I can use the "
                        "ZIMSEC template and subject-specific rules."
                    )
                }
            )
        try:
            completion, request_meta = _chat_with_fallback(
                [
                    {
                        "role": "system",
                        "content": (
                            f"{_ree_identity()} "
                            "Mode: GENERAL. Provide direct answers with simple explanations. "
                            "Ask a brief follow-up question if needed."
                        ),
                    },
                    *history,
                    {"role": "user", "content": question},
                ],
                request=request,
            )
        except Exception:
            logger.exception("AI request failed")
            return Response({"error": "AI service error"}, status=502)

        answer_text = _extract_text(completion)
        history = _save_history(request, "general", request.data, answer_text)
        if history:
            _notify_shared_chat_activity(
                session_id=session_id,
                actor=request.user,
                history_id=history.id,
            )
        return Response(
            {
                "answer": answer_text,
                "history_id": history.id if history else None,
                **request_meta,
            }
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
        except Exception:
            logger.exception("AI request failed")
            return Response({"error": "AI service error"}, status=502)

        updated_text = _extract_text(completion)
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
                    "study": "/api/ai/study/",
                    "project": "/api/ai/project/",
                    "general": "/api/ai/general/",
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
