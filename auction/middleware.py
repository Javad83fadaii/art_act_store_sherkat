from django.core.cache import cache

from .scheduled_dispatch import dispatch_due_auction_emails


class AuctionEmailDispatchMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            return response

        if cache.add('auction-email-dispatch-lock', '1', timeout=60):
            dispatch_due_auction_emails(limit=10)

        return response
