import traceback

from .models import ErrorLog


class ErrorLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            response = self.get_response(request)
        except Exception:
            self._create_error_log(request, 500, traceback.format_exc())
            raise

        if response.status_code in {400, 403, 404, 500}:
            self._create_error_log(request, response.status_code, '')

        return response

    def _create_error_log(self, request, status_code, stack_trace):
        user = getattr(request, 'user', None)
        if user is not None and not getattr(user, 'is_authenticated', False):
            user = None

        ErrorLog.objects.create(
            error_type=str(status_code),
            url=request.path,
            method=request.method,
            user=user,
            ip_address=self._get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            stack_trace=stack_trace,
            request_data={
                'GET': dict(request.GET),
                'POST': dict(request.POST),
            },
        )

    def _get_client_ip(self, request):
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR') or '127.0.0.1'
