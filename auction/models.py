from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class Auction(models.Model):
    name = models.CharField(max_length=255, blank=True, null=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    products_count = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'auction_auction'
        verbose_name = 'Auction'
        verbose_name_plural = 'Auctions'
        ordering = ['-start_date']

    def __str__(self):
        return self.name or f'Auction #{self.pk}'

    @property
    def status(self) -> str:
        now = timezone.now()
        if now < self.start_date:
            return 'ready'
        if self.start_date <= now <= self.end_date:
            return 'ongoing'
        return 'finished'


class AuctionProduct(models.Model):
    class AuthenticityStatus(models.IntegerChoices):
        CONFIRMED = 0, 'اصالت تایید شده'
        NOT_CONFIRMED = 1, 'اصالت تایید نشده'

    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='products')
    product_id = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=255)
    authenticity_status = models.SmallIntegerField(
        choices=AuthenticityStatus.choices,
        default=AuthenticityStatus.CONFIRMED,
        verbose_name='وضعیت اصالت',
    )
    description = models.TextField(blank=True, null=True)
    dimensions = models.CharField(max_length=255, blank=True, null=True)
    creation_year = models.PositiveIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    artist = models.ForeignKey('store.Artist', on_delete=models.PROTECT, related_name='auction_products')
    artwork_type = models.ForeignKey(
        'store.ArtworkType',
        on_delete=models.PROTECT,
        related_name='auction_products',
    )
    subject = models.ForeignKey(
        'store.Subject',
        on_delete=models.PROTECT,
        related_name='auction_products',
        null=True,
        blank=True,
    )
    usage = models.ForeignKey(
        'store.Usage',
        on_delete=models.PROTECT,
        related_name='auction_products',
        null=True,
        blank=True,
    )
    material = models.ForeignKey(
        'store.Material',
        on_delete=models.PROTECT,
        related_name='auction_products',
        null=True,
        blank=True,
    )
    
    # فیلدهای قیمت به تومان (بدون اعشار)
    base_price = models.DecimalField(max_digits=15, decimal_places=0)
    current_price = models.DecimalField(max_digits=15, decimal_places=0, blank=True, null=True)
    price_description = models.CharField(max_length=255, blank=True, null=True, verbose_name='توضیحات قیمت')

    # درصد افزایش بید برای هر محصول
    bid_value = models.DecimalField(max_digits=15, decimal_places=0)
    
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='won_auction_products',
    )

    class Meta:
        db_table = 'auction_product'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.current_price is None:
            self.current_price = self.base_price
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'{self.product_id} - {self.title}'

    @property
    def main_image_url(self):
        if not self.product_id:
            return f'{settings.STATIC_URL}images/no-image.jpg'

        try:
            if settings.STATICFILES_DIRS:
                static_root = Path(settings.STATICFILES_DIRS[0])
            else:
                static_root = Path(settings.BASE_DIR) / 'static'
        except AttributeError:
            static_root = Path(settings.BASE_DIR) / 'static'

        file_name = f'{self.product_id}.webp'
        full_path = static_root / 'images' / 'action' / self.product_id / file_name
        if full_path.exists():
            return f'{settings.STATIC_URL}images/action/{self.product_id}/{file_name}'
        return f'{settings.STATIC_URL}images/no-image.jpg'

    @property
    def gallery_images(self):
        if not self.product_id:
            return []

        try:
            if settings.STATICFILES_DIRS:
                static_root = Path(settings.STATICFILES_DIRS[0])
            else:
                static_root = Path(settings.BASE_DIR) / 'static'
        except AttributeError:
            return []

        full_dir_path = static_root / 'images' / 'action' / self.product_id
        if not (full_dir_path.exists() and full_dir_path.is_dir()):
            return []

        file_names = [
            file_path.name
            for file_path in full_dir_path.iterdir()
            if file_path.is_file() and file_path.suffix.lower() == '.webp'
        ]
        file_names.sort(key=lambda n: n.lower())

        main_name = f'{self.product_id}.webp'
        if main_name in file_names:
            file_names.remove(main_name)
            file_names.insert(0, main_name)

        images_urls = [f"{settings.STATIC_URL}images/action/{self.product_id}/{name}" for name in file_names]
        return images_urls

    @property
    def model_360_url(self):
        if not self.product_id:
            return None

        try:
            if settings.STATICFILES_DIRS:
                static_root = Path(settings.STATICFILES_DIRS[0])
            else:
                static_root = Path(settings.BASE_DIR) / 'static'
        except AttributeError:
            return None

        folder_relative_path = Path('images') / 'action' / self.product_id
        folder_full_path = static_root / folder_relative_path

        if folder_full_path.exists() and folder_full_path.is_dir():
            glb_files = [
                file_path
                for file_path in folder_full_path.iterdir()
                if file_path.is_file() and file_path.suffix.lower() == '.glb'
            ]
            if glb_files:
                glb_files.sort(key=lambda p: p.name.lower())
                selected = glb_files[0]
                return f"{settings.STATIC_URL}images/action/{self.product_id}/{selected.name}"

        return None

    @property
    def video_url(self):
        if not self.product_id:
            return None

        try:
            if settings.STATICFILES_DIRS:
                static_root = Path(settings.STATICFILES_DIRS[0])
            else:
                static_root = Path(settings.BASE_DIR) / 'static'
        except AttributeError:
            return None

        folder_relative_path = Path('images') / 'action' / self.product_id
        folder_full_path = static_root / folder_relative_path

        if not (folder_full_path.exists() and folder_full_path.is_dir()):
            return None

        allowed = {'.mp4', '.webm', '.mov', '.m4v'}
        video_files = [
            file_path
            for file_path in folder_full_path.iterdir()
            if file_path.is_file() and file_path.suffix.lower() in allowed
        ]
        if not video_files:
            return None

        video_files.sort(key=lambda p: p.name.lower())
        selected = video_files[0]
        return f"{settings.STATIC_URL}images/action/{self.product_id}/{selected.name}"

    @property
    def end_time(self):
        return self.auction.end_date

    @property
    def medium(self):
        return getattr(self.material, 'name', '') or getattr(self.artwork_type, 'name', '') or ''

    def _get_linked_artwork(self):
        if hasattr(self, '_linked_artwork_cache'):
            return self._linked_artwork_cache
        try:
            from store.models import Artwork
        except Exception:
            self._linked_artwork_cache = None
            return None
        self._linked_artwork_cache = Artwork.objects.filter(product_id=self.product_id).only('provenance').first()
        return self._linked_artwork_cache

    @property
    def provenance(self):
        artwork = self._get_linked_artwork()
        return getattr(artwork, 'provenance', None)

    @property
    def condition_report(self):
        return None

    def get_min_next_bid(self):
        current = self.current_price or self.base_price or Decimal('0')
        try:
            current = Decimal(str(current))
        except (InvalidOperation, TypeError, ValueError):
            current = Decimal('0')
        percent = Decimal(str(self.bid_value or 0))
        min_next = current + (current * (percent / Decimal('100')))

        return int(min_next.to_integral_value(rounding=ROUND_CEILING))

    def place_bid(self, user, amount):
        user_model = get_user_model()

        with transaction.atomic():
            product = (
                AuctionProduct.objects
                .select_related('auction')
                .select_for_update()
                .get(pk=self.pk)
            )

            if product.auction.status != 'ongoing':
                raise ValidationError('مزایده در حال حاضر فعال نیست.')

            raw = (amount or '').strip() if isinstance(amount, str) else amount
            try:
                bid_amount = Decimal(str(raw))
            except (InvalidOperation, TypeError, ValueError):
                raise ValidationError('مبلغ پیشنهاد نامعتبر است.')

            if bid_amount <= 0:
                raise ValidationError('مبلغ پیشنهاد باید بزرگتر از صفر باشد.')

            min_next = Decimal(str(product.get_min_next_bid()))
            if bid_amount < min_next:
                # تغییر متن ارور از دلار به تومان
                raise ValidationError(f'حداقل پیشنهاد بعدی {int(min_next):,} تومان است.')

            bidder = user_model.objects.select_for_update().get(pk=user.pk)
            bidder.refresh_current_credit()
            active_cart_item = (
                AuctionCartItem.objects
                .select_related('user', 'bid')
                .select_for_update()
                .filter(product=product, is_active=True)
                .first()
            )
            bidder_cart_item = (
                AuctionCartItem.objects
                .select_related('user', 'bid')
                .select_for_update()
                .filter(user=bidder, product=product)
                .order_by('-updated_at', '-created_at', '-pk')
                .first()
            )

            previous_reserved = Decimal('0')
            if bidder_cart_item:
                previous_reserved = Decimal(str(bidder_cart_item.reserved_amount or 0))

            additional_required = bid_amount - previous_reserved
            available_credit = Decimal(str(getattr(bidder, 'current_credit', 0) or 0))
            if additional_required > available_credit:
                raise ValidationError('اعتبار شما برای ثبت این پیشنهاد کافی نیست.')

            previous_bidder = None
            if active_cart_item and active_cart_item.user_id != bidder.pk:
                previous_bidder = user_model.objects.select_for_update().get(pk=active_cart_item.user_id)
                active_cart_item.is_active = False
                active_cart_item.outbid_at = timezone.now()
                active_cart_item.save(update_fields=['is_active', 'outbid_at', 'updated_at'])

            bid = Bid.objects.create(
                auction=product.auction,
                product=product,
                bid_amount=bid_amount,
                user=bidder,
                user_fullname=getattr(bidder, 'get_full_name', lambda: '')() or getattr(bidder, 'full_name', '') or '',
                user_mobile=getattr(bidder, 'phone_number', '') or '',
            )

            if bidder_cart_item:
                bidder_cart_item.auction = product.auction
                bidder_cart_item.bid = bid
                bidder_cart_item.reserved_amount = bid_amount
                bidder_cart_item.is_active = True
                bidder_cart_item.outbid_at = None
                bidder_cart_item.save(
                    update_fields=[
                        'auction',
                        'bid',
                        'reserved_amount',
                        'is_active',
                        'outbid_at',
                        'updated_at',
                    ]
                )
            else:
                AuctionCartItem.objects.create(
                    user=bidder,
                    auction=product.auction,
                    product=product,
                    bid=bid,
                    reserved_amount=bid_amount,
                    is_active=True,
                )

            product.current_price = bid_amount
            product.winner = bidder
            product.save(update_fields=['current_price', 'winner'])

            bidder_id = bidder.pk
            previous_bidder_id = previous_bidder.pk if previous_bidder is not None else None

            bidder.refresh_current_credit()
            if previous_bidder is not None:
                previous_bidder.refresh_current_credit()

            def _broadcast_profile_updates():
                from accounts.realtime import broadcast_profile_update

                broadcast_profile_update(bidder_id)
                if previous_bidder_id and previous_bidder_id != bidder_id:
                    broadcast_profile_update(previous_bidder_id)

            transaction.on_commit(_broadcast_profile_updates)

            return bid


class AuctionCartItem(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='auction_cart_items',
    )
    auction = models.ForeignKey(
        Auction,
        on_delete=models.CASCADE,
        related_name='cart_items',
    )
    product = models.ForeignKey(
        AuctionProduct,
        on_delete=models.CASCADE,
        related_name='cart_items',
        to_field='product_id',
    )
    bid = models.OneToOneField(
        'Bid',
        on_delete=models.CASCADE,
        related_name='cart_item',
    )
    # مبلغ رزرو شده به تومان بدون اعشار
    reserved_amount = models.DecimalField(max_digits=15, decimal_places=0)
    is_active = models.BooleanField(default=True)
    outbid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'auction_cart_item'
        ordering = ['-updated_at', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'product'],
                name='uniq_auction_cart_item_user_product',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.user_id} - {self.product_id} - {self.reserved_amount}'


class AuctionVisitHistory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='auction_visit_history',
        verbose_name='کاربر',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='آدرس IP')
    auction = models.ForeignKey(
        Auction,
        on_delete=models.CASCADE,
        related_name='visit_history',
        verbose_name='مزایده',
    )
    product = models.ForeignKey(
        AuctionProduct,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='visit_history',
        verbose_name='محصول مزایده',
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='زمان بازدید')

    class Meta:
        db_table = 'auction_visit_history'
        verbose_name = 'تاریخچه بازدید مزایده'
        verbose_name_plural = 'تاریخچه بازدیدهای مزایده'
        ordering = ['-timestamp']

    @property
    def visit_scope(self) -> str:
        return 'product' if self.product_id else 'auction'

    def __str__(self) -> str:
        visitor = str(self.user) if self.user else f'{self.ip_address} (مهمان)'
        target = self.product.title if self.product_id else (self.auction.name or f'مزایده {self.auction_id}')
        return f'{visitor} - {target}'


class Bid(models.Model):
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='bids')
    product = models.ForeignKey(
        AuctionProduct,
        on_delete=models.CASCADE,
        related_name='bids',
        to_field='product_id',
    )
    # مبلغ پیشنهاد به تومان بدون اعشار
    bid_amount = models.DecimalField(max_digits=15, decimal_places=0)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='auction_bids')
    user_fullname = models.CharField(max_length=255)
    user_mobile = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'auction_bid'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.product_id} - {self.bid_amount}'
