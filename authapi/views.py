import logging
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from .serializers import (
    RegisterSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    SetPasswordSerializer,
)

logger = logging.getLogger(__name__)


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()

        user = User.objects.filter(email__iexact=email).first()
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_url_base = getattr(settings, "PASSWORD_RESET_URL", "")
            reset_link = f"{reset_url_base}?uid={uid}&token={token}" if reset_url_base else ""

            subject = "Password reset request"
            if reset_link:
                message = (
                    "You requested a password reset. "
                    f"Use this link to set a new password: {reset_link}"
                )
            else:
                message = (
                    "You requested a password reset. "
                    "Please contact support because the reset link is not configured."
                )

            try:
                if not reset_link:
                    logger.warning("PASSWORD_RESET_URL not configured; email will omit link.")
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            except Exception:
                logger.exception("Failed to send password reset email")
                return Response(
                    {"detail": "Email service error"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        return Response(
            {"detail": "If an account exists for this email, a reset link has been sent."}
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

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
    authentication_classes = [JWTAuthentication]

    def post(self, request):
        serializer = SetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        return Response({"detail": "Password has been reset successfully."})


class DeleteUserView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

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
    authentication_classes = [JWTAuthentication]

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

    def get(self, request):
        return Response(
            {
                "detail": "Auth API root",
                "endpoints": {
                    "register": "/api/auth/register/",
                    "login": "/api/auth/login/",
                    "refresh": "/api/auth/refresh/",
                    "password_reset": "/api/auth/password-reset/",
                    "password_reset_confirm": "/api/auth/password-reset/confirm/",
                    "me": "/api/auth/me/",
                },
            }
        )
