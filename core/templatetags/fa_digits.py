from decimal import Decimal, InvalidOperation

from django import template

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


@register.filter(name='fa_digits')
def fa_digits(value):
    if value is None:
        return ''
    return _to_persian_digits(value)


@register.filter(name='fa_price')
def fa_price(value):
    return _format_amount(value)

