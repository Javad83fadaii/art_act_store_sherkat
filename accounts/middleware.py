from django.shortcuts import redirect
from django.urls import reverse
from urllib.parse import urlencode


class EmailVerificationRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""

        if path.startswith("/static/") or path.startswith("/media/"):
            return self.get_response(request)

        if request.user.is_authenticated and not getattr(request.user, "has_verified_email", False):
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

        return self.get_response(request)
