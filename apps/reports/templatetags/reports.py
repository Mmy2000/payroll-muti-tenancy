from django import template

register = template.Library()


@register.filter
def param(params: dict, key: str):
    """{{ params|param:spec.key }}: a filter's parsed value."""
    return params.get(key)


@register.filter
def minutes(value) -> str:
    """125 → "2:05"; nothing → ""."""
    if value in (None, ""):
        return ""
    value = int(value)
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value) // 60}:{abs(value) % 60:02d}"
