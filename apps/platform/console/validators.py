"""The rules on provisioning a client."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.translation import gettext as _

from apps.core.errors import ValidationError

if TYPE_CHECKING:
    from .services.provisioning import ProvisionTenantCommand


def check_link(user, cmd: ProvisionTenantCommand) -> None:
    """An existing login becomes this workspace's owner only when asked, never a staff login,
    and never with a password typed for it (it would be ignored)."""
    if user.is_platform_staff:
        raise ValidationError(_("Platform staff logins can't own a workspace. Use another email."),
                              fields={"owner_email": [_("A platform staff login.")]},
                              code="TENANT_OWNER_IS_STAFF")
    if not cmd.link_existing_owner:
        raise ValidationError(
            _("This email already has a login. Add this workspace to that login, or use "
              "another email."), fields={"owner_email": [_("Already has a login.")]},
            code="TENANT_OWNER_EXISTS")
    if cmd.owner_password:
        raise ValidationError(
            _("That login keeps its own password: leave the password empty."),
            fields={"owner_password": [_("Leave empty.")]}, code="TENANT_OWNER_PASSWORD")
