"""The role page lists permissions in the order people work: the sidebar's."""

import pytest
from django.utils import translation

from apps.iam.catalog import permissions
from apps.iam.flow import FLOW
from config.context_processors import NAVIGATION
from conftest import login

NOT_IN_THE_SIDEBAR = {"Mobile app"}


@pytest.fixture(autouse=True)
def _english():
    with translation.override("en"):
        yield


def _titles(items) -> list[str]:
    return [str(item.title) for item in items]


def test_every_permission_has_one_place():
    placed = [code for section in FLOW for screen in section.screens for code in screen.codes]
    assert sorted(placed) == sorted(permissions()), "add it to apps/iam/flow.py"
    assert len(placed) == len(set(placed))


def test_the_sections_follow_the_sidebar():
    sidebar = [str(section.title) for section in NAVIGATION if section.key != "overview"]
    assert [title for title in _titles(FLOW) if title not in NOT_IN_THE_SIDEBAR] == sidebar


def test_the_screens_of_a_section_follow_the_sidebar():
    for section in FLOW:
        match = [s for s in NAVIGATION if str(s.title) == str(section.title)]
        if not match:
            continue
        sidebar = [str(item.label) for item in match[0].items]
        shown = [title for title in _titles(section.screens) if title in sidebar]
        assert shown == [label for label in sidebar if label in shown], section.title


@pytest.mark.django_db
def test_the_role_page_shows_them_in_that_order(tenant_a):
    page = login(tenant_a, language="en").get("/settings/roles/new/").content.decode()
    places = [page.index(f'data-permission="{code}"') for code in (
        "employees.employee.view", "attendance.day.view", "payroll.run.read", "admin.users.view")]
    assert places == sorted(places)
    assert page.index('"payroll.run.read"') < page.index('"payroll.run.approve"')
