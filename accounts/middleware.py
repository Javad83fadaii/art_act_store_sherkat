from django.shortcuts import redirect
from django.urls import reverse
from urllib.parse import urlencode

from .models import CustomUser


VERIFICATION_EXEMPT_PATHS = {'/39556468.txt'}


def _get_pending_verification_user(request):
    if getattr(request.user, "is_authenticated", False):
        return request.user

    user_id = str(request.session.get("_auth_user_id") or "").strip()
    if not user_id:
        return None

    try:
        user = CustomUser.objects.get(pk=user_id)
    except (CustomUser.DoesNotExist, ValueError, TypeError):
        return None

    preferred_methods = {
        str(method).strip().lower()
        for method in (getattr(user, "preferred_contact_methods", None) or [])
        if str(method).strip()
    }
    user_email = str(getattr(user, "email", "") or "").strip()
    requires_email_verification = bool(user_email) and not getattr(user, "has_verified_email", False) and (
        not preferred_methods or "email" in preferred_methods
    )
    requires_sms_verification = ("sms" in preferred_methods) and not getattr(user, "is_active", True)

    if requires_email_verification or requires_sms_verification:
        return user

    return None


class EmailVerificationRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""
        session_user = _get_pending_verification_user(request)
        if session_user is not None and not getattr(request.user, "is_authenticated", False):
            request.user = session_user

        if path.startswith("/static/") or path.startswith("/media/") or path in VERIFICATION_EXEMPT_PATHS:
            return self.get_response(request)

        user_email = str(getattr(request.user, "email", "") or "").strip()
        preferred_methods = {
            str(method).strip().lower()
            for method in (getattr(request.user, "preferred_contact_methods", None) or [])
            if str(method).strip()
        }
        requires_email_verification = bool(user_email) and not getattr(request.user, "has_verified_email", False) and (
            not preferred_methods or "email" in preferred_methods
        )

        if request.user.is_authenticated and requires_email_verification:
            if (
                path.startswith("/accounts/verification/")
                or path.startswith("/accounts/login/")
                or path.startswith("/accounts/signup/")
                or path.startswith("/accounts/logout/")
                or path.startswith("/admin/logout/")
            ):
                return self.get_response(request)

            verification_url = reverse("email_verification")
            params = urlencode({"next": request.get_full_path()})
            return redirect(f"{verification_url}?{params}")

        if request.user.is_authenticated and not getattr(request.user, "is_active", True):
            requires_sms_verification = "sms" in preferred_methods
            if requires_sms_verification:
                if (
                    path.startswith("/accounts/verification/")
                    or path.startswith("/accounts/login/")
                    or path.startswith("/accounts/signup/")
                    or path.startswith("/accounts/logout/")
                    or path.startswith("/admin/logout/")
                ):
                    return self.get_response(request)

                verification_url = reverse("sms_verification")
                params = urlencode({"next": request.get_full_path()})
                return redirect(f"{verification_url}?{params}")

        return self.get_response(request)
