import logging
import sys
import smtplib
import threading
import socket
import json
from urllib import request as urlrequest
from urllib import error as urlerror
from django.db import DatabaseError, IntegrityError
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail, get_connection
from django.middleware.csrf import get_token
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from .authentication import enforce_csrf
from .serializers import (
    RegisterSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    SetPasswordSerializer,
)

logger = logging.getLogger(__name__)

def _set_auth_cookies(response, access_token=None, refresh_token=None):
    secure = bool(getattr(settings, "AUTH_COOKIE_SECURE", True))
    samesite = getattr(settings, "AUTH_COOKIE_SAMESITE", "None")
    access_name = getattr(settings, "AUTH_COOKIE_ACCESS", "smart_notes_access")
    refresh_name = getattr(settings, "AUTH_COOKIE_REFRESH", "smart_notes_refresh")
    access_max_age = getattr(settings, "AUTH_COOKIE_ACCESS_MAX_AGE", None)
    refresh_max_age = getattr(settings, "AUTH_COOKIE_REFRESH_MAX_AGE", None)

    if access_token:
        response.set_cookie(
            access_name,
            access_token,
            httponly=True,
            secure=secure,
            samesite=samesite,
            max_age=access_max_age,
            path="/",
        )
    if refresh_token:
        response.set_cookie(
            refresh_name,
            refresh_token,
            httponly=True,
            secure=secure,
            samesite=samesite,
            max_age=refresh_max_age,
            path="/",
        )


def _clear_auth_cookies(response):
    access_name = getattr(settings, "AUTH_COOKIE_ACCESS", "smart_notes_access")
    refresh_name = getattr(settings, "AUTH_COOKIE_REFRESH", "smart_notes_refresh")
    response.delete_cookie(access_name, path="/")
    response.delete_cookie(refresh_name, path="/")


def _resolve_reset_url_base():
    explicit = (getattr(settings, "PASSWORD_RESET_URL", "") or "").strip()
    if explicit:
        return explicit

    frontend_base = (getattr(settings, "FRONTEND_BASE_URL", "") or "").strip()
    if frontend_base:
        return frontend_base

    # Safe fallback to trusted origins configured for this deployment.
    for source in (
        getattr(settings, "CSRF_TRUSTED_ORIGINS", []),
        getattr(settings, "CORS_ALLOWED_ORIGINS", []),
    ):
        for origin in source:
            if isinstance(origin, str) and origin.startswith(("http://", "https://")):
                return origin.rstrip("/")
    return ""


def _build_reset_link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    base = _resolve_reset_url_base()
    if not base:
        return ""
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}uid={uid}&token={token}"


def _email_error_detail(exc):
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "Email service timed out."
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "Email service authentication failed. Check SMTP username/password."
    if isinstance(exc, smtplib.SMTPServerDisconnected):
        return "Email service connection failed. Check SMTP host/port and TLS/SSL settings."
    if isinstance(exc, smtplib.SMTPConnectError):
        return "Email service is unreachable. Check SMTP host/port."
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "Recipient was rejected by email provider."
    if isinstance(exc, smtplib.SMTPDataError):
        return "Email provider rejected the message data."
    if isinstance(exc, smtplib.SMTPException):
        return "SMTP error while sending password reset email."
    if isinstance(exc, urlerror.HTTPError):
        return f"Email API rejected the request ({exc.code})."
    if isinstance(exc, urlerror.URLError):
        return "Email API connection failed."
    return "Email service error"


def _send_password_reset_email_via_resend(recipient, subject, message):
    api_key = (getattr(settings, "RESEND_API_KEY", "") or "").strip()
    if not api_key:
        raise ValueError("RESEND_API_KEY not configured")

    from_email = (
        (getattr(settings, "RESEND_FROM_EMAIL", "") or "").strip()
        or (getattr(settings, "DEFAULT_FROM_EMAIL", "") or "").strip()
    )
    if not from_email:
        raise ValueError("Sender email not configured")

    timeout = getattr(settings, "EMAIL_TIMEOUT", 20)
    payload = {
        "from": from_email,
        "to": [recipient],
        "subject": subject,
        "text": message,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        url="https://api.resend.com/emails",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    with urlrequest.urlopen(req, timeout=timeout) as resp:
        status_code = getattr(resp, "status", 200)
        if status_code >= 400:
            raise RuntimeError(f"Resend API returned status {status_code}")


def _send_password_reset_email(recipient, subject, message):
    try:
        # Prefer Resend HTTPS API to avoid SMTP socket timeouts in hosted environments.
        if (getattr(settings, "RESEND_API_KEY", "") or "").strip():
            _send_password_reset_email_via_resend(recipient, subject, message)
            return

        timeout = getattr(settings, "EMAIL_TIMEOUT", 20)
        connection = get_connection(timeout=timeout)
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[recipient],
            fail_silently=False,
            connection=connection,
        )
    except Exception as exc:
        logger.exception(
            "Failed to send password reset email to %s: %s",
            recipient,
            _email_error_detail(exc),
        )


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError:
            return Response(
                {"detail": "Username or email already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except DatabaseError:
            logger.exception("Database error during user registration")
            detail = (
                "Registration service is temporarily unavailable. "
                "Please retry shortly."
            )
            message = str(sys.exc_info()[1] or "").lower()
            if "network is unreachable" in message and "supabase" in message:
                detail = (
                    "Database connection failed. Use a Supabase pooler URL "
                    "(port 6543, sslmode=require) in Render environment variables."
                )
            return Response(
                {"detail": detail},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class CsrfTokenView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class CookieTokenObtainPairView(TokenObtainPairView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code != status.HTTP_200_OK:
            return response
        payload = response.data or {}
        csrf_token = get_token(request)
        _set_auth_cookies(
            response,
            access_token=payload.get("access"),
            refresh_token=payload.get("refresh"),
        )
        response.data = {"detail": "Login successful.", "csrfToken": csrf_token}
        return response


class CookieTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, *args, **kwargs):
        enforce_csrf(request)
        refresh_cookie_name = getattr(settings, "AUTH_COOKIE_REFRESH", "smart_notes_refresh")
        request_data = request.data.copy()
        if not request_data.get("refresh"):
            cookie_refresh = request.COOKIES.get(refresh_cookie_name)
            if cookie_refresh:
                request_data["refresh"] = cookie_refresh
        request._full_data = request_data

        response = super().post(request, *args, **kwargs)
        if response.status_code != status.HTTP_200_OK:
            _clear_auth_cookies(response)
            return response

        payload = response.data or {}
        csrf_token = get_token(request)
        _set_auth_cookies(
            response,
            access_token=payload.get("access"),
            refresh_token=payload.get("refresh"),
        )
        response.data = {"detail": "Token refreshed.", "csrfToken": csrf_token}
        return response


class LogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        enforce_csrf(request)
        refresh_cookie_name = getattr(settings, "AUTH_COOKIE_REFRESH", "smart_notes_refresh")
        refresh_token = request.data.get("refresh") or request.COOKIES.get(refresh_cookie_name)
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except TokenError:
                # If token is already invalid/expired, we still clear cookies.
                pass
        response = Response({"detail": "Logged out."})
        _clear_auth_cookies(response)
        return response


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()

        user = User.objects.filter(email__iexact=email).first()
        if user:
            reset_link = _build_reset_link(user)

            subject = "Password reset request"
            if reset_link:
                message = (
                    "You requested a password reset. "
                    f"Use this link to set a new password: {reset_link}"
                )
            else:
                message = (
                    "You requested a password reset. "
                    "Please contact support because reset URL configuration is missing."
                )

            if not reset_link:
                logger.error(
                    "Password reset email link not generated. Configure PASSWORD_RESET_URL or FRONTEND_BASE_URL."
                )

            # Dispatch email in a daemon thread so SMTP network hangs do not block request workers.
            thread = threading.Thread(
                target=_send_password_reset_email,
                args=(user.email, subject, message),
                daemon=True,
            )
            thread.start()

        return Response(
            {"detail": "If an account exists for this email, a reset link has been sent."}
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uid = serializer.validated_data["uid"]
        token = serializer.validated_data["token"]
        new_password = serializer.validated_data["new_password"]

        try:
            user_id = urlsafe_base64_decode(uid).decode()
            user = User.objects.get(pk=user_id)
        except Exception:
            return Response({"detail": "Invalid reset token."}, status=400)

        if not default_token_generator.check_token(user, token):
            return Response({"detail": "Invalid reset token."}, status=400)

        user.set_password(new_password)
        user.save(update_fields=["password"])

        return Response({"detail": "Password has been reset successfully."})


class SetPasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SetPasswordSerializer(data=request.data, context={"user": request.user})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        return Response({"detail": "Password has been reset successfully."})


class DeleteUserView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk=None):
        user = request.user
        if pk is not None and pk != user.id:
            return Response(
                {"detail": "You can only delete your own account."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            user.delete()
        except Exception:
            logger.exception("Failed to delete user account")
            return Response(
                {"detail": "We could not delete your account right now. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({"detail": "Account has been deleted successfully."})


class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response(
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
            }
        )


class AuthApiIndexView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response(
            {
                "detail": "Auth API root",
                "endpoints": {
                    "csrf": "/api/auth/csrf/",
                    "register": "/api/auth/register/",
                    "login": "/api/auth/login/",
                    "refresh": "/api/auth/refresh/",
                    "logout": "/api/auth/logout/",
                    "password_reset": "/api/auth/password-reset/",
                    "password_reset_confirm": "/api/auth/password-reset/confirm/",
                    "me": "/api/auth/me/",
                },
            }
        )
