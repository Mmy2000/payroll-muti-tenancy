"""The employee, and the settings the app runs by."""

from __future__ import annotations

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from rest_framework.response import Response

from apps.notifications import selectors as notifications_selectors

from .... import selectors
from ....contract import AppError
from ....services import tracking
from .. import serializers as s
from .auth import employee_or_none
from .base import MONITOR, AppView, valid


def today(person):
    day = selectors.work_day(person, timezone.now())
    return day, selectors.day_punches(person, day)


class MeView(AppView):
    def get(self, request):
        actor = request._request.actor
        person = employee_or_none(self.member)
        unread = notifications_selectors.unread_count(self.member)
        if person is None:
            if not actor.can(MONITOR):
                raise AppError("no_employee", status=404)
            return Response({"username": self.member.username, "is_superuser": True,
                             "employee": None, "leave_balance": None, "today": [],
                             "active_session": None, "notifications_unread": unread})
        _day, punches = today(person)
        return Response({
            "username": self.member.username, "is_superuser": actor.can(MONITOR),
            "employee": s.employee(person, request),
            "leave_balance": selectors.balance(person, timezone.localdate().year),
            "today": s.attendance_list(punches),
            "active_session": s.session(tracking.active_session(person)),
            "notifications_unread": unread})


class ConfigView(AppView):
    def get(self, request):
        return Response(selectors.config())


class ProfileView(AppView):
    def get(self, request):
        return Response(s.profile(self.employee(), request))

    def patch(self, request):
        person = self.employee()
        data = valid(s.ProfileSerializer, request.data, partial=True)
        upload = request.FILES.get("image")
        if upload is not None and upload.size > s.MAX_IMAGE:
            raise AppError("image_too_large")
        fields = []
        if "tel" in data:
            person.phone, fields = data["tel"] or "", [*fields, "phone"]
        if "add" in data:
            person.address, fields = data["add"] or "", [*fields, "address"]
        if "image_base64" in data:
            extension, content = data["image_base64"]
            upload = ContentFile(content, name=f"photo-{get_random_string(12).lower()}"
                                               f".{extension}")
        if upload is not None:
            old = person.photo.name if person.photo else ""
            person.photo.save(upload.name, upload, save=False)
            fields.append("photo")
        if not fields:
            raise AppError("nothing_to_update")
        person.updated_by = request.user
        person.save(update_fields=[*fields, "updated_by", "updated_at"])
        if upload is not None and old:
            transaction.on_commit(lambda: person.photo.storage.delete(old))
        return Response(s.profile(person, request))
