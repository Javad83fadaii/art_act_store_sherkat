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
        for source_key, target_key in self.context_map.items():
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
    verification.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='کد تایید ثبت نام',
            body_template=(
                'سلام\n\n'
                'کد تایید ثبت نام شما: {code}\n\n'
                'در صورت عدم درخواست، این پیام را نادیده بگیرید.\n'
                'تیم ماه آکشن'
            ),
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
            body_template=(
                'سلام\n\n'
                'کد تایید ثبت نام شما: {code}\n\n'
                'در صورت عدم درخواست، این پیام را نادیده بگیرید.\n'
                'تیم ماه آکشن'
            ),
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
        'سلام\n\n'
        'مزایده {auction_name} هم‌اکنون آغاز شده است.\n\n'
        'از این لحظه امکان ثبت پیشنهاد قیمت و شرکت در رقابت برای آثار این مزایده فعال است.\n\n'
        'با آرزوی موفقیت\n'
        'تیم ماه آکشن'
    )
    auction_started.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='زمان رقابت فرا رسید؛ مزایده {auction_name} آغاز شد',
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
        'سلام\n\n'
        'مزایده {auction_name} ۲۴ ساعت دیگر آغاز می‌شود.\n\n'
        'زمان شروع: {auction_start_date}\n\n'
        'اگر قصد شرکت در این مزایده را دارید، لطفاً از آماده بودن حساب کاربری و اعتبار خود مطمئن شوید.\n\n'
        'با آرزوی موفقیت\n'
        'تیم ماه آکشن'
    )
    auction_24h.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='یادآوری: ۲۴ ساعت تا شروع مزایده {auction_name}',
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
                'auction_name': 'AUCTIONNAME',
                'auction_start_date': 'AUCTIONSTART_DATE',
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
        'سلام،\n'
        '{name} گرامی\n\n'
        'مزایده {auction_name} تنها ۱۲ ساعت دیگر به پایان می\u200cرسد.\n\n'
        'زمان پایان: {auction_end_date}\n\n'
        'با سپاس\n'
        'تیم ماه آکشن\n'
        'mahauction.com/'
    )
    auction_end.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='یادآوری: ۱۲ ساعت تا پایان مزایده {auction_name}',
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
                'auction_name': 'AUCTIONNAME',
                'name': 'NAME',
                'auction_end_date': 'AUCTIONEND_DATE',
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
        'سلام {name} گرامی\n\n'
        'مزایده {auction_name} به پایان رسیده و شما برنده نهایی مورد یا موارد زیر شده\u200cاید:\n\n'
        '{line_items_text}\n\n'
        'جمع کل صورتحساب اولیه: {formatted_total_amount} تومان\n\n'
        'این مبلغ بر اساس قیمت نهایی ثبت\u200cشده در مزایده محاسبه شده و فاکتور اولیه شما محسوب می\u200cشود.\n\n'
        'با سپاس\n'
        'تیم ماه آکشن'
    )
    auction_invoice.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.EMAIL,
            subject_template='نتیجه مزایده و صورتحساب اولیه «{auction_name}»',
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
                'sms_line_items_text': 'LINE_ITEMS_TEXT',
                'auction_name': 'AUCTIONNAME',
                'name': 'NAME',
                'line_items_text': 'LINE_ITEMS_TEXT',
                'formatted_total_amount': 'FORMAT_AMOUNTTOTAL_AMOUNT',
            },
        )
    )
    auction_invoice.register_channel(
        NotificationChannelTemplate(
            provider=NotificationProviderType.TELEGRAM,
            body_template=auction_invoice_body,
        )
    )

    return (
        verification,
        auction_started,
        auction_24h,
        auction_end,
        auction_invoice,
    )
