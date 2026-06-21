from urllib.parse import urlencode
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, OuterRef, Subquery, Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import DetailView, ListView

from .models import Auction, AuctionCartItem, AuctionProduct, Bid
from .realtime import build_bid_live_payload
from .services import (
    ensure_auction_product_winner,
    ensure_products_have_finished_winners,
    has_valid_winner_access_token,
    build_winner_access_token,
)
from accounts.models import VerificationRequest, CreditIncreaseRequest  # CreditIncreaseRequest اضافه شد
from core.notification_messages import get_notification
from store.models import Artwork


def _format_seconds_as_hhmmss(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}'

def _split_seconds(total_seconds: int) -> tuple[int, int, int, int]:
    total_seconds = max(0, int(total_seconds))
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return days, hours, minutes, seconds


def _build_inactive_auction_redirect(product: AuctionProduct):
    list_url = reverse('auction:auction_products', kwargs={'pk': product.auction.pk})
    return redirect(
        f'{list_url}?{urlencode({"toast_message": get_notification("auction.inactive"), "toast_type": "warning"})}'
    )


def _has_finished_winner_profile_access(request, product: AuctionProduct, access_token: str) -> bool:
    if not getattr(request.user, 'is_authenticated', False):
        return False

    return (
        product.auction.status == 'finished'
        and product.winner_id == request.user.pk
        and has_valid_winner_access_token(
            token=access_token,
            user_id=request.user.pk,
            product_id=product.pk,
        )
    )


class AuctionListView(ListView):
    model = Auction
    template_name = 'auction/act.html'
    context_object_name = 'auctions'
    paginate_by = 12

    def get_queryset(self):
        return Auction.objects.annotate(bid_count=Count('bids')).order_by('-start_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        for auction in context.get('auctions', []):
            if auction.status == 'ready':
                target = auction.start_date
                auction.countdown_label = 'زمان باقی‌مانده تا شروع'
            elif auction.status == 'ongoing':
                target = auction.end_date
                auction.countdown_label = 'زمان باقی‌مانده تا پایان'
            else:
                target = None
                auction.countdown_label = 'مزایده به پایان رسید'

            total_seconds = (target - now).total_seconds() if target else 0
            days, hours, minutes, seconds = _split_seconds(total_seconds)

            auction.countdown_days = f'{days:02d}'
            auction.countdown_hours = f'{hours:02d}'
            auction.countdown_minutes = f'{minutes:02d}'
            auction.countdown_seconds = f'{seconds:02d}'
            auction.time_left_str = _format_seconds_as_hhmmss(total_seconds)
        context['bid_error'] = self.request.GET.get('bid_error', '')
        context['bid_success'] = self.request.GET.get('bid_success', '')
        return context


class AuctionDetailView(DetailView):
    model = Auction
    template_name = 'auction/product_auction.html'
    context_object_name = 'auction'

    def get_queryset(self):
        return Auction.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['bid_error'] = self.request.GET.get('bid_error', '')
        context['bid_success'] = self.request.GET.get('bid_success', '')
        latest_credit_request = None
        if self.request.user.is_authenticated:
            latest_credit_request = (
                CreditIncreaseRequest.objects
                .filter(user=self.request.user)
                .order_by('-updated_at', '-created_at', '-pk')
                .first()
            )
        context['latest_credit_request_status'] = (
            latest_credit_request.status if latest_credit_request is not None else ''
        )
        return context


def auction_product_detail(request, pk: int):
    product = get_object_or_404(
        AuctionProduct.objects.select_related('artist', 'artwork_type', 'auction'),
        pk=pk,
    )
    product = ensure_auction_product_winner(product)
    access_token = request.GET.get('access_token', '').strip()
    has_winner_profile_access = _has_finished_winner_profile_access(request, product, access_token)
    is_active_auction = product.auction.status == 'ongoing'

    if not is_active_auction and not has_winner_profile_access:
        if not request.user.is_authenticated and access_token:
            login_url = f'{reverse("login")}?{urlencode({"next": request.get_full_path()})}'
            return redirect(login_url)
        return _build_inactive_auction_redirect(product)

    if not request.user.is_authenticated:
        login_url = f'{reverse("login")}?{urlencode({"next": request.path})}'
        list_url = reverse('auction:auction_products', kwargs={'pk': product.auction.pk})
        return redirect(
            f'{list_url}?{urlencode({"toast_message": get_notification("auction.detail_login_required"), "toast_type": "warning", "toast_action_label": "ورود", "toast_action_href": login_url})}'
        )

    if int(getattr(request.user, 'is_verified', 0) or 0) != 1 and not has_winner_profile_access:
        list_url = reverse('auction:auction_products', kwargs={'pk': product.auction.pk})
        has_opt_in = request.user.has_pending_auction_request

        if not has_opt_in:
            edit_url = f'{reverse("edit_profile")}?{urlencode({"next": list_url})}'
            return redirect(
                f'{list_url}?{urlencode({"toast_message": get_notification("auction.enable_participation"), "toast_type": "warning", "toast_action_label": "ویرایش", "toast_action_href": edit_url})}'
            )

        return redirect(
            f'{list_url}?{urlencode({"toast_message": get_notification("auction.pending_approval"), "toast_type": "warning"})}'
        )

    # ----------------------------------
    # Query های بهینه
    # ----------------------------------

    user_bids_qs = Bid.objects.filter(
        user=request.user,
        product_id=product.product_id
    )

    my_bids = list(
        user_bids_qs
        .order_by('-created_at', '-pk')[:50]
    )

    my_bids_count = user_bids_qs.count()

    # بالاترین بید کل مزایده
    highest_auction_bid = (
        Bid.objects.filter(product_id=product.product_id)
        .aggregate(max_bid=Max('bid_amount'))
        .get('max_bid')
    )

    # بالاترین بید کاربر
    highest_user_bid = (
        user_bids_qs
        .aggregate(max_bid=Max('bid_amount'))
        .get('max_bid')
    )

    # آخرین بید کاربر
    latest_user_bid_id = (
        user_bids_qs
        .order_by('-created_at', '-pk')
        .values_list('id', flat=True)
        .first()
    )

    # ----------------------------------
    # فلگ های UI
    # ----------------------------------

    for bid in my_bids:

        # آخرین بید
        bid.is_latest = bid.id == latest_user_bid_id

        # بالاترین بید کاربر
        bid.is_user_top = highest_user_bid and bid.bid_amount == highest_user_bid

        # برنده فعلی
        bid.is_user_highest = (
            highest_user_bid
            and highest_auction_bid
            and highest_user_bid == highest_auction_bid
            and bid.bid_amount == highest_user_bid
        )

    context = {
        'auction': product,
        'has_winner_profile_access': has_winner_profile_access,
        'live_state_url': (
            f'{reverse("auction:auction_product_live_state", kwargs={"pk": product.pk})}?{urlencode({"access_token": access_token})}'
            if has_winner_profile_access and access_token
            else reverse("auction:auction_product_live_state", kwargs={"pk": product.pk})
        ),
        'my_bids': my_bids,
        'my_bids_count': my_bids_count,
        'bid_success': request.session.pop('bid_success', None),
        'bid_error': request.session.pop('bid_error', None),
        'latest_credit_request_status': (
            CreditIncreaseRequest.objects
            .filter(user=request.user)
            .order_by('-updated_at', '-created_at', '-pk')
            .values_list('status', flat=True)
            .first() or ''
        ),
    }

    context['bid_error'] = request.GET.get('bid_error', '') or context['bid_error']
    context['bid_success'] = request.GET.get('bid_success', '') or context['bid_success']

    return render(request, 'auction/product_auction.html', context)


def auction_product_live_state(request, pk: int):
    product = get_object_or_404(AuctionProduct, pk=pk)
    product = ensure_auction_product_winner(product)
    access_token = request.GET.get('access_token', '').strip()
    is_active_auction = product.auction.status == 'ongoing'
    has_winner_profile_access = _has_finished_winner_profile_access(request, product, access_token)
    if not is_active_auction and not has_winner_profile_access:
        return JsonResponse({'success': False, 'message': get_notification('auction.inactive')}, status=403)
    return JsonResponse(
        {
            'success': True,
            **build_bid_live_payload(product, request.user),
        }
    )


@login_required
def place_bid(request, pk: int):
    auction = get_object_or_404(AuctionProduct, pk=pk)
    
    # بررسی اینکه آیا درخواست از نوع AJAX (Fetch) است یا خیر
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'success': False, 'message': get_notification('common.invalid_request')}, status=400)
        return redirect('auction:auction_product_detail', pk=auction.pk)

    next_url = request.POST.get('next') or reverse('auction:auction_product_detail', kwargs={'pk': auction.pk})
    amount = request.POST.get('amount', '').strip()
    
    if int(getattr(request.user, 'is_verified', 0) or 0) != 1:
        has_opt_in = request.user.has_pending_auction_request
        if not has_opt_in:
            msg = get_notification('auction.enable_participation')
            if is_ajax:
                return JsonResponse({'success': False, 'message': msg})
                
            edit_url = f'{reverse("edit_profile")}?{urlencode({"next": next_url})}'
            return redirect(
                f'{next_url}?{urlencode({"toast_message": msg, "toast_type": "warning", "toast_action_label": "ویرایش", "toast_action_href": edit_url})}'
            )
            
        msg_pending = get_notification('auction.pending_approval')
        if is_ajax:
            return JsonResponse({'success': False, 'message': msg_pending})
        return redirect(
            f'{next_url}?{urlencode({"toast_message": msg_pending, "toast_type": "warning"})}'
        )

    raw = (amount or "").strip() if isinstance(amount, str) else amount
    try:
        new_bid_amount = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        new_bid_amount = None

    if new_bid_amount is not None:
        credit = request.user.calculate_current_credit()

        current_cart_item = (
            AuctionCartItem.objects
            .filter(product=auction, is_active=True)
            .select_related('user')
            .first()
        )
        previous_reserved = Decimal("0")
        if current_cart_item and current_cart_item.user_id == request.user.pk:
            previous_reserved = Decimal(str(current_cart_item.reserved_amount or 0))

        additional_required = new_bid_amount - previous_reserved

        if additional_required > credit:
            pending_credit_request = CreditIncreaseRequest.objects.filter(
                user=request.user,
                status=CreditIncreaseRequest.RequestStatus.PENDING,
            ).exists()
            credit_request_state = "pending" if pending_credit_request else "request"
            msg_credit = (
                get_notification('auction.credit_request_pending')
                if pending_credit_request else
                get_notification('auction.credit_request_needed')
            )
            if is_ajax:
                return JsonResponse(
                    {
                        "success": False, 
                        "message": msg_credit,
                        "needs_credit_increase": True,
                        "credit_request_state": credit_request_state,
                    },
                    status=400,
                )
            
            toast_payload = {"toast_message": msg_credit, "toast_type": "error"}
            if not pending_credit_request:
                credit_url = reverse("credit_increase_requests")
                toast_payload.update({
                    "toast_action_label": "درخواست افزایش اعتبار",
                    "toast_action_href": credit_url,
                })
            return redirect(
                f'{next_url}?{urlencode(toast_payload)}'
            )

    try:
        auction.place_bid(request.user, amount)
    except ValidationError as exc:
        message = exc.messages[0] if getattr(exc, 'messages', None) else str(exc)
        if is_ajax:
            return JsonResponse({'success': False, 'message': message})
        return redirect(f'{next_url}?{urlencode({"toast_message": message, "toast_type": "error"})}')

    if is_ajax:
        auction.refresh_from_db()
        return JsonResponse(
            {
                'success': True,
                'message': get_notification('auction.bid_success_ajax'),
                **build_bid_live_payload(auction, request.user),
            }
        )

    return redirect(
        f'{next_url}?{urlencode({"toast_message": get_notification("auction.bid_success_redirect"), "toast_type": "success"})}'
    )


class AuctionGridView(ListView):
    model = Auction
    template_name = 'auction/auction.html'
    context_object_name = 'auctions'
    paginate_by = 12

    def get_queryset(self):
        return Auction.objects.annotate(bid_count=Count('bids')).order_by('-start_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        for auction in context.get('auctions', []):
            if auction.status == 'ready':
                target = auction.start_date
                auction.countdown_label = 'زمان باقی‌مانده تا شروع'
            elif auction.status == 'ongoing':
                target = auction.end_date
                auction.countdown_label = 'زمان باقی‌مانده تا پایان'
            else:
                target = None
                auction.countdown_label = 'مزایده به پایان رسید'

            total_seconds = (target - now).total_seconds() if target else 0
            days, hours, minutes, seconds = _split_seconds(total_seconds)

            auction.countdown_days = f'{days:02d}'
            auction.countdown_hours = f'{hours:02d}'
            auction.countdown_minutes = f'{minutes:02d}'
            auction.countdown_seconds = f'{seconds:02d}'
            auction.time_left_str = _format_seconds_as_hhmmss(total_seconds)
        context['bid_error'] = self.request.GET.get('bid_error', '')
        context['bid_success'] = self.request.GET.get('bid_success', '')
        return context


class AuctionProductsView(ListView):
    model = AuctionProduct
    template_name = 'auction/auction.html'
    context_object_name = 'products'
    paginate_by = 12

    def dispatch(self, request, *args, **kwargs):
        self.auction = get_object_or_404(Auction, pk=kwargs.get('pk'))
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        artwork_pk = Artwork.objects.filter(product_id=OuterRef('product_id')).values('pk')[:1]
        return (
            AuctionProduct.objects.filter(auction=self.auction)
            .select_related('artist', 'artwork_type', 'auction')
            .annotate(bid_count=Count('bids'))
            .annotate(artwork_pk=Subquery(artwork_pk))
            .order_by('-created_at')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ensure_products_have_finished_winners(context.get('object_list'))
        products = list(context.get('object_list') or [])
        if self.request.user.is_authenticated:
            for product in products:
                if (
                    getattr(product, 'auction', None) is not None
                    and product.auction.status == 'finished'
                    and product.winner_id == self.request.user.pk
                ):
                    product.detail_access_token = build_winner_access_token(
                        user_id=self.request.user.pk,
                        product_id=product.pk,
                    )
        context['auction'] = self.auction
        context['bid_error'] = self.request.GET.get('bid_error', '')
        context['bid_success'] = self.request.GET.get('bid_success', '')
        latest_credit_request = None
        if self.request.user.is_authenticated:
            latest_credit_request = (
                CreditIncreaseRequest.objects
                .filter(user=self.request.user)
                .order_by('-updated_at', '-created_at', '-pk')
                .first()
            )
        context['latest_credit_request_status'] = (
            latest_credit_request.status if latest_credit_request is not None else ''
        )
        return context

# ----------------------------------------------------
# ویو جدید برای ثبت درخواست افزایش اعتبار از طریق AJAX
# ----------------------------------------------------
@login_required
def submit_credit_increase_ajax(request):
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    
    if request.method == 'POST' and is_ajax:
        user_model = get_user_model()
        pending_request = CreditIncreaseRequest.objects.filter(
            user=request.user,
            status=CreditIncreaseRequest.RequestStatus.PENDING,
        ).first()

        profile_url = reverse('profile')

        if pending_request:
            return JsonResponse({
                'success': True,
                'already_pending': True,
                'message': get_notification('auction.credit_request_pending_exists'),
                'profile_url': profile_url,
            })

        current_credit = request.user.calculate_current_credit()
        
        CreditIncreaseRequest.objects.create(
            user=request.user,
            current_credit=current_credit
        )
        
        return JsonResponse({
            'success': True,
            'message': get_notification('auction.credit_request_created'),
            'profile_url': profile_url
        })
        
    return JsonResponse({'success': False, 'message': get_notification('common.invalid_request')}, status=400)
