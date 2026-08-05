from django.shortcuts import redirect
from django.urls import reverse
from urllib.parse import urlencode


VERIFICATION_EXEMPT_PATHS = {'/39556468.txt'}


class EmailVerificationRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""

        if path.startswith("/static/") or path.startswith("/media/") or path in VERIFICATION_EXEMPT_PATHS:
            return self.get_response(request)

        user_email = str(getattr(request.user, "email", "") or "").strip()
        if request.user.is_authenticated and user_email and not getattr(request.user, "has_verified_email", False):
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
            preferred_methods = {
                str(method).strip().lower()
                for method in (getattr(request.user, "preferred_contact_methods", None) or [])
                if str(method).strip()
            }
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
