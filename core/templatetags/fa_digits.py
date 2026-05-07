from django import template

register = template.Library()


@register.filter(name='fa_digits')
def fa_digits(value):
    if value is None:
        return ''
    return str(value).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))

