from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from notifications.enums import NotificationProviderType
from notifications.utils import render_text_template


@dataclass(slots=True)
class RenderedNotificationTemplate:
    """Rendered notification content."""

    subject: str
    body: str


@dataclass(slots=True)
class ResolvedChannelTemplate:
    """Resolved provider-specific template payload."""

    subject: str
    body: str
    context: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(slots=True)
class NotificationChannelTemplate:
    """Channel-specific notification template definition."""

    provider: NotificationProviderType
    subject_template: str = ''
    body_template: str = ''
    metadata: Mapping[str, Any] = field(default_factory=dict)
    context_map: Mapping[str, str] = field(default_factory=dict)

    def render(self, context: Mapping[str, Any] | None = None) -> ResolvedChannelTemplate:
        resolved_context = self._build_context(context)
        return ResolvedChannelTemplate(
            subject=render_text_template(self.subject_template, resolved_context),
            body=render_text_template(self.body_template, resolved_context),
            context=resolved_context,
            metadata=dict(self.metadata),
        )

    def _build_context(self, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        resolved_context = dict(context or {})
        for source_key, target_keys in self.context_map.items():
            targets = (target_keys,) if isinstance(target_keys, str) else tuple(target_keys)
            for target_key in targets:
                if source_key in resolved_context and target_key not in resolved_context:
                    resolved_context[target_key] = resolved_context[source_key]
        return resolved_context


@dataclass(slots=True)
class NotificationTemplate:
    """In-memory template definition."""

    key: str
    default_providers: tuple[NotificationProviderType, ...] = field(default_factory=tuple)
    channels: dict[NotificationProviderType, NotificationChannelTemplate] = field(default_factory=dict)

    def render(self, context: Mapping[str, Any] | None = None) -> RenderedNotificationTemplate:
        providers = self.available_providers
        if not providers:
            raise KeyError(f'Notification template "{self.key}" does not have any configured providers.')
        channel_template = self.get_channel_template(providers[0])
        rendered = channel_template.render(context)
        return RenderedNotificationTemplate(subject=rendered.subject, body=rendered.body)

    @property
    def available_providers(self) -> tuple[NotificationProviderType, ...]:
        if self.default_providers:
            return self.default_providers
        return tuple(self.channels.keys())

    def register_channel(self, channel_template: NotificationChannelTemplate) -> None:
        self.channels[channel_template.provider] = channel_template

    def get_channel_template(self, provider: NotificationProviderType) -> NotificationChannelTemplate:
        try:
            return self.channels[provider]
        except KeyError as exc:
            raise KeyError(
                f'Notification template "{self.key}" is not configured for provider "{provider.value}".'
            ) from exc


class NotificationTemplateRegistry:
    """Registry for code-defined notification templates."""

    def __init__(self, templates: Iterable[NotificationTemplate] | None = None) -> None:
        self._templates: dict[str, NotificationTemplate] = {}
        for template in templates or get_default_notification_templates():
            self.register(template)

    def register(self, template: NotificationTemplate) -> None:
        self._templates[template.key] = template

    def get(self, key: str) -> NotificationTemplate:
        if key not in self._templates:
            raise KeyError(f'Notification template "{key}" is not registered.')
        return self._templates[key]


def get_default_notification_templates() -> tuple[NotificationTemplate, ...]:
    """Return the built-in provider-aware notification template registry."""
    verification = NotificationTemplate(
        key='verification',
        default_providers=(
            NotificationProviderType.EMAIL,
            NotificationProviderType.SMS,
            NotificationProviderType.TELEGRAM,
        ),
    )
    verification_body = (
        'سلام\n\n'
        'کد تایید ثبت نام شما: {code}\n\n'
        'حراج هنری ماه\n'
        'Mahauction.com'
    )
    verification.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='کد تایید ثبت نام',
            body_template=verification_body,
        )
    )
    verification.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.SMS,
            metadata={
                'sms_pattern': 'verification',
            },
            context_map={
                'code': 'CODE',
            },
        )
    )
    verification.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.TELEGRAM,
            body_template=verification_body,
        )
    )

    signup_welcome = NotificationTemplate(
        key='signup_welcome',
        default_providers=(
            NotificationProviderType.EMAIL,
            NotificationProviderType.SMS,
            NotificationProviderType.TELEGRAM,
        ),
    )
    signup_welcome_email_body = (
        '{name} عزیز\n\n'
        'ثبت نام شما با موفقیت انجام شد.\n'
        'لطفاً ایمیل خود را تأیید و فرآیند ثبت‌نام را تکمیل کنید.\n'
        'از حضور و همراهی شما سپاسگزاریم.\n\n'
        'Mahauction.com'
    )
    signup_welcome_sms_body = (
        'خوش آمد گویی ثبت نام\n'
        '{name} عزیز\n'
        'ثبت نام شما با موفقیت انجام شد\n'
        'لطفاً شماره خود را تأیید و فرآیند ثبت‌نام را تکمیل کنید.\n'
        'از حضور و همراهی شما سپاسگزاریم\n'
        'Mahauction.com'
    )
    signup_welcome.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='خوش آمد گویی ثبت نام',
            body_template=signup_welcome_email_body,
        )
    )
    signup_welcome.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.SMS,
            metadata={
                'sms_pattern': 'signup_welcome',
            },
            context_map={
                'name': 'NAME',
            },
            body_template=signup_welcome_sms_body,
        )
    )
    signup_welcome.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.TELEGRAM,
            body_template=signup_welcome_email_body,
        )
    )

    auction_started = NotificationTemplate(
        key='auction_started',
        default_providers=(
            NotificationProviderType.EMAIL,
            NotificationProviderType.SMS,
            NotificationProviderType.TELEGRAM,
        ),
    )
    auction_started_email_body = (
        'با درود و احترام\n'
        '{name} عزیز\n\n'
        'مزایده {auction_name} هم‌اکنون آغاز شده است\n'
        'از این لحظه امکان ثبت پیشنهاد قیمت و شرکت در رقابت برای آثار این مزایده فعال است.\n\n'
        'با آرزوی موفقیت\n'
        'حراج هنری ماه\n'
        'Mahauction.com'
    )
    auction_started.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='شروع مزایده',
            body_template=auction_started_email_body,
        )
    )
    auction_started.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.SMS,
            metadata={
                'sms_pattern': 'auction_started',
            },
            context_map={
                'name': 'NAME',
                'auction_name': 'AUCTIONNAME',
            },
        )
    )
    auction_started.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.TELEGRAM,
            body_template=auction_started_email_body,
        )
    )

    auction_24h = NotificationTemplate(
        key='auction_24h',
        default_providers=(
            NotificationProviderType.EMAIL,
            NotificationProviderType.SMS,
            NotificationProviderType.TELEGRAM,
        ),
    )
    auction_24h_email_body = (
        'با درود و احترام\n\n'
        'تنها ۲۴ ساعت تا آغاز مزایده {auction_name} باقی مانده است.\n'
        'پیشنهاد می‌کنیم پیش از آغاز مزایده، آثار موردنظر خود را بررسی کرده و برای شرکت در رقابت آماده باشید.\n\n'
        'با احترام\n'
        'حراج هنری ماه\n'
        'Mahauction.com'
    )
    auction_24h.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='یادآوری شروع مزایده',
            body_template=auction_24h_email_body,
        )
    )
    auction_24h.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.SMS,
            metadata={
                'sms_pattern': 'auction_24h',
            },
            context_map={
                'auction_name': ('AUCTION_NAME', 'AUCTIONNAME'),
                'auction_start_date': ('AUCTIONSTART_DATE', 'AUCTION_START_DATE'),
            },
        )
    )
    auction_24h.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.TELEGRAM,
            body_template=auction_24h_email_body,
        )
    )

    auction_end = NotificationTemplate(
        key='auction_end',
        default_providers=(
            NotificationProviderType.EMAIL,
            NotificationProviderType.SMS,
            NotificationProviderType.TELEGRAM,
        ),
    )
    auction_end_body = (
        'با درود و احترام\n\n'
        'تنها ۱۲ ساعت تا پایان مزایده {auction_name} باقی مانده است.\n'
        'اگر اثر موردنظر خود را انتخاب کرده‌اید، فرصت ثبت یا افزایش پیشنهاد قیمت تا پایان مزایده همچنان برقرار است.\n\n'
        'با احترام\n'
        'حراج هنری ماه'
    )
    auction_end.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='یادآوری پایان مزایده',
            body_template=auction_end_body,
        )
    )
    auction_end.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.SMS,
            metadata={
                'sms_pattern': 'auction_end',
            },
            context_map={
                'auction_name': ('AUCTIONNAME', 'AUCTION_NAME'),
                'name': 'NAME',
                'auction_end_date': ('AUCTIONEND_DATE', 'AUCTION_END_DATE'),
            },
        )
    )
    auction_end.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.TELEGRAM,
            body_template=auction_end_body,
        )
    )

    auction_invoice = NotificationTemplate(
        key='auction_Invoice',
        default_providers=(
            NotificationProviderType.EMAIL,
            NotificationProviderType.SMS,
            NotificationProviderType.TELEGRAM,
        ),
    )
    auction_invoice_body = (
        'با درود و احترام\n\n'
        'با خرسندی، به اطلاع می‌رساند پیشنهاد شما برای اثر {product_title} در مزایده {auction_name} به‌عنوان بالاترین پیشنهاد ثبت شده و این اثر به شما تعلق گرفته است.\n\n'
        'مشخصات خرید\n'
        'شماره اثر: {lot_number}\n'
        'مبلغ نهایی پیشنهاد: {formatted_total_amount}\n\n'
        'صورتحساب اولیه خرید شما صادر شده است. لطفاً برای مشاهده جزئیات صورتحساب و تکمیل فرآیند پرداخت، به حساب کاربری خود مراجعه کنید.\n\n'
        'از اعتماد و همراهی شما با حراج هنری ماه سپاسگزاریم.\n\n'
        'با احترام\n'
        'حراج هنری ماه\n'
        'Mahauction.com'
    )
    auction_invoice.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='نتیجه مزایده و صورتحساب اولیه',
            body_template=auction_invoice_body,
        )
    )
    auction_invoice.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.SMS,
            metadata={
                'sms_pattern': 'auction_Invoice',
            },
            context_map={
                'product_title': 'PRODUCT_TITLE',
                'auction_name': ('AUCTION_NAME', 'AUCTIONNAME'),
                'name': 'NAME',
                'lot_number': 'LOT_NUMBER',
                'formatted_total_amount': ('FINAL_BID_AMOUNT', 'FORMAT_AMOUNTTOTAL_AMOUNT'),
                'line_items_text': 'LINE_ITEMS_TEXT',
                'sms_line_items_text': 'LINE_ITEMS_TEXT',
            },
        )
    )
    auction_invoice.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.TELEGRAM,
            body_template=auction_invoice_body,
        )
    )

    add_bid = NotificationTemplate(
        key='add_bid',
        default_providers=(
            NotificationProviderType.EMAIL,
            NotificationProviderType.SMS,
        ),
    )
    add_bid_body = (
        'با درود و احترام\n\n'
        'پیشنهاد قیمت شما برای اثر {product_title} با موفقیت ثبت شد.\n'
        'مبلغ پیشنهاد: {formatted_bid_amount}\n'
        'شماره اثر: {lot_number}\n'
        'مزایده: {auction_name}\n\n'
        'این پیشنهاد تا زمان ثبت پیشنهاد بالاتر، در رقابت معتبر خواهد بود.\n\n'
        'با احترام\n'
        'حراج هنری ماه\n'
        'Mahauction.com'
    )
    add_bid.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='ثبت پیشنهاد قیمت',
            body_template=add_bid_body,
        )
    )
    add_bid.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.SMS,
            metadata={
                'sms_pattern': 'add_bid',
            },
            context_map={
                'name': 'NAME',
                'product_title': 'PRODUCT_TITLE',
                'formatted_bid_amount': 'FORMAT_AMOUNTBIDBID_AMOUNT',
                'lot_number': 'LOT_NUMBER',
                'auction_name': 'AUCTION_NAME',
            },
        )
    )

    dell_bid = NotificationTemplate(
        key='dell_bid',
        default_providers=(
            NotificationProviderType.EMAIL,
            NotificationProviderType.SMS,
        ),
    )
    dell_bid_body = (
        'با درود و احترام\n\n'
        'پیشنهاد بالاتری برای اثر {product_title} ثبت شده است و اثر از سبد مزایده شما خارج شده است.\n'
        'در صورت تمایل، می‌توانید با ثبت پیشنهاد جدید، مجدداً در رقابت این اثر شرکت کنید.\n\n'
        'با احترام\n'
        'حراج هنری ماه\n'
        'Mahauction.com'
    )
    dell_bid.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='خروج اثر از سبد مزایده',
            body_template=dell_bid_body,
        )
    )
    dell_bid.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.SMS,
            metadata={
                'sms_pattern': 'dell_bid',
            },
            context_map={
                'name': 'NAME',
                'product_title': 'PRODUCT_TITLE',
                'formatted_latest_bid_amount': 'FORMAT_AMOUNTLATEST_BIDBID_AMOUNT',
            },
        )
    )

    return (
        verification,
        signup_welcome,
        auction_started,
        auction_24h,
        auction_end,
        auction_invoice,
        add_bid,
        dell_bid,
    )
