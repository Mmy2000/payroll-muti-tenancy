from django import template

register = template.Library()


@register.inclusion_tag("audit/_history_link.html", takes_context=True)
def history_link(context, record):
    """{% history_link employee %}: a "History" link to the record's changes, for members who
    may see them. The table comes from the model, never typed into a template."""
    return {"request": context.get("request"), "table": record._meta.db_table,
            "row": record.pk}
