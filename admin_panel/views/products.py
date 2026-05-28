import json
import uuid
from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Q, Count, Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from auction.models import AuctionProduct, Auction, AuctionVisitHistory, Bid
from auction.models import Bid as AuctionBid
from auction.ranking import get_product_rankings, get_top_unique_bid_amounts
from core.decorators import log_admin_action, staff_required
from core.utils import cache_response, invalidate_cache
from store.models import Artwork, ArtworkType, Artist, Material, Subject, Usage, VisitHistory


def _request_payload(request):
    try:
        return json.loads(request.body.decode() or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return request.POST.dict()


@staff_required
def store_page_view(request):
    return render(request, 'admin_panel/store_products.html')


@staff_required
def store_detail_page_view(request, pk):
    return render(request, 'admin_panel/store_product_detail.html', {'product_pk': pk})


@staff_required
def auctions_page_view(request):
    return render(request, 'admin_panel/auctions.html')


@staff_required
def auction_detail_page_view(request, pk):
    return render(request, 'admin_panel/auction_detail.html', {'auction_pk': pk})


@staff_required
def auction_products_page_view(request):
    return render(request, 'admin_panel/auction_products.html')


@staff_required
def auction_product_detail_page_view(request, pk):
    return render(request, 'admin_panel/auction_product_detail.html', {'product_pk': pk})


@staff_required
def create_page_view(request):
    return render(request, 'admin_panel/product_create.html')


@require_http_methods(['GET'])
@staff_required
def product_options(request):
    artists = list(Artist.objects.all().order_by('name').values('id', 'name'))
    artwork_types = list(ArtworkType.objects.all().order_by('name').values('id', 'name'))
    subjects = list(Subject.objects.all().order_by('name').values('id', 'name'))
    usages = list(Usage.objects.all().order_by('name').values('id', 'name'))
    materials = list(Material.objects.all().order_by('name').values('id', 'name'))
    auctions_qs = Auction.objects.all().order_by('-start_date')

    auctions = [
        {
            'id': a.id,
            'title': a.name or f'مزایده {a.id}',
            'start_date': a.start_date.isoformat() if a.start_date else None,
            'end_date': a.end_date.isoformat() if a.end_date else None,
            'status': a.status,
        }
        for a in auctions_qs
    ]

    return JsonResponse(
        {
            'artists': artists,
            'artwork_types': artwork_types,
            'subjects': subjects,
            'usages': usages,
            'materials': materials,
            'auctions': auctions,
        }
    )


@staff_required
def reports_page_view(request):
    return render(request, 'admin_panel/product_reports.html')


@require_http_methods(['GET'])
@staff_required
def visit_reports(request):
    report_type = request.GET.get('type', 'store')
    search = request.GET.get('search', '').strip()
    auction_id = request.GET.get('auction_id')
    product_id = request.GET.get('product_id')

    if report_type == 'auction':
        queryset = AuctionVisitHistory.objects.select_related('user', 'auction').filter(product__isnull=True).order_by('-timestamp')
    elif report_type == 'auction_product':
        queryset = AuctionVisitHistory.objects.select_related('user', 'auction', 'product').filter(product__isnull=False).order_by('-timestamp')
    else:
        report_type = 'store'
        queryset = VisitHistory.objects.select_related('user', 'product').order_by('-timestamp')

    if search:
        if report_type == 'store':
            queryset = queryset.filter(
                Q(product__title__icontains=search)
                | Q(product__product_id__icontains=search)
                | Q(user__email__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(ip_address__icontains=search)
            )
        elif report_type == 'auction':
            queryset = queryset.filter(
                Q(auction__name__icontains=search)
                | Q(user__email__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(ip_address__icontains=search)
            )
        else:
            queryset = queryset.filter(
                Q(auction__name__icontains=search)
                | Q(product__title__icontains=search)
                | Q(product__product_id__icontains=search)
                | Q(user__email__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(ip_address__icontains=search)
            )

    if report_type == 'auction' and auction_id and auction_id.isdigit():
        queryset = queryset.filter(auction_id=int(auction_id))
    elif report_type == 'auction_product':
        if auction_id and auction_id.isdigit():
            queryset = queryset.filter(auction_id=int(auction_id))
        if product_id and product_id.isdigit():
            queryset = queryset.filter(product_id=int(product_id))
    elif report_type == 'store':
        if product_id and str(product_id).isdigit():
            queryset = queryset.filter(product_id=int(product_id))

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    if report_type == 'store':
        payload = [
            {
                'id': item.id,
                'section': 'بازدید محصول فروشگاه',
                'target_id': item.product.product_id if item.product_id else '',
                'target_title': item.product.title if item.product_id else '',
                'parent_title': 'فروشگاه',
                'visitor_name': (item.user.get_full_name() or item.user.email) if item.user_id else 'کاربر مهمان',
                'user_id': str(item.user_id) if item.user_id else None,
                'ip_address': item.ip_address or 'نامشخص',
                'timestamp': item.timestamp.isoformat(),
            }
            for item in page_obj.object_list
        ]
    elif report_type == 'auction':
        payload = [
            {
                'id': item.id,
                'section': 'بازدید مزایده',
                'target_id': item.auction_id,
                'target_title': item.auction.name or f'مزایده {item.auction_id}',
                'parent_title': '-',
                'visitor_name': (
                    item.user.get_full_name() or getattr(item.user, 'email', '') or getattr(item.user, 'username', '')
                ) if item.user_id else 'کاربر مهمان',
                'user_id': str(item.user_id) if item.user_id else None,
                'ip_address': item.ip_address or 'نامشخص',
                'timestamp': item.timestamp.isoformat(),
            }
            for item in page_obj.object_list
        ]
    else:
        payload = [
            {
                'id': item.id,
                'section': 'بازدید محصول مزایده',
                'target_id': item.product.product_id if item.product_id else item.product_id,
                'target_title': item.product.title if item.product_id else '',
                'parent_title': item.auction.name or f'مزایده {item.auction_id}',
                'visitor_name': (
                    item.user.get_full_name() or getattr(item.user, 'email', '') or getattr(item.user, 'username', '')
                ) if item.user_id else 'کاربر مهمان',
                'user_id': str(item.user_id) if item.user_id else None,
                'ip_address': item.ip_address or 'نامشخص',
                'timestamp': item.timestamp.isoformat(),
            }
            for item in page_obj.object_list
        ]

    return JsonResponse(
        {
            'results': payload,
            'total': paginator.count,
            'pages': paginator.num_pages,
            'current_page': page_obj.number,
            'type': report_type,
        }
    )


# ==========================================
# بخش محصولات فروشگاهی (Store Products)
# ==========================================

@require_http_methods(['GET', 'POST'])
@staff_required
def store_list(request):
    if request.method == 'POST':
        data = _request_payload(request)
        artist_id = data.get('artist_id')
        if not artist_id:
            return JsonResponse({'error': 'artist_id الزامی است'}, status=400)
        try:
            product = Artwork.objects.create(
                product_id=(data.get('product_id') or '').strip(),
                title=data.get('title'),
                description=data.get('description'),
                price=data.get('price'),
                dimensions=data.get('dimensions'),
                creation_year=data.get('creation_year'),
                provenance=data.get('provenance'),
                is_sold=data.get('is_sold', Artwork.IsSoldStatus.AVAILABLE),
                authenticity_status=data.get('authenticity_status', Artwork.AuthenticityStatus.CONFIRMED),
                artist_id=artist_id,
                artwork_type_id=data.get('artwork_type_id') or None,
                subject_id=data.get('subject_id') or None,
                usage_id=data.get('usage_id') or None,
                material_id=data.get('material_id') or None,
            )
            invalidate_cache('admin_dashboard*')
            invalidate_cache('admin_store_products*')
            return JsonResponse({'success': True, 'id': product.id}, status=201)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    products = (
        Artwork.objects.select_related('artist')
        .annotate(views_count=Count('visithistory'))
    )

    status = request.GET.get('status')
    if status:
        status_map = {
            'active': Artwork.IsSoldStatus.AVAILABLE,
            'available': Artwork.IsSoldStatus.AVAILABLE,
            'sold': Artwork.IsSoldStatus.SOLD,
            'reserved': Artwork.IsSoldStatus.RESERVED,
            'inactive': Artwork.IsSoldStatus.SOLD,
        }
        if status in status_map:
            products = products.filter(is_sold=status_map[status])

    search = request.GET.get('search')
    if search:
        products = products.filter(
            Q(title__icontains=search)
            | Q(artist__name__icontains=search)
            | Q(product_id__icontains=search)
        )

    sort = request.GET.get('sort', '-created_at')
    products = products.order_by(sort)

    paginator = Paginator(products, 20)
    page = paginator.get_page(request.GET.get('page', 1))
    page_items = list(page.object_list)
    product_rankings = get_product_rankings([item.product_id for item in page_items])

    payload = [
        {
            'id': product.id,
            'title': product.title,
            'seller': product.artist.name if product.artist else 'نامشخص',
            'price': str(product.price),
            'status': product.get_is_sold_display(),
            'created_at': product.created_at.isoformat(),
            'updated_at': product.updated_at.isoformat() if getattr(product, 'updated_at', None) else None,
            'views': getattr(product, 'views_count', 0),
        }
        for product in page.object_list
    ]

    return JsonResponse({
        'products': payload,
        'total': paginator.count,
        'pages': paginator.num_pages,
    })


@require_http_methods(['GET', 'PUT', 'DELETE'])
@staff_required
@log_admin_action('update_store_product')
def store_detail(request, pk):
    product = get_object_or_404(Artwork, pk=pk)

    if request.method == 'PUT':
        data = _request_payload(request)
        editable_fields = {
            'title', 'description', 'price', 'dimensions',
            'creation_year', 'provenance', 'is_sold', 'authenticity_status',
            'product_id', 'artist_id', 'artwork_type_id', 'subject_id', 'usage_id', 'material_id'
        }
        for key, value in data.items():
            if key in editable_fields:
                if key == 'product_id':
                    product.product_id = (value or '').strip()
                elif key == 'artist_id':
                    product.artist_id = value or product.artist_id
                elif key == 'artwork_type_id':
                    product.artwork_type_id = value or None
                elif key == 'subject_id':
                    product.subject_id = value or None
                elif key == 'usage_id':
                    product.usage_id = value or None
                elif key == 'material_id':
                    product.material_id = value or None
                elif hasattr(product, key):
                    setattr(product, key, value)
        product.save()

        invalidate_cache('admin_dashboard*')
        invalidate_cache('admin_store_products*')
        invalidate_cache(f'admin_store_product_detail_{pk}')
        return JsonResponse({'success': True})

    elif request.method == 'DELETE':
        product.delete()
        invalidate_cache('admin_dashboard*')
        invalidate_cache('admin_store_products*')
        return JsonResponse({'success': True, 'message': 'محصول با موفقیت حذف شد'})

    return JsonResponse({
        'id': product.pk,
        'product_id': product.product_id,
        'title': product.title,
        'price': str(product.price),
        'status': product.get_is_sold_display(),
        'is_sold': product.is_sold,
        'authenticity_status': product.authenticity_status,
        'seller': product.artist.name if product.artist else 'نامشخص',
        'artist_id': product.artist_id,
        'artwork_type_id': getattr(product, 'artwork_type_id', None),
        'subject_id': getattr(product, 'subject_id', None),
        'usage_id': getattr(product, 'usage_id', None),
        'material_id': getattr(product, 'material_id', None),
        'description': product.description,
        'dimensions': product.dimensions,
        'creation_year': product.creation_year,
        'provenance': product.provenance,
        'created_at': product.created_at.isoformat(),
        'updated_at': product.updated_at.isoformat() if getattr(product, 'updated_at', None) else None,
        'views': VisitHistory.objects.filter(product=product).count(),
    })


@require_http_methods(['POST'])
@staff_required
@log_admin_action('bulk_store_action')
def store_bulk(request):
    data = _request_payload(request)
    ids = data.get('ids', [])
    action = data.get('action')

    if not ids or not action:
        return JsonResponse({'error': 'اطلاعات ارسالی نامعتبر است'}, status=400)

    queryset = Artwork.objects.filter(pk__in=ids)

    if action == 'mark_sold':
        queryset.update(is_sold=Artwork.IsSoldStatus.SOLD, updated_at=timezone.now())
    elif action == 'mark_available':
        queryset.update(is_sold=Artwork.IsSoldStatus.AVAILABLE, updated_at=timezone.now())
    elif action == 'delete':
        queryset.delete()
    else:
        return JsonResponse({'error': 'عملیات ناشناخته'}, status=400)

    invalidate_cache('admin_dashboard*')
    invalidate_cache('admin_store_products*')
    return JsonResponse({'success': True})


@require_http_methods(['GET'])
@staff_required
@cache_response(timeout=300, key_prefix='admin_store_stats')
def store_stats(request):
    total_products = Artwork.objects.count()
    sold_products = Artwork.objects.filter(is_sold=Artwork.IsSoldStatus.SOLD).count()
    available_products = Artwork.objects.filter(is_sold=Artwork.IsSoldStatus.AVAILABLE).count()

    thirty_days_ago = timezone.now() - timedelta(days=30)
    sales_chart = list(
        Artwork.objects.filter(
            is_sold=Artwork.IsSoldStatus.SOLD,
            created_at__gte=thirty_days_ago
        )
        .annotate(date=TruncDate('created_at'))
        .values('date')
        .annotate(sales=Sum('price'), count=Count('id'))
        .order_by('date')
    )

    return JsonResponse({
        'stats': {
            'total': total_products,
            'sold': sold_products,
            'available': available_products,
        },
        'chart_data': sales_chart
    })


# ==========================================
# بخش مدیریت پایه مزایده‌ها (Auctions)
# ==========================================

@require_http_methods(['GET', 'POST'])
@staff_required
def auction_main_list(request):
    if request.method == 'POST':
        data = _request_payload(request)
        try:
            auction = Auction.objects.create(
                name=data.get('name', ''),
                start_date=data.get('start_date'),
                end_date=data.get('end_date'),
                products_count=data.get('products_count', 0),
            )
            invalidate_cache('admin_auctions*')
            return JsonResponse({'success': True, 'id': auction.id}, status=201)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    now = timezone.now()
    auctions = Auction.objects.annotate(
        views_count=Count('visit_history', filter=Q(visit_history__product__isnull=True)),
        products_total=Count('products', distinct=True),
    )

    search = request.GET.get('search')
    if search:
        auctions = auctions.filter(Q(name__icontains=search) | Q(id=search if search.isdigit() else 0))

    status_filter = request.GET.get('status')
    if status_filter:
        if status_filter == 'upcoming' or status_filter == 'ready':
            auctions = auctions.filter(start_date__gt=now)
        elif status_filter == 'running' or status_filter == 'ongoing':
            auctions = auctions.filter(start_date__lte=now, end_date__gte=now)
        elif status_filter == 'finished':
            auctions = auctions.filter(end_date__lt=now)

    sort = request.GET.get('sort', '-start_date')
    auctions = auctions.order_by(sort)

    paginator = Paginator(auctions, 20)
    page = paginator.get_page(request.GET.get('page', 1))

    # ترجمه وضعیت‌ها به فارسی برای نمایش در پنل
    status_fa = {
        'ready': 'آینده',
        'ongoing': 'در حال برگزاری',
        'finished': 'پایان یافته'
    }

    payload = [{
        'id': a.id,
        'title': a.name or f'مزایده {a.id}',
        'start_date': a.start_date.isoformat() if a.start_date else None,
        'end_date': a.end_date.isoformat() if a.end_date else None,
        'status': status_fa.get(a.status, 'نامشخص'),
        'views': getattr(a, 'views_count', 0),
        'products_total': getattr(a, 'products_total', 0),
        'created_at': a.created_at.isoformat() if getattr(a, 'created_at', None) else None,
        'updated_at': a.updated_at.isoformat() if getattr(a, 'updated_at', None) else None,
    } for a in page.object_list]

    return JsonResponse({
        'auctions': payload,
        'total': paginator.count,
        'pages': paginator.num_pages,
    })


@require_http_methods(['GET', 'PUT', 'DELETE'])
@staff_required
@log_admin_action('update_auction')
def auction_main_detail(request, pk):
    auction = get_object_or_404(Auction, pk=pk)

    if request.method == 'PUT':
        data = _request_payload(request)
        for key in ['name', 'start_date', 'end_date', 'products_count']:
            if key in data and hasattr(auction, key):
                setattr(auction, key, data[key])
        auction.save()
        invalidate_cache('admin_auctions*')
        return JsonResponse({'success': True})

    elif request.method == 'DELETE':
        auction.delete()
        invalidate_cache('admin_auctions*')
        return JsonResponse({'success': True})

    status_fa = {
        'ready': 'آینده',
        'ongoing': 'در حال برگزاری',
        'finished': 'پایان یافته',
    }

    return JsonResponse({
        'id': auction.pk,
        'title': auction.name or f'مزایده {auction.pk}',
        'start_date': auction.start_date.isoformat() if auction.start_date else None,
        'end_date': auction.end_date.isoformat() if auction.end_date else None,
        'status': status_fa.get(auction.status, 'نامشخص'),
        'products_count': auction.products_count,
        'views': AuctionVisitHistory.objects.filter(auction=auction, product__isnull=True).count(),
        'products_total': auction.products.count(),
        'created_at': auction.created_at.isoformat() if getattr(auction, 'created_at', None) else None,
        'updated_at': auction.updated_at.isoformat() if getattr(auction, 'updated_at', None) else None,
    })


# ==========================================
# بخش محصولات مزایده (Auction Products)
# ==========================================

@require_http_methods(['GET', 'POST'])
@staff_required
def auction_list(request):
    if request.method == 'POST':
        data = _request_payload(request)
        auction_id = data.get('auction_id')
        artist_id = data.get('artist_id')
        artwork_type_id = data.get('artwork_type_id')
        if not auction_id:
            return JsonResponse({'error': 'auction_id الزامی است'}, status=400)
        if not artist_id:
            return JsonResponse({'error': 'artist_id الزامی است'}, status=400)
        if not artwork_type_id:
            return JsonResponse({'error': 'artwork_type_id الزامی است'}, status=400)

        try:
            prod_id = (data.get('product_id') or '').strip() or f"AUC-{uuid.uuid4().hex[:8].upper()}"
            title = (data.get('title') or data.get('artwork_title') or 'بدون عنوان').strip() or 'بدون عنوان'
            base_price = data.get('base_price', None)
            if base_price is None:
                base_price = data.get('reserve_price', 0)

            current_price = data.get('current_price')
            if current_price in ('', None):
                current_price = None

            winner_id = data.get('winner_id')
            if winner_id in ('', None):
                winner_id = None

            authenticity_status = data.get('authenticity_status', AuctionProduct.AuthenticityStatus.CONFIRMED)

            ap = AuctionProduct.objects.create(
                auction_id=auction_id,
                product_id=prod_id,
                title=title,
                authenticity_status=authenticity_status,
                description=data.get('description'),
                dimensions=data.get('dimensions'),
                creation_year=data.get('creation_year'),
                artist_id=artist_id,
                artwork_type_id=artwork_type_id,
                subject_id=data.get('subject_id') or None,
                usage_id=data.get('usage_id') or None,
                material_id=data.get('material_id') or None,
                base_price=base_price or 0,
                current_price=current_price,
                bid_value=data.get('bid_value', 0),
                winner_id=winner_id,
            )
            invalidate_cache('admin_auction_products*')
            return JsonResponse({'success': True, 'id': ap.id}, status=201)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    now = timezone.now()
    products = (
        AuctionProduct.objects.select_related('auction', 'artist')
        .annotate(views_count=Count('visit_history'))
        .order_by('-created_at')
    )

    auction_id = request.GET.get('auction_id')
    if auction_id and str(auction_id).isdigit():
        products = products.filter(auction_id=int(auction_id))

    status = request.GET.get('status')
    if status:
        if status in ['upcoming', 'ready']:
            products = products.filter(auction__start_date__gt=now)
        elif status in ['running', 'ongoing']:
            products = products.filter(auction__start_date__lte=now, auction__end_date__gte=now)
        elif status == 'finished':
            products = products.filter(auction__end_date__lt=now)

    search = request.GET.get('search')
    if search:
        products = products.filter(
            Q(title__icontains=search)
            | Q(product_id__icontains=search)
            | Q(artist__name__icontains=search)
        )

    sort = request.GET.get('sort', '-created_at')
    products = products.order_by(sort)

    paginator = Paginator(products, 20)
    page = paginator.get_page(request.GET.get('page', 1))
    page_items = list(page.object_list)
    product_rankings = get_product_rankings([item.product_id for item in page_items])

    status_fa = {
        'ready': 'آینده',
        'ongoing': 'در حال برگزاری',
        'finished': 'پایان یافته'
    }

    payload = [{
        'id': ap.id,
        'auction_id': ap.auction_id,
        'auction': ap.auction.name or f'مزایده {ap.auction.id}' if ap.auction else '',
        'artwork_title': ap.title,
        'artist': ap.artist.name if ap.artist else 'نامشخص',
        'reserve_price': str(ap.base_price), # نگاشت base_price دیتابیس به فرمت مورد انتظار فرانت
        'status': status_fa.get(ap.auction.status, 'نامشخص') if ap.auction else 'نامشخص',
        'auction_start': ap.auction.start_date.isoformat() if ap.auction and ap.auction.start_date else None,
        'auction_end': ap.auction.end_date.isoformat() if ap.auction and ap.auction.end_date else None,
        'created_at': ap.created_at.isoformat() if getattr(ap, 'created_at', None) else None,
        'updated_at': ap.updated_at.isoformat() if getattr(ap, 'updated_at', None) else None,
        'views': getattr(ap, 'views_count', 0),
        'top_rankings': product_rankings.get(str(ap.product_id), []),
    } for ap in page_items]

    return JsonResponse({
        'products': payload,
        'total': paginator.count,
        'pages': paginator.num_pages,
    })


@require_http_methods(['GET', 'PUT', 'DELETE'])
@staff_required
@log_admin_action('update_auction_product')
def auction_detail(request, pk):
    ap = get_object_or_404(AuctionProduct, pk=pk)

    if request.method == 'PUT':
        data = _request_payload(request)
        if 'artwork_title' in data:
            ap.title = data['artwork_title']
        if 'reserve_price' in data:
            ap.base_price = data['reserve_price']
        if 'product_id' in data:
            ap.product_id = (data.get('product_id') or '').strip() or ap.product_id
        if 'auction_id' in data:
            ap.auction_id = data.get('auction_id') or ap.auction_id
        if 'artist_id' in data:
            ap.artist_id = data.get('artist_id') or ap.artist_id
        if 'artwork_type_id' in data:
            ap.artwork_type_id = data.get('artwork_type_id') or ap.artwork_type_id
        if 'subject_id' in data:
            ap.subject_id = data.get('subject_id') or None
        if 'usage_id' in data:
            ap.usage_id = data.get('usage_id') or None
        if 'material_id' in data:
            ap.material_id = data.get('material_id') or None
        if 'authenticity_status' in data:
            ap.authenticity_status = data.get('authenticity_status')
        if 'current_price' in data:
            ap.current_price = data.get('current_price') if data.get('current_price') not in ('', None) else None
        if 'bid_value' in data:
            ap.bid_value = data.get('bid_value')
        if 'winner_id' in data:
            ap.winner_id = data.get('winner_id') if data.get('winner_id') not in ('', None) else None
        editable_fields = ['title', 'base_price', 'description', 'dimensions', 'creation_year']
        for key in editable_fields:
            if key in data and hasattr(ap, key):
                setattr(ap, key, data[key])
        ap.save()
        invalidate_cache('admin_auction_products*')
        return JsonResponse({'success': True})

    elif request.method == 'DELETE':
        ap.delete()
        invalidate_cache('admin_auction_products*')
        return JsonResponse({'success': True})

    status_fa = {
        'ready': 'آینده',
        'ongoing': 'در حال برگزاری',
        'finished': 'پایان یافته'
    }

    return JsonResponse({
        'id': ap.pk,
        'product_id': ap.product_id,
        'auction_id': ap.auction_id,
        'auction': ap.auction.name or f'مزایده {ap.auction.id}' if ap.auction else '',
        'artwork_title': ap.title,
        'artist': ap.artist.name if ap.artist else 'نامشخص',
        'artist_id': ap.artist_id,
        'artwork_type_id': ap.artwork_type_id,
        'subject_id': ap.subject_id,
        'usage_id': ap.usage_id,
        'material_id': ap.material_id,
        'authenticity_status': ap.authenticity_status,
        'reserve_price': str(ap.base_price),
        'current_price': str(ap.current_price) if ap.current_price is not None else None,
        'bid_value': str(ap.bid_value),
        'winner_id': ap.winner_id,
        'status': status_fa.get(ap.auction.status, 'نامشخص') if ap.auction else 'نامشخص',
        'auction_start': ap.auction.start_date.isoformat() if ap.auction and ap.auction.start_date else None,
        'auction_end': ap.auction.end_date.isoformat() if ap.auction and ap.auction.end_date else None,
        'created_at': ap.created_at.isoformat() if getattr(ap, 'created_at', None) else None,
        'updated_at': ap.updated_at.isoformat() if getattr(ap, 'updated_at', None) else None,
        'views': AuctionVisitHistory.objects.filter(product=ap).count(),
    })


@require_http_methods(['POST'])
@staff_required
@log_admin_action('bulk_auction_products')
def auction_bulk(request):
    data = _request_payload(request)
    ids = data.get('ids', [])
    action = data.get('action')

    if not ids or not action:
        return JsonResponse({'error': 'اطلاعات ارسالی نامعتبر است'}, status=400)

    queryset = AuctionProduct.objects.filter(pk__in=ids)

    if action == 'delete':
        queryset.delete()
    else:
        # تغییر وضعیت محصول در مدل جدید بی‌معنی است زیرا وضعیت از مزایده به ارث می‌رسد
        # این بخش را برای جلوگیری از خطای سمت فرانت‌اند فقط با موفقیت برمی‌گردانیم
        pass 

    invalidate_cache('admin_auction_products*')
    return JsonResponse({'success': True})


@require_http_methods(['GET'])
@staff_required
@cache_response(timeout=300, key_prefix='admin_auction_stats')
def auction_stats(request):
    total_auctions = Auction.objects.count()
    active_auctions = Auction.objects.filter(start_date__lte=timezone.now(), end_date__gte=timezone.now()).count()

    # وضعیت محصولات بر اساس وضعیت مزایده‌هایشان محاسبه می‌شود
    now = timezone.now()
    ready_count = AuctionProduct.objects.filter(auction__start_date__gt=now).count()
    ongoing_count = AuctionProduct.objects.filter(auction__start_date__lte=now, auction__end_date__gte=now).count()
    finished_count = AuctionProduct.objects.filter(auction__end_date__lt=now).count()

    status_counts = [
        {'status': 'ready', 'count': ready_count},
        {'status': 'ongoing', 'count': ongoing_count},
        {'status': 'finished', 'count': finished_count},
    ]

    return JsonResponse({
        'stats': {
            'total_auctions': total_auctions,
            'active_auctions': active_auctions,
            'by_status': status_counts,
        }
    })


@require_http_methods(['GET'])
@staff_required
def bid_reports(request):
    search = request.GET.get('search', '').strip()
    auction_id = request.GET.get('auction_id')
    product_id = request.GET.get('product_id')

    queryset = Bid.objects.select_related('auction', 'product', 'user').order_by('-created_at')

    if search:
        queryset = queryset.filter(
            Q(product__title__icontains=search)
            | Q(product__product_id__icontains=search)
            | Q(user__email__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
            | Q(user_fullname__icontains=search)
            | Q(user_mobile__icontains=search)
        )

    if auction_id and str(auction_id).isdigit():
        queryset = queryset.filter(auction_id=int(auction_id))
    if product_id:
        queryset = queryset.filter(product__id=product_id)

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    results = []
    for bid in page_obj.object_list:
        results.append({
            'id': bid.id,
            'auction_id': bid.auction_id,
            'auction_name': bid.auction.name or f'مزایده {bid.auction_id}' if bid.auction else '-',
            'product_id': bid.product_id,
            'product_title': bid.product.title if bid.product else '-',
            'bid_amount': str(bid.bid_amount),
            'user_id': str(bid.user_id) if bid.user_id else None,
            'user_fullname': bid.user_fullname or '-',
            'user_mobile': bid.user_mobile or '-',
            'created_at': bid.created_at.isoformat() if bid.created_at else None,
        })

    return JsonResponse({
        'results': results,
        'total': paginator.count,
        'pages': paginator.num_pages,
        'current_page': page_obj.number,
    })


@require_http_methods(['GET'])
@staff_required
def product_bids(request, pk):
    product = get_object_or_404(AuctionProduct, pk=pk)
    queryset = Bid.objects.filter(product=product).select_related('user').order_by('-created_at')
    top_amounts = get_top_unique_bid_amounts(product.product_id, limit=10)

    paginator = Paginator(queryset, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    results = []
    for bid in page_obj.object_list:
        rank = None
        try:
            rank = top_amounts.index(bid.bid_amount) + 1
        except ValueError:
            rank = None
        results.append({
            'id': bid.id,
            'bid_amount': str(bid.bid_amount),
            'user_id': str(bid.user_id) if bid.user_id else None,
            'user_fullname': bid.user_fullname or '-',
            'user_mobile': bid.user_mobile or '-',
            'created_at': bid.created_at.isoformat() if bid.created_at else None,
            'rank': rank,
        })

    return JsonResponse({
        'results': results,
        'total': paginator.count,
        'pages': paginator.num_pages,
        'current_page': page_obj.number,
    })
