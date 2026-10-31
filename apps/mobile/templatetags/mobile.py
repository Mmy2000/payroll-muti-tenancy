"""The app's card on the employee's page, so the employees app needn't know about QR codes."""

from django import template

from apps.mobile import devices, qr

register = template.Library()


@register.inclusion_tag("mobile/_qr_card.html", takes_context=True)
def app_qr_card(context, employee) -> dict:
    allowed = context["request"].actor.can(qr.MANAGE, branch=employee.branch_id)
    if not allowed:
        return {"allowed": False}
    link = qr.active(employee)
    return {"allowed": True, "employee": employee, "active": link,
            "devices": list(devices.signed_in(employee.member)) if employee.member_id else []}
