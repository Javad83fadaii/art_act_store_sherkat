import json

from django.shortcuts import render, get_object_or_404
from django.conf import settings
from django.http import FileResponse, Http404, StreamingHttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

# ایمپورت مدل‌های فروشگاه و مزایده
from store.models import Artwork, ProductLike, VisitHistory
from auction.models import Auction, AuctionProduct, AuctionVisitHistory

import mimetypes
import os
import re
from pathlib import Path


# ==========================================
# بخش اول: صفحات اصلی و استاتیک (Home & Pages)
# ==========================================

def home(request):
    """
    نمایش صفحه اصلی سایت
    شامل:
    ۱. جدیدترین آثار فروشگاه (حفظ منطق و ساختار قبلی)
    ۲. رویدادهای مزایده فعال (جایگزین شده با مدل اصلی Auction)
    """
    now = timezone.now()

    # ۱. دریافت جدیدترین آثار موجود فروشگاه
    # فقط ۳ محصول آخر که هنوز قابل خرید هستند نمایش داده می‌شوند.
    latest_artworks = Artwork.objects.filter(
        is_sold=Artwork.IsSoldStatus.AVAILABLE
    ).order_by('-created_at')[:3]

    # ۲. دریافت رویدادهای مزایده فعال
    # فیلتر مزایده‌هایی که شروع شده‌اند و هنوز تمام نشده‌اند
    active_auctions = Auction.objects.filter(
        start_date__lte=now,
        end_date__gt=now
    ).order_by('end_date')[:3]  # نمایش نهایتا ۳ مزایده فعال که زودتر تمام می‌شوند

    user_liked_artworks = set()
    if request.user.is_authenticated:
        user_liked_artworks = set(
            ProductLike.objects.filter(user=request.user).values_list('product_id', flat=True)
        )

    context = {
        'latest_artworks': latest_artworks,
        'active_auctions': active_auctions,
        'user_liked_artworks': user_liked_artworks,
    }

    return render(request, 'core/index.html', context)


def about(request):
    """نمایش صفحه درباره ما"""
    return render(request, 'core/about.html')


def site_rules(request):
    """نمایش صفحه قوانین و مقررات سایت"""
    return render(request, 'core/site_rules.html')


def _get_client_ip(request) -> str | None:
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


@csrf_exempt
@require_POST
def track_public_visit(request):
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'بدنه درخواست نامعتبر است.'}, status=400)

    visit_kind = str(payload.get('kind') or '').strip()
    object_id = payload.get('object_id')

    try:
        object_id = int(object_id)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'شناسه نامعتبر است.'}, status=400)

    user = request.user if request.user.is_authenticated else None
    ip_address = _get_client_ip(request)

    if visit_kind == 'store_product':
        product = get_object_or_404(Artwork, pk=object_id)
        VisitHistory.objects.create(
            user=user,
            ip_address=ip_address,
            product=product,
        )
    elif visit_kind == 'auction':
        auction = get_object_or_404(Auction, pk=object_id)
        AuctionVisitHistory.objects.create(
            user=user,
            ip_address=ip_address,
            auction=auction,
        )
    elif visit_kind == 'auction_product':
        product = get_object_or_404(
            AuctionProduct.objects.select_related('auction'),
            pk=object_id,
        )
        AuctionVisitHistory.objects.create(
            user=user,
            ip_address=ip_address,
            auction=product.auction,
            product=product,
        )
    else:
        return JsonResponse({'success': False, 'message': 'نوع بازدید نامعتبر است.'}, status=400)

    return JsonResponse({'success': True})


# ==========================================
# بخش دوم: استریم ویدیو (Video Streaming Support)
# ==========================================

def _iter_file_range(file_obj, start, length, chunk_size=8192):
    """
    یک Generator برای خواندن فایل به صورت تکه‌تکه (Chunk) 
    مناسب برای استریم مدیا و جلوگیری از اشغال بیش از حد حافظه RAM
    """
    file_obj.seek(start)
    remaining = length
    while remaining > 0:
        read_size = chunk_size if remaining >= chunk_size else remaining
        data = file_obj.read(read_size)
        if not data:
            break
        remaining -= len(data)
        yield data


def static_video(request, subpath: str):
    """
    مدیریت درخواست‌های مربوط به فایل‌های ویدیویی استاتیک با پشتیبانی از هدر Range.
    این ویو امکان جلو و عقب بردن ویدیو در پلیر مرورگر (Seek) را با ارسال کد 206 فراهم می‌کند.
    """
    allowed_ext = {'.mp4', '.webm', '.mov', '.m4v'}
    relative = Path('images') / subpath

    # بررسی پسوند مجاز ویدیو
    suffix = Path(subpath).suffix.lower()
    if suffix not in allowed_ext:
        raise Http404()

    # یافتن مسیر اصلی فایل‌های استاتیک
    try:
        static_root = Path(settings.STATICFILES_DIRS[0])
    except (AttributeError, IndexError):
        raise Http404()

    base_dir = (static_root / 'images').resolve()
    full_path = (static_root / relative).resolve()

    # جلوگیری از Directory Traversal Attack
    if base_dir not in full_path.parents:
        raise Http404()

    # بررسی وجود فایل
    if not full_path.exists() or not full_path.is_file():
        raise Http404()

    # تشخیص نوع محتوا (MIME type)
    ctype, _ = mimetypes.guess_type(str(full_path))
    content_type = ctype or 'application/octet-stream'
    file_size = os.path.getsize(full_path)

    # بررسی وجود هدر Range برای استریم
    range_header = request.headers.get('Range') or request.META.get('HTTP_RANGE')
    
    # اگر درخواستی برای Range نبود، کل فایل ارسال می‌شود (کد 200)
    if not range_header:
        resp = FileResponse(open(full_path, 'rb'), content_type=content_type)
        resp['Accept-Ranges'] = 'bytes'
        resp['Content-Length'] = str(file_size)
        return resp

    # پردازش هدر Range
    match = re.match(r'^bytes=(\d*)-(\d*)$', range_header.strip())
    if not match:
        resp = FileResponse(open(full_path, 'rb'), content_type=content_type)
        resp['Accept-Ranges'] = 'bytes'
        resp['Content-Length'] = str(file_size)
        return resp

    start_str, end_str = match.groups()
    if start_str == '' and end_str == '':
        resp = FileResponse(open(full_path, 'rb'), content_type=content_type)
        resp['Accept-Ranges'] = 'bytes'
        resp['Content-Length'] = str(file_size)
        return resp

    # محاسبه نقطه شروع و پایان بایت‌ها
    if start_str == '':
        suffix_length = min(int(end_str), file_size)
        start = file_size - suffix_length
        end = file_size - 1
    else:
        start = int(start_str)
        end = int(end_str) if end_str != '' else file_size - 1

    # اعتبارسنجی بازه درخواستی
    if start < 0 or start >= file_size:
        resp = StreamingHttpResponse(status=416)
        resp['Content-Range'] = f'bytes */{file_size}'
        return resp

    end = max(start, min(end, file_size - 1))
    length = end - start + 1

    # ارسال پاسخ با محتوای جزئی (کد 206 Partial Content)
    file_obj = open(full_path, 'rb')
    resp = StreamingHttpResponse(
        _iter_file_range(file_obj, start, length),
        status=206,
        content_type=content_type,
    )
    resp['Accept-Ranges'] = 'bytes'
    resp['Content-Length'] = str(length)
    resp['Content-Range'] = f'bytes {start}-{end}/{file_size}'
    
    return resp
