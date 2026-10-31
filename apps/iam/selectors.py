"""What the users and roles screens read, and a user's membership in this client."""

from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, OuterRef, QuerySet, Subquery

from .catalog import permissions
from .models import Membership, MembershipStatus, Role, SignInEvent, SignInOutcome


def active_membership(user) -> Membership | None:
    return (Membership.objects.select_related("user", "default_branch")
            .filter(user=user, status=MembershipStatus.ACTIVE).first())


def active_member_count() -> int:
    return Membership.objects.filter(status=MembershipStatus.ACTIVE).count()


def members_by_name() -> QuerySet[Membership]:
    return Membership.objects.select_related("user").order_by("username")


def member_with_user(pk) -> Membership | None:
    return Membership.objects.select_related("user").filter(pk=pk).first()


def members_with_roles() -> QuerySet[Membership]:
    return (Membership.objects.select_related("user")
            .prefetch_related("roles__role", "roles__branches").order_by("username"))


def member_with_roles(pk) -> Membership:
    return members_with_roles().get(pk=pk)


def members_with_last_sign_in() -> QuerySet[Membership]:
    signed_in = SignInEvent.objects.filter(membership=OuterRef("pk"),
                                           outcome=SignInOutcome.SIGNED_IN).order_by("-at")
    return (Membership.objects.select_related("user", "default_branch")
            .prefetch_related("roles__role", "roles__branches__branch")
            .annotate(last_signed_in=Subquery(signed_in.values("at")[:1]))
            .order_by("username"))


def role_assignments(membership: Membership) -> QuerySet:
    return membership.roles.prefetch_related("branches")


def roles_with_grants() -> QuerySet[Role]:
    return Role.objects.prefetch_related("grants").order_by("name")


def roles_with_member_counts() -> QuerySet[Role]:
    return (Role.objects.prefetch_related("grants")
            .annotate(member_count=Count("assignments", distinct=True)).order_by("name"))


def role_with_member_count(pk) -> Role:
    return roles_with_member_counts().get(pk=pk)


def role_by_id(pk) -> Role | None:
    return Role.objects.filter(pk=pk).first()


def granted_codes(role: Role) -> set[str]:
    return set(role.grants.values_list("permission", flat=True))


def permission_groups() -> list[tuple]:
    groups = defaultdict(list)
    for definition in permissions().values():
        groups[str(definition.group)].append(definition)
    return sorted(groups.items())
