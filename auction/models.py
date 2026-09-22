from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


def _fa_digits(value):
    if value is None:
        return ''
    return str(value).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


class Auction(models.Model):
    name = models.CharField(max_length=255, blank=True, null=True)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    products_count = models.PositiveIntegerField()
    start_reminder_24h_dispatched_at = models.DateTimeField(null=True, blank=True)
    start_notice_dispatched_at = models.DateTimeField(null=True, blank=True)
    end_notice_dispatched_at = models.DateTimeField(null=True, blank=True)
    winner_billing_dispatched_at = models.DateTimeField(null=True, blank=True)
    extension_notice_dispatched_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='زمان ارسال پیامک تمدید مزایده',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'auction_auction'
        verbose_name = 'Auction'
        verbose_name_plural = 'Auctions'
        ordering = ['-start_date']

    def __str__(self):
        return self.name or f'Auction #{self.pk}'

    def get_max_end_date(self):
        if not self.pk:
            return self.end_date
        latest_extended = (
            self.products.filter(extended_end_time__isnull=False)
            .order_by('-extended_end_time')
            .values_list('extended_end_time', flat=True)
            .first()
        )
        if latest_extended and latest_extended > self.end_date:
            return latest_extended
        return self.end_date

    def get_active_extended_products_count(self, now=None) -> int:
        if not self.pk:
            return 0
        now = now or timezone.now()
        cutoff = max(now, self.end_date)
        return self.products.filter(
            extended_end_time__gt=cutoff,
        ).count()

    @property
    def status(self) -> str:
        now = timezone.now()
        if now < self.start_date:
            return 'ready'
        if self.start_date <= now <= self.end_date:
            return 'ongoing'
        if self.get_active_extended_products_count(now) > 0:
            return 'extended'
        return 'finished'

    @staticmethod
    def _image_extensions():
        return ('.webp', '.png', '.jpg', '.jpeg')

    @staticmethod
    def _main_image_extensions():
        return ('.webp',)

    @staticmethod
    def _gallery_image_extensions():
        return ('.jpg', '.jpeg')

    def _get_priority_image_names(self):
        if not self.pk:
            return ('main', 'cover', 'primary', 'first')
        pk_text = str(self.pk).lower()
        return (pk_text, 'main', 'cover', 'primary', 'first')

    def _get_static_root(self):
        try:
            if settings.STATICFILES_DIRS:
                return Path(settings.STATICFILES_DIRS[0])
        except AttributeError:
            pass
        return Path(settings.BASE_DIR) / 'static'

    def _get_image_dir(self):
        if not self.pk:
            return None
        return self._get_static_root() / 'images' / 'action' / str(self.pk)

    def _image_sort_key(self, file_path):
        stem = file_path.stem.lower()
        priority_names = self._get_priority_image_names()

        for index, priority_name in enumerate(priority_names):
            if stem == priority_name:
                return (index, 0, file_path.name.lower())
            if stem.startswith(f'{priority_name}-') or stem.startswith(f'{priority_name}_') or stem.startswith(f'{priority_name} '):
                return (index, 1, file_path.name.lower())

        return (len(priority_names), 2, file_path.name.lower())

    def _get_image_files(self, allowed_extensions=None):
        image_dir = self._get_image_dir()
        if not image_dir or not (image_dir.exists() and image_dir.is_dir()):
            return []

        allowed_extensions = tuple(
            ext.lower() for ext in (allowed_extensions or self._image_extensions())
        )
        image_files = [
            file_path
            for file_path in image_dir.iterdir()
            if file_path.is_file() and file_path.suffix.lower() in allowed_extensions
        ]
        image_files.sort(key=self._image_sort_key)
        return image_files

    def _get_legacy_image_url(self, extensions):
        if not self.pk:
            return None

        static_root = self._get_static_root()
        for ext in extensions:
            legacy_file = static_root / 'images' / 'action' / f'{self.pk}{ext}'
            if legacy_file.exists() and legacy_file.is_file():
                return f"{settings.STATIC_URL}images/action/{legacy_file.name}"
        return None

    def _get_legacy_main_image_url(self):
        return self._get_legacy_image_url(self._main_image_extensions())

    @property
    def main_image_url(self):
        if not self.pk:
            return ''

        image_files = self._get_image_files(self._main_image_extensions())
        if image_files:
            return f"{settings.STATIC_URL}images/action/{self.pk}/{image_files[0].name}"

        legacy_main_image_url = self._get_legacy_main_image_url()
        if legacy_main_image_url:
            return legacy_main_image_url

        return ''

    @property
    def catalog_url(self):
        if not self.pk:
            return ''
        return f'{settings.STATIC_URL}catalogs/auctions/{self.pk}.pdf'


class AuctionProduct(models.Model):
    class AuthenticityStatus(models.IntegerChoices):
        CONFIRMED = 0, 'اصالت تایید شده'
        NOT_CONFIRMED = 1, 'اصالت تایید نشده'

    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='products')
    product_id = models.CharField(max_length=64, unique=True)
    lot = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_column='lot',
        verbose_name='شماره لات',
    )
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
    artist = models.ForeignKey(
        'store.Artist',
        on_delete=models.PROTECT,
        related_name='auction_products',
        null=True,
        blank=True,
    )
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

    extended_end_time = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name='زمان پایان تمدید شده',
    )
    extension_count = models.PositiveIntegerField(
        default=0,
        verbose_name='تعداد دفعات تمدید',
    )

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
    def display_title(self) -> str:
        return self.title or ''

    @property
    def pure_price(self) -> Decimal:
        price = self.current_price if self.current_price is not None else self.base_price
        try:
            return Decimal(str(price or 0))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal('0')

    @property
    def tax_amount(self) -> Decimal:
        pure = self.pure_price
        tax = pure * Decimal('0.10')
        return tax.to_integral_value(rounding=ROUND_CEILING)

    @property
    def final_price_with_tax(self) -> Decimal:
        pure = self.pure_price
        total = pure * Decimal('1.10')
        return total.to_integral_value(rounding=ROUND_CEILING)

    @staticmethod
    def _image_extensions():
        return ('.webp', '.png', '.jpg', '.jpeg')

    @staticmethod
    def _main_image_extensions():
        return ('.webp',)

    @staticmethod
    def _gallery_image_extensions():
        return ('.jpg', '.jpeg')

    def _get_priority_image_names(self):
        if not self.product_id:
            return ('main', 'cover', 'primary', 'first')
        return (
            self.product_id.lower(),
            'main',
            'cover',
            'primary',
            'first',
        )

    def _get_static_root(self):
        try:
            if settings.STATICFILES_DIRS:
                return Path(settings.STATICFILES_DIRS[0])
        except AttributeError:
            pass
        return Path(settings.BASE_DIR) / 'static'

    def _get_product_image_dir(self):
        if not self.product_id:
            return None
        return self._get_static_root() / 'images' / 'action' / self.product_id

    def _get_product_image_files(self, allowed_extensions=None):
        image_dir = self._get_product_image_dir()
        if not image_dir or not (image_dir.exists() and image_dir.is_dir()):
            return []

        allowed_extensions = tuple(
            ext.lower() for ext in (allowed_extensions or self._image_extensions())
        )
        image_files = [
            file_path
            for file_path in image_dir.iterdir()
            if file_path.is_file() and file_path.suffix.lower() in allowed_extensions
        ]
        image_files.sort(key=self._image_sort_key)
        return image_files

    def _get_legacy_image_url(self, extensions):
        if not self.product_id:
            return None

        static_root = self._get_static_root()
        for ext in extensions:
            legacy_file = static_root / 'images' / 'action' / f'{self.product_id}{ext}'
            if legacy_file.exists() and legacy_file.is_file():
                return f"{settings.STATIC_URL}images/action/{legacy_file.name}"
        return None

    def _get_legacy_main_image_url(self):
        return self._get_legacy_image_url(self._main_image_extensions())

    def _image_sort_key(self, file_path):
        stem = file_path.stem.lower()
        priority_names = self._get_priority_image_names()

        for index, priority_name in enumerate(priority_names):
            if stem == priority_name:
                return (index, 0, file_path.name.lower())
            if stem.startswith(f'{priority_name}-') or stem.startswith(f'{priority_name}_') or stem.startswith(f'{priority_name} '):
                return (index, 1, file_path.name.lower())

        return (len(priority_names), 2, file_path.name.lower())

    @property
    def main_image_url(self):
        if not self.product_id:
            return ''

        image_files = self._get_product_image_files(self._main_image_extensions())
        if not image_files:
            legacy_main_image_url = self._get_legacy_main_image_url()
            if legacy_main_image_url:
                return legacy_main_image_url
            return ''

        selected = image_files[0]
        file_name = selected.name
        if file_name:
            return f'{settings.STATIC_URL}images/action/{self.product_id}/{file_name}'
        return ''

    @property
    def gallery_images(self):
        if not self.product_id:
            return []

        image_files = self._get_product_image_files(self._gallery_image_extensions())
        if not image_files:
            return []

        images_urls = [f"{settings.STATIC_URL}images/action/{self.product_id}/{file_path.name}" for file_path in image_files]
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
        return self.extended_end_time or self.auction.end_date

    @property
    def is_extended(self) -> bool:
        if not self.extended_end_time or not self.auction_id:
            return False
        return self.extended_end_time > self.auction.end_date

    @property
    def is_in_extension(self) -> bool:
        """آیا در حال حاضر در وضعیت تمدید فعال است؟"""
        now = timezone.now()
        return bool(self.is_extended and now < self.end_time)

    @property
    def status(self) -> str:
        now = timezone.now()
        if now < self.auction.start_date:
            return 'ready'
        if now <= self.end_time:
            return 'ongoing'
        return 'finished'

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

    def get_current_step_increment(self, price=None) -> int:
        from .services import get_current_step_increment
        target_price = price if price is not None else (self.current_price or self.base_price)
        return get_current_step_increment(target_price)

    def get_min_next_bid(self) -> int:
        from .services import get_min_next_bid
        target_price = self.current_price or self.base_price
        return get_min_next_bid(target_price)

    @property
    def current_step_increment(self) -> int:
        return self.get_current_step_increment()

    def place_bid(self, user, amount=None):
        user_model = get_user_model()

        with transaction.atomic():
            product = (
                AuctionProduct.objects
                .select_related('auction')
                .select_for_update()
                .get(pk=self.pk)
            )

            now = timezone.now()
            if now < product.auction.start_date:
                raise ValidationError('مزایده هنوز آغاز نشده است.')
            if now > product.end_time:
                raise ValidationError('مهلت ثبت پیشنهاد برای این اثر به پایان رسیده است.')

            # ارزیابی مجدد حداقل پیشنهاد بر اساس پله جاری پس از اعمال قفل دیتابیس
            min_next = Decimal(str(product.get_min_next_bid()))

            # در صورت عدم ارسال مبلغ، حداقل پیشنهاد بعدی پله جاری منظور می‌شود
            raw = (amount or '').strip() if isinstance(amount, str) else amount
            if raw in (None, ''):
                bid_amount = min_next
            else:
                try:
                    bid_amount = Decimal(str(raw))
                except (InvalidOperation, TypeError, ValueError):
                    raise ValidationError('مبلغ پیشنهاد نامعتبر است.')

            if bid_amount <= 0:
                raise ValidationError('مبلغ پیشنهاد باید بزرگتر از صفر باشد.')

            if bid_amount < min_next:
                raise ValidationError(f'حداقل پیشنهاد بعدی {_fa_digits(f"{int(min_next):,}")} تومان است.')

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

            # منطق تمدید خودکار (Soft Close / Overtime):
            # اگر در ۶ ساعت پایانی مانده به اتمام مزایده پیشنهادی روی اثری ثبت شد،
            # زمان پایان همان محصول باید به مدت ۶ ساعت از لحظه ثبت بید تمدید شود.
            time_remaining = product.end_time - now
            soft_close_window = timezone.timedelta(hours=6)
            soft_close_extension = timezone.timedelta(hours=6)

            update_fields = ['current_price', 'winner', 'updated_at']
            if time_remaining <= soft_close_window:
                new_end_time = now + soft_close_extension
                if not product.extended_end_time or new_end_time > product.extended_end_time:
                    product.extended_end_time = new_end_time
                    product.extension_count = (product.extension_count or 0) + 1
                    update_fields.extend(['extended_end_time', 'extension_count'])

            product.current_price = bid_amount
            product.winner = bidder
            product.save(update_fields=update_fields)

            bidder.refresh_current_credit()
            if previous_bidder is not None:
                previous_bidder.refresh_current_credit()

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
