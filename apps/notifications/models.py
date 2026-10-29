"""What a member is told: a leave request to decide, their leave decided, an incentive given,
their pay paid… (PayRole `Notif.Notification`). The mobile app polls them (`/api/v1/
notifications`); there is no push.

The text is written once, in the client's language, when the event happens (PayRole's were
Arabic text too)."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantScopedModel


class Kind(models.TextChoices):
    LEAVE_REQUEST = "leave_request", _("Leave to decide")
    LEAVE_WITHDRAWN = "leave_withdrawn", _("Leave request withdrawn")
    LEAVE_ADDED = "leave_added", _("Leave entered")
    LEAVE_APPROVED = "leave_approved", _("Leave approved")
    LEAVE_REJECTED = "leave_rejected", _("Leave rejected")
    LEAVE_CANCELLED = "leave_cancelled", _("Leave cancelled")
    PERMISSION_ADDED = "permission_added", _("Hourly leave entered")
    PERMISSION_CANCELLED = "permission_cancelled", _("Hourly leave cancelled")
    MOVEMENT = "movement", _("Pay movement")
    SALARY_PAID = "salary_paid", _("Pay paid")


class Notification(TenantScopedModel):
    member = models.ForeignKey("iam.Membership", on_delete=models.CASCADE,
                               related_name="notifications")
    kind = models.CharField(max_length=30, choices=Kind.choices)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=300, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["tenant", "member", "read_at"],
                                name="notifications_unread_idx")]

    def __str__(self):
        return self.title
