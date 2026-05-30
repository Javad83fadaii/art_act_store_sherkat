import uuid
import json
import requests
import os
import logging
import datetime
import threading
import pytz
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, View
from django.http import JsonResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import timezone
from core.notification_messages import get_notification
from core.utils import send_admin_notification, invalidate_cache
from .models import Artwork, ArtworkType, ProductLike, TelegramPurchaseRequest, PurchaseHistory, SiteVisitLog

logger = logging.getLogger(__name__)

# --- تنظیمات تلگرام ---
BOT_TOKEN = (
    getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    or getattr(settings, 'BOT_TOKEN', None)
    or os.environ.get('TELEGRAM_BOT_TOKEN')
    or os.environ.get('BOT_TOKEN')
)
ADMIN_GROUP_CHAT_ID = (
    getattr(settings, 'ADMIN_GROUP_CHAT_ID', None)
    or getattr(settings, 'TELEGRAM_CHAT_ID', None)
    or os.environ.get('TELEGRAM_CHAT_ID')
)
try:
    ADMIN_GROUP_CHAT_ID = int(ADMIN_GROUP_CHAT_ID)
except (TypeError, ValueError):
    ADMIN_GROUP_CHAT_ID = None

_raw_message_thread_id = (
    getattr(settings, "TELEGRAM_STORE_MESSAGE_THREAD_ID", None)
    or getattr(settings, "TELEGRAM_MESSAGE_THREAD_ID", None)
    or os.environ.get("TELEGRAM_STORE_MESSAGE_THREAD_ID")
    or os.environ.get("TELEGRAM_MESSAGE_THREAD_ID")
    or 9
)
try:
    MESSAGE_THREAD_ID = int(_raw_message_thread_id)
except (TypeError, ValueError):
    MESSAGE_THREAD_ID = None

TELEGRAM_WEBHOOK_SECRET_TOKEN = (
    getattr(settings, 'TELEGRAM_WEBHOOK_SECRET_TOKEN', None)
    or os.environ.get('TELEGRAM_WEBHOOK_SECRET_TOKEN')
)

def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621

    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )

    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365

    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd

def _jalali_datetime_str(dt: datetime.datetime) -> str:
    tehran_tz = pytz.timezone("Asia/Tehran")
    dt_local = dt.astimezone(tehran_tz)
    jy, jm, jd = _gregorian_to_jalali(dt_local.year, dt_local.month, dt_local.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d} {dt_local:%H:%M:%S}"


def _telegram_api_post(method: str, payload: dict, *, timeout: int = 8) -> bool:
    if not (BOT_TOKEN and ADMIN_GROUP_CHAT_ID):
        logger.warning(
            "Telegram config missing: BOT_TOKEN=%s ADMIN_GROUP_CHAT_ID=%s",
            bool(BOT_TOKEN),
            bool(ADMIN_GROUP_CHAT_ID),
        )
        return False

    telegram_api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        resp = requests.post(telegram_api_url, json=payload, timeout=timeout)
        if resp.status_code >= 400:
            logger.warning(
                "Telegram %s failed: status=%s body=%s",
                method,
                resp.status_code,
                resp.text[:300],
            )
            return False

        logger.info("Telegram %s ok", method)
        return True
    except Exception:
        logger.exception("Telegram %s exception", method)
        return False


def _build_purchase_request_reply_markup(purchase_request_id: int) -> dict:
    return {
        'inline_keyboard': [[
            {
                'text': 'تایید خرید',
                'callback_data': f'purchase:approve:{purchase_request_id}',
            },
            {
                'text': 'رد درخواست',
                'callback_data': f'purchase:reject:{purchase_request_id}',
            },
        ]]
    }


def _send_telegram_purchase_message(
    message_text: str,
    *,
    purchase_request_id: int | None = None,
    chat_id: int | None = None,
    thread_id: int | None = None,
) -> bool:
    payload = {
        'chat_id': chat_id or ADMIN_GROUP_CHAT_ID,
        'text': message_text,
        'parse_mode': 'HTML',
    }

    effective_thread_id = MESSAGE_THREAD_ID if thread_id is None else thread_id
    if effective_thread_id:
        payload['message_thread_id'] = effective_thread_id

    if purchase_request_id is not None:
        payload['reply_markup'] = _build_purchase_request_reply_markup(purchase_request_id)

    return _telegram_api_post('sendMessage', payload)


def _answer_telegram_callback(callback_query_id: str, text: str, *, show_alert: bool = False) -> None:
    _telegram_api_post(
        'answerCallbackQuery',
        {
            'callback_query_id': callback_query_id,
            'text': text[:180],
            'show_alert': show_alert,
        },
    )


def _remove_telegram_message_buttons(chat_id: int, message_id: int) -> None:
    _telegram_api_post(
        'editMessageReplyMarkup',
        {
            'chat_id': chat_id,
            'message_id': message_id,
            'reply_markup': {'inline_keyboard': []},
        },
    )


def _purchase_status_label(status: str) -> str:
    labels = {
        'pending': 'در انتظار',
        'confirmed': 'تایید شده',
        'rejected': 'رد شده',
        'contacted': 'تماس گرفته شد',
        'approved': 'تایید شده',
    }
    return labels.get((status or '').lower(), 'نامشخص')


def _process_telegram_purchase_action(*, purchase_request_id: int, action: str) -> tuple[bool, str, TelegramPurchaseRequest | None]:
    try:
        purchase_request = (
            TelegramPurchaseRequest.objects
            .select_for_update()
            .select_related('user', 'artwork')
            .get(pk=purchase_request_id)
        )
    except TelegramPurchaseRequest.DoesNotExist:
        return False, 'درخواست خرید پیدا نشد.', None

    current_status = (purchase_request.status or '').lower()
    if current_status != 'pending':
        return False, f'این درخواست قبلا {_purchase_status_label(current_status)} شده است.', purchase_request

    artwork = purchase_request.artwork
    if action == 'approve':
        if artwork:
            artwork.is_sold = Artwork.IsSoldStatus.SOLD
            artwork.save(update_fields=['is_sold', 'updated_at'])
        purchase_request.status = 'confirmed'
        purchase_request.save(update_fields=['status', 'updated_at'])
        return True, 'درخواست خرید تایید شد.', purchase_request

    if action == 'reject':
        purchase_request.status = 'rejected'
        purchase_request.save(update_fields=['status', 'updated_at'])
        if artwork:
            artwork.is_sold = Artwork.IsSoldStatus.AVAILABLE
            artwork.save(update_fields=['is_sold', 'updated_at'])
        return True, 'درخواست خرید رد شد.', purchase_request

    return False, 'عملیات نامعتبر است.', purchase_request


def _handle_purchase_request_side_effects_async(
    *,
    artwork_title: str,
    purchase_request_id: int,
    user_id: int,
    artwork_id: int,
    message_text: str,
) -> None:
    def runner() -> None:
        try:
            send_admin_notification(
                notification_type='purchase_request',
                title='درخواست جدید خرید',
                message=f'یک درخواست خرید جدید برای «{artwork_title}» ثبت شد.',
                data={
                    'request_type': 'purchase',
                    'id': purchase_request_id,
                    'user_id': user_id,
                    'artwork_id': artwork_id,
                },
            )
        except Exception:
            logger.exception("Admin notification exception")

        _send_telegram_purchase_message(
            message_text,
            purchase_request_id=purchase_request_id,
        )

    # تمام کارهای جانبی پس از ثبت سفارش در پس‌زمینه انجام می‌شوند.
    threading.Thread(target=runner, daemon=True).start()


@csrf_exempt
@require_POST
def telegram_purchase_webhook(request):
    if TELEGRAM_WEBHOOK_SECRET_TOKEN:
        provided_secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
        if provided_secret != TELEGRAM_WEBHOOK_SECRET_TOKEN:
            return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'error': 'invalid payload'}, status=400)

    callback_query = payload.get('callback_query') or {}
    if not callback_query:
        return JsonResponse({'ok': True})

    callback_query_id = callback_query.get('id')
    callback_data = (callback_query.get('data') or '').strip()
    message = callback_query.get('message') or {}
    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    message_id = message.get('message_id')
    message_thread_id = message.get('message_thread_id')
    actor = callback_query.get('from') or {}
    actor_name = (
        actor.get('username')
        or ' '.join(filter(None, [actor.get('first_name'), actor.get('last_name')])).strip()
        or 'ادمین'
    )

    if callback_query_id and chat_id != ADMIN_GROUP_CHAT_ID:
        _answer_telegram_callback(callback_query_id, 'این عملیات فقط در گروه ادمین مجاز است.', show_alert=True)
        return JsonResponse({'ok': True})

    parts = callback_data.split(':')
    if len(parts) != 3 or parts[0] != 'purchase' or parts[1] not in {'approve', 'reject'}:
        if callback_query_id:
            _answer_telegram_callback(callback_query_id, 'دکمه نامعتبر است.', show_alert=True)
        return JsonResponse({'ok': True})

    try:
        purchase_request_id = int(parts[2])
    except (TypeError, ValueError):
        if callback_query_id:
            _answer_telegram_callback(callback_query_id, 'شناسه درخواست نامعتبر است.', show_alert=True)
        return JsonResponse({'ok': True})

    with transaction.atomic():
        success, result_text, purchase_request = _process_telegram_purchase_action(
            purchase_request_id=purchase_request_id,
            action=parts[1],
        )

    if callback_query_id:
        _answer_telegram_callback(callback_query_id, result_text, show_alert=not success)

    if not success or purchase_request is None:
        return JsonResponse({'ok': True})

    invalidate_cache('admin_requests*')
    invalidate_cache('admin_request_detail*')
    invalidate_cache('admin_dashboard*')

    if message_id and chat_id:
        _remove_telegram_message_buttons(chat_id, message_id)

    artwork_title = purchase_request.artwork.title if purchase_request.artwork else 'نامشخص'
    action_label = 'تایید شد' if parts[1] == 'approve' else 'رد شد'
    followup_message = "\n".join(
        [
            "🧾 <b>رسیدگی به درخواست خرید</b>",
            "",
            f"🏷 <b>نام اثر:</b> {artwork_title}",
            f"🆔 <b>شناسه درخواست:</b> {purchase_request.pk}",
            f"📌 <b>وضعیت:</b> {action_label}",
            f"👤 <b>رسیدگی‌کننده:</b> {actor_name}",
        ]
    )
    _send_telegram_purchase_message(
        followup_message,
        chat_id=chat_id,
        thread_id=message_thread_id,
    )

    return JsonResponse({'ok': True})

# --- ویو برای نمایش لیست آثار هنری ---
class ArtworkListView(ListView):
    model = Artwork
    template_name = 'store/store.html'
    context_object_name = 'artworks'
    paginate_by = 100

    def get_queryset(self):
        queryset = Artwork.objects.select_related('artist', 'artwork_type').exclude(is_sold=1).order_by('-created_at')
        query = self.request.GET.get('q')
        type_id = self.request.GET.get('type')

        if query:
            queryset = queryset.filter(
                Q(title__icontains=query) |
                Q(artist__name__icontains=query)
            )

        if type_id and type_id.isdigit():
            queryset = queryset.filter(artwork_type_id=type_id)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['artwork_types'] = ArtworkType.objects.all()
        context['search_query'] = self.request.GET.get('q', '')
        type_id = self.request.GET.get('type')
        if type_id and type_id.isdigit():
            context['selected_type'] = int(type_id)
        else:
            context['selected_type'] = None
        context['user_liked_artworks'] = set()
        if self.request.user.is_authenticated:
            context['user_liked_artworks'] = set(
                ProductLike.objects.filter(user=self.request.user).values_list('product_id', flat=True)
            )
        return context

# --- ویو برای نمایش جزئیات اثر هنری ---
class ArtworkDetailView(DetailView):
    model = Artwork
    template_name = 'store/product_store.html'
    context_object_name = 'artwork'

    def get(self, request, *args, **kwargs):
        # اجرای متد پیش‌فرض برای دریافت آبجکت و تنظیمات رندر
        response = super().get(request, *args, **kwargs)
        
        # استخراج آدرس IP واقعی کاربر
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')

        user = request.user if request.user.is_authenticated else None

        # ثبت و بروزرسانی لاگ نشست و حضور در سایت
        if not request.session.session_key:
            request.session.create()
        
        session_key = request.session.session_key
        
        # جایگزینی get_or_create با filter().first() برای جلوگیری از خطای MultipleObjectsReturned
        site_log = SiteVisitLog.objects.filter(session_key=session_key).first()
        
        if site_log:
            # اگر لاگ از قبل وجود داشت (یا چندین لاگ وجود داشت و اولی را گرفتیم)، زمان بروز می‌شود
            site_log.last_activity = timezone.now()
            # آپدیت آی‌پی در صورتی که تغییر کرده باشد
            site_log.ip_address = ip_address 
            if user and not site_log.user:
                site_log.user = user
            site_log.save(update_fields=['last_activity', 'user', 'ip_address'])
        else:
            # اگر هیچ لاگی یافت نشد، یک رکورد جدید ایجاد می‌کنیم
            SiteVisitLog.objects.create(
                session_key=session_key,
                user=user,
                ip_address=ip_address,
                start_time=timezone.now(),
                last_activity=timezone.now()
            )

        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        artwork = self.object

        if self.request.user.is_authenticated:
            context['is_liked'] = ProductLike.objects.filter(user=self.request.user, product=artwork).exists()
        else:
            context['is_liked'] = False

        context['whatsapp_link'] = f"https://wa.me/989123456789?text=درخواست خرید {artwork.title}"
        context['telegram_link'] = f"https://t.me/admin_username?text=درخواست خرید {artwork.title}"

        related_artworks = (
            Artwork.objects
            .filter(artist=artwork.artist)
            .exclude(pk=artwork.pk)
            .exclude(is_sold=Artwork.IsSoldStatus.SOLD)
            .order_by('-created_at')[:4]
        )
        context['related_artworks'] = related_artworks
        return context

# --- ویو برای لایک کردن محصول ---
class ToggleLikeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Artwork, pk=pk)
        
        # در اینجا نیز برای امنیت بیشتر از بروز خطای مشابه، از filter().first() استفاده شد
        like = ProductLike.objects.filter(user=request.user, product=product).first()

        if like:
            like.delete()
            is_liked = False
        else:
            ProductLike.objects.create(user=request.user, product=product)
            is_liked = True

        return JsonResponse({
            'is_liked': is_liked,
            'count': product.likes.count()
        })

# --- ویو جستجو ---
def search_artworks(request):
    query = request.GET.get('q')
    type_id = request.GET.get('type')
    
    artworks_list = (
        Artwork.objects
        .select_related('artist', 'artwork_type')
        .exclude(is_sold=Artwork.IsSoldStatus.SOLD)
        .order_by('-created_at')
    )

    if query:
        artworks_list = artworks_list.filter(
            Q(title__icontains=query) |
            Q(artist__name__icontains=query)
        )

    selected_type = None
    if type_id and type_id.isdigit():
        artworks_list = artworks_list.filter(artwork_type__id=type_id)
        selected_type = int(type_id)

    paginator = Paginator(artworks_list, 100)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'artworks': page_obj,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'artwork_types': ArtworkType.objects.all(),
        'search_query': query,
        'selected_type': selected_type
    }
    return render(request, 'store/store.html', context)

@require_POST
def reserve_artwork(request, pk):
    """
    ثبت درخواست خرید و رزرو محصول
    """
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'message': get_notification('store.reserve.login_required')
        }, status=401)

    user = request.user

    try:
        with transaction.atomic():
            artwork = (
                Artwork.objects
                .select_for_update()
                .select_related('artist')
                .get(pk=pk)
            )

            if artwork.is_sold != Artwork.IsSoldStatus.AVAILABLE:
                return JsonResponse({
                    'success': False,
                    'message': get_notification('store.reserve.already_reserved_or_sold')
                }, status=400)

            artwork.is_sold = Artwork.IsSoldStatus.RESERVED
            artwork.save(update_fields=['is_sold', 'updated_at'])

            purchase_request = TelegramPurchaseRequest.objects.create(
                user=user,
                artwork=artwork,
            )
            phone = getattr(user, 'phone_number', user.username)
            PurchaseHistory.objects.create(
                user=user,
                artwork=artwork,
            )

            user_name = (getattr(user, "get_full_name", lambda: "")() or "").strip() or None
            jalali_dt = _jalali_datetime_str(timezone.now())

            lines = [
                "🎨 <b>درخواست خرید اثر هنری</b>",
                "",
                f"🏷 <b>نام اثر:</b> {artwork.title}",
                f"🆔 <b>کد اثر:</b> {artwork.product_id}",
                f"💰 <b>قیمت اثر:</b> {artwork.price:,} دلار",
            ]
            if user_name:
                lines.append(f"👤 <b>نام کاربر:</b> {user_name}")
            lines.extend(
                [
                    f"📱 <b>شماره تلفن:</b> {phone}",
                    f"🕒 <b>تاریخ و ساعت:</b> {jalali_dt}",
                ]
            )
            message_text = "\n".join(lines)
            transaction.on_commit(
                lambda: _handle_purchase_request_side_effects_async(
                    artwork_title=artwork.title,
                    purchase_request_id=purchase_request.pk,
                    user_id=user.id,
                    artwork_id=artwork.id,
                    message_text=message_text,
                )
            )
    except Artwork.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': get_notification('store.reserve.not_found')
        }, status=404)

    return JsonResponse({
        'success': True,
        'message': get_notification('store.reserve.success')
    })
