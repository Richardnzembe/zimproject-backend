from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import CSRFCheck
from rest_framework_simplejwt.authentication import JWTAuthentication


def enforce_csrf(request):
    check = CSRFCheck(lambda req: None)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise exceptions.PermissionDenied(f"CSRF Failed: {reason}")


class CookieJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            return super().authenticate(request)

        raw_token = request.COOKIES.get(getattr(settings, "AUTH_COOKIE_ACCESS", "smart_notes_access"))
        if not raw_token:
            return None

        # Cookie-bound auth must enforce CSRF for unsafe requests.
        if request.method not in ("GET", "HEAD", "OPTIONS", "TRACE"):
            enforce_csrf(request)

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token
