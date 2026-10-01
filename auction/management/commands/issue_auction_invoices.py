from decimal import Decimal
import sys

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from auction.models import Auction, AuctionInvoice
from auction.services import (
    ensure_products_have_finished_winners,
    issue_auction_invoices_and_billing,
)
from auction.tasks import _format_amount


class Command(BaseCommand):
    help = (
        'بررسی و صدور قطعی فاکتورهای رسمی برندگان مزایده و ارسال پیامک/ایمیل صورت‌حساب توسط مدیر سامانه روی سرور.\n'
        'استفاده: python manage.py issue_auction_invoices <auction_id> [گزینه‌ها]'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'auction_id',
            nargs='?',
            type=int,
            help='شناسه عددی مزایده (Auction ID)',
        )
        parser.add_argument(
            '--list',
            action='store_true',
            dest='list_auctions',
            help='نمایش لیست مزایده‌های پایان‌یافته و وضعیت فاکتورهای آن‌ها',
        )
        parser.add_argument(
            '--preview',
            '--dry-run',
            action='store_true',
            dest='preview',
            help='پیش‌نمایش برندگان، اقلام و مبالغ فاکتور بدون ذخیره در دیتابیس یا ارسال پیامک',
        )
        parser.add_argument(
            '-y',
            '--yes',
            action='store_true',
            dest='force_yes',
            help='تایید خودکار و عدم درخواست تایید تعاملی (y/n)',
        )
        parser.add_argument(
            '--skip-notifications',
            action='store_true',
            dest='skip_notifications',
            help='صدور فاکتورها در دیتابیس بدون ارسال پیامک یا ایمیل به برندگان',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            dest='force',
            help='اجرای صدور فاکتور حتی اگر وضعیت مزایده هنوز رسماً finished نشده باشد',
        )

    def handle(self, *args, **options):
        if options.get('list_auctions'):
            self._list_finished_auctions()
            return

        auction_id = options.get('auction_id')
        if not auction_id:
            self.stdout.write(self.style.WARNING('لطفاً شناسه مزایده را مشخص کنید یا از فلگ --list استفاده نمایید.'))
            self.stdout.write('مثال: python manage.py issue_auction_invoices 12')
            self.stdout.write('یا:    python manage.py issue_auction_invoices --list')
            return

        try:
            auction = Auction.objects.get(pk=auction_id)
        except Auction.DoesNotExist:
            raise CommandError(f'مزایده‌ای با شناسه {auction_id} یافت نشد.')

        is_preview = options.get('preview', False)
        force_yes = options.get('force_yes', False)
        skip_notifications = options.get('skip_notifications', False)
        force = options.get('force', False)

        # نمایش پیش‌نمایش برندگان و اقلام
        self._display_auction_summary(auction)

        if is_preview:
            self.stdout.write(self.style.NOTICE('\n[حالت پیش‌نمایش] هیچ تغییری در دیتابیس اعمال نشد و هیچ اطلاعیه‌ای ارسال نگردید.'))
            return

        # بررسی اینکه آیا قبلاً فاکتور صادر شده است یا خیر
        if auction.invoices_dispatched_at is not None and not force:
            existing_count = AuctionInvoice.objects.filter(auction=auction).count()
            self.stdout.write(self.style.WARNING(
                f'\nتوجه: برای این مزایده قبلاً در تاریخ {auction.invoices_dispatched_at} تعداد {existing_count} فاکتور صادر شده است.'
            ))
            if auction.winner_billing_dispatched_at is not None:
                self.stdout.write(self.style.WARNING('پیامک و ایمیل صورت‌حساب نیز قبلاً ارسال شده است.'))
            
            if not force_yes:
                confirm = input('\nآیا مایل به بازتولید فاکتورها / ارسال مجدد هستید؟ [y/N]: ').strip().lower()
                if confirm not in ('y', 'yes', 'بله'):
                    self.stdout.write(self.style.NOTICE('عملیات لغو شد.'))
                    return

        # درخواست تایید تعاملی در صورت عدم استفاده از -y
        elif not force_yes:
            notif_msg = 'بدون ارسال پیامک/ایمیل' if skip_notifications else 'همراه با ارسال پیامک و ایمیل صورت‌حساب به برندگان'
            self.stdout.write(self.style.WARNING(f'\nآماده صدور فاکتورها ({notif_msg}).'))
            confirm = input('آیا از صدور نهایی فاکتورها اطمینان دارید؟ [y/N]: ').strip().lower()
            if confirm not in ('y', 'yes', 'بله'):
                self.stdout.write(self.style.NOTICE('عملیات لغو شد. هیچ تغییری در دیتابیس اعمال نگردید.'))
                return

        # اجرای صدور فاکتورها و ارسال پیامک/ایمیل
        self.stdout.write(self.style.NOTICE('\nدر حال پردازش و ثبت فاکتورها در پایگاه داده...'))
        try:
            result = issue_auction_invoices_and_billing(
                auction,
                send_notifications=not skip_notifications,
                force=force,
            )
        except Exception as e:
            raise CommandError(f'خطا در صدور فاکتورها: {e}')

        invoices = result.get('invoices', [])
        notif_count = result.get('notifications_sent', 0)
        notif_errors = result.get('notification_errors', [])

        self.stdout.write(self.style.SUCCESS(
            f'\n✓ با موفقیت تعداد {len(invoices)} فاکتور رسمی صادر گردید.'
        ))

        for inv in invoices:
            user_name = inv.user.get_full_name() or inv.user.phone_number
            self.stdout.write(
                f'  - شماره فاکتور: {inv.invoice_number} | خریدار: {user_name} | مبلغ کل: {_format_amount(inv.total_amount)} تومان'
            )

        if not skip_notifications:
            self.stdout.write(self.style.SUCCESS(
                f'✓ تعداد {notif_count} اطلاع‌رسانی پیامکی و ایمیلی صورت‌حساب ارسال شد.'
            ))
            if notif_errors:
                self.stdout.write(self.style.WARNING(f'خطا در ارسال {len(notif_errors)} پیامک/ایمیل:'))
                for err in notif_errors:
                    self.stdout.write(self.style.ERROR(f"  - {err['user']}: {err['error']}"))
        else:
            self.stdout.write(self.style.NOTICE('اطلاع‌رسانی پیامکی/ایمیلی طبق درخواست شما نادیده گرفته شد (--skip-notifications).'))

    def _list_finished_auctions(self):
        """نمایش لیست مزایده‌های پایان‌یافته همراه با وضعیت فاکتورها"""
        now = timezone.now()
        auctions = Auction.objects.filter(end_date__lt=now).order_by('-end_date')

        if not auctions.exists():
            self.stdout.write('هیچ مزایده پایان‌یافته‌ای یافت نشد.')
            return

        self.stdout.write(self.style.SUCCESS('\n=== لیست مزایده‌های پایان‌یافته ===\n'))
        header = f"{'شناسه':<6} | {'عنوان مزایده':<30} | {'تاریخ پایان':<18} | {'وضعیت فاکتورها':<26} | {'اطلاع‌رسانی'}"
        self.stdout.write(header)
        self.stdout.write('-' * 95)

        for a in auctions:
            inv_count = AuctionInvoice.objects.filter(auction=a).count()
            if a.invoices_dispatched_at:
                inv_status = self.style.SUCCESS(f'صادر شده ({inv_count} فاکتور)')
            else:
                inv_status = self.style.WARNING('منتظر تایید و صدور')

            if a.winner_billing_dispatched_at:
                notif_status = self.style.SUCCESS('ارسال شده')
            else:
                notif_status = self.style.NOTICE('ارسال نشده')

            end_str = timezone.localtime(a.end_date).strftime('%Y-%m-%d %H:%M') if a.end_date else '-'
            title = (a.name or f'مزایده {a.id}')[:28]
            self.stdout.write(f"{a.id:<6} | {title:<30} | {end_str:<18} | {inv_status:<35} | {notif_status}")

        self.stdout.write('\nجهت بررسی یک مزایده: python manage.py issue_auction_invoices <ID> --preview')
        self.stdout.write('جهت صدور فاکتورها:   python manage.py issue_auction_invoices <ID>\n')

    def _display_auction_summary(self, auction):
        """نمایش جزئیات برندگان، قیمت‌ها و اقلام فروش‌نرفته"""
        self.stdout.write(self.style.SUCCESS(f'\n======================================================'))
        self.stdout.write(self.style.SUCCESS(f' بررسی مزایده شناسه {auction.id}: «{auction.name or auction.id}»'))
        self.stdout.write(self.style.SUCCESS(f'======================================================'))
        self.stdout.write(f"وضعیت: {auction.status}")
        self.stdout.write(f"تاریخ شروع: {timezone.localtime(auction.start_date).strftime('%Y-%m-%d %H:%M')}")
        self.stdout.write(f"تاریخ پایان: {timezone.localtime(auction.end_date).strftime('%Y-%m-%d %H:%M')}")

        products = list(auction.products.select_related('winner', 'artist').all().order_by('lot', 'pk'))
        ensure_products_have_finished_winners(products)

        sold_items = [p for p in products if p.winner]
        unsold_items = [p for p in products if not p.winner]

        self.stdout.write(self.style.NOTICE(f'\n--- اقلام برنده شده ({len(sold_items)} اثر) ---'))

        if not sold_items:
            self.stdout.write('هیچ اثری در این مزایده پیشنهادی دریافت نکرده و برنده ندارد.')
        else:
            header = f"{'لات':<5} | {'کد اثر':<10} | {'نام اثر':<24} | {'برنده':<20} | {'موبایل':<13} | {'چکش‌خورده':<14} | {'۱۰٪ حق‌العمل':<12} | {'مبلغ کل'}"
            self.stdout.write(header)
            self.stdout.write('-' * 110)

            total_hammer_sum = Decimal('0')
            total_premium_sum = Decimal('0')
            total_sum = Decimal('0')

            for p in sold_items:
                winner = p.winner
                w_name = (winner.get_full_name() or winner.full_name or winner.phone_number or '-')[:18]
                w_phone = getattr(winner, 'phone_number', '-') or '-'
                hammer = Decimal(str(p.pure_price or 0))
                premium = (hammer * Decimal('0.10')).quantize(Decimal('1'))
                item_total = hammer + premium

                total_hammer_sum += hammer
                total_premium_sum += premium
                total_sum += item_total

                lot_str = str(p.lot or '-')
                title = (p.title or '')[:22]
                self.stdout.write(
                    f"{lot_str:<5} | {p.product_id:<10} | {title:<24} | {w_name:<20} | {w_phone:<13} | "
                    f"{_format_amount(hammer):<14} | {_format_amount(premium):<12} | {_format_amount(item_total)}"
                )

            self.stdout.write('-' * 110)
            self.stdout.write(
                f"{'مجموع:':<78} | {_format_amount(total_hammer_sum):<14} | {_format_amount(total_premium_sum):<12} | "
                f"{self.style.SUCCESS(_format_amount(total_sum) + ' تومان')}"
            )

        if unsold_items:
            self.stdout.write(self.style.NOTICE(f'\n--- اقلام بدون پیشنهاد ({len(unsold_items)} اثر) ---'))
            for p in unsold_items:
                self.stdout.write(f"  - کد: {p.product_id} | لات: {p.lot or '-'} | «{p.title}» | قیمت پایه: {_format_amount(p.base_price)} تومان")

        buyers_count = len({p.winner_id for p in sold_items if p.winner_id})
        self.stdout.write(self.style.NOTICE(f'\nخلاصه:'))
        self.stdout.write(f'  • کل آثار: {len(products)}')
        self.stdout.write(f'  • فروخته شده: {len(sold_items)}')
        self.stdout.write(f'  • بدون خریدار: {len(unsold_items)}')
        self.stdout.write(f'  • تعداد خریداران متمایز (فاکتورها): {buyers_count}')
