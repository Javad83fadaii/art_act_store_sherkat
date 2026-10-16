from django import template
from django.utils import timezone
from datetime import datetime
from jalali_date import datetime2jalali, date2jalali
from decimal import Decimal, InvalidOperation

register = template.Library()


PERSIAN_DIGITS_TRANS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def _to_persian_digits(value):
    return str(value).translate(PERSIAN_DIGITS_TRANS)


def _format_amount(value):
    if value in (None, ''):
        return ''

    normalized = str(value).strip().replace(',', '').replace('٬', '')

    try:
        amount = Decimal(normalized)
    except (InvalidOperation, TypeError, ValueError):
        return _to_persian_digits(value)

    if amount == amount.to_integral_value():
        return _to_persian_digits(f'{int(amount):,}')

    return _to_persian_digits(f'{amount:,.2f}'.rstrip('0').rstrip('.'))


@register.filter(name='jalali_date')
def jalali_date(value):
    if not value:
        return ''
    try:
        if isinstance(value, datetime):
            j_date = datetime2jalali(value)
            return j_date.strftime('%Y/%m/%d %H:%M')
        else:
            j_date = date2jalali(value)
            return j_date.strftime('%Y/%m/%d')
    except Exception:
        return str(value)


@register.filter(name='jalali_date_short')
def jalali_date_short(value):
    if not value:
        return ''
    try:
        if isinstance(value, datetime):
            j_date = datetime2jalali(value)
            return j_date.strftime('%Y/%m/%d')
        else:
            j_date = date2jalali(value)
            return j_date.strftime('%Y/%m/%d')
    except Exception:
        return str(value)


@register.filter(name='dollar_format')
def dollar_format(value):
    if value is None:
        return ''
    try:
        amount = Decimal(str(value))
        return f'${amount:,.2f}'
    except Exception:
        return str(value)


@register.filter(name='dollar_format_no_decimal')
def dollar_format_no_decimal(value):
    if value is None:
        return ''
    try:
        amount = int(Decimal(str(value)))
        return f'${amount:,}'
    except Exception:
        return str(value)


@register.filter(name='fa_digits')
def fa_digits(value):
    if value is None:
        return ''
    return _to_persian_digits(value)


@register.filter(name='fa_price')
def fa_price(value):
    return _format_amount(value)


@register.simple_tag
def get_rank_medal(rank):
    if rank == 1:
        return '🥇'
    elif rank == 2:
        return '🥈'
    elif rank == 3:
        return '🥉'
    return ''
