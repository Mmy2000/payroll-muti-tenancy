"""Telling members something (apps/notifications/handlers.py says what, when), and reading it.

A notification is written once, in the client's language (the mobile app shows the text as it
is). Whoever caused the event is not told about it (PayRole: the acting user)."""

from __future__ import annotations

from django.db.models import QuerySet
from django.utils import timezone, translation

from . import realtime
from .models import Notification

PAGE = 30  # the mobile app's page


def _language() -> str:
    from apps.org.models import TenantProfile

    return TenantProfile.objects.values_list("locale", flat=True).first() or "ar"


def notify(members, kind: str, title, body="", *, url: str = "", by=None) -> int:
    """`title` and `body` are lazy texts (or functions returning them), rendered in the
    client's language. Returns how many members were told."""
    by_id = getattr(getattr(by, "membership", by), "pk", None)
    targets = [m for m in members if m is not None and m.pk != by_id]
    if not targets:
        return 0
    with translation.override(_language()):
        title_text = str(title() if callable(title) else title)[:200]
        body_text = str(body() if callable(body) else body)[:500]
    members = {m.pk: m for m in targets}
    Notification.objects.bulk_create([
        Notification(member=member, kind=kind, title=title_text, body=body_text, url=url)
        for member in members.values()])
    realtime.announce(next(iter(members.values())).tenant_id, members)
    return len(targets)


def for_member(member) -> QuerySet:
    return Notification.objects.filter(member=member)


def unread_count(member) -> int:
    return for_member(member).filter(read_at__isnull=True).count()


def mark_read(member, ids=None) -> int:
    rows = for_member(member).filter(read_at__isnull=True)
    if ids:
        rows = rows.filter(pk__in=ids)
    marked = rows.update(read_at=timezone.now())
    if marked:
        realtime.announce(member.tenant_id, [member.pk])  # the member's other tabs follow
    return marked


def clean_up(*, read_days: int = 90, unread_days: int = 365) -> int:
    now = timezone.now()
    gone, _detail = Notification.objects.filter(
        read_at__lt=now - timezone.timedelta(days=read_days)).delete()
    old, _detail = Notification.objects.filter(
        created_at__lt=now - timezone.timedelta(days=unread_days)).delete()
    return gone + old
