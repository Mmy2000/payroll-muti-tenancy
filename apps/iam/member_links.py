"""The user form also says which employee a user is. The link is the mobile app's (it sits above
iam), so the app registers it here from ready()."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class EmployeeLink:
    can_link: Callable
    choices: Callable
    linked: Callable
    link_member: Callable


_link: EmployeeLink | None = None


def register(link: EmployeeLink) -> None:
    global _link
    _link = link


def employee_link() -> EmployeeLink:
    return _link
