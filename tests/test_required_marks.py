"""A red star on a label means the server refuses the field empty, and only then.

Crawls the workspace from the dashboard, so a new form is covered without being listed here.
Each form is sent empty, the way the browser would, in the test database, and the fields the
server refuses are compared with the labels marked `is-required`.

Not checked: a list with no empty choice (it cannot be left empty) and a field with no label to
mark. A rule the server applies only after the basic checks pass can't be seen by sending a form
empty: those are listed in AFTER_THE_BASIC_CHECKS.
"""

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import Resolver404, resolve, reverse

pytestmark = pytest.mark.django_db
PASSWORD = "Demo-Pass-2026"
SKIP = re.compile(r"\.(pdf|xlsx|csv)$|/logout/|/i18n/|/media/|/static/")
CONTROLS = ("input", "select", "textarea")
AFTER_THE_BASIC_CHECKS = {
    ("payroll/new/", "reason"),  # apps/payroll/services/runs.py: an off-cycle run says why
    ("settings/users/new/", "password"),  # apps/iam/api/views.py: only a new user needs one
}


@dataclass
class Control:
    tag: str
    name: str
    id: str = ""
    type: str = "text"
    empty: str = ""  # data-empty
    has_empty_option: bool = False
    options: int = 0
    star: bool = False
    label: str = ""
    shown_when: str = ""


@dataclass
class Form:
    attrs: dict
    controls: list = field(default_factory=list)
    labels: dict = field(default_factory=dict)  # for= -> (text, star)


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms, self.links = [], []
        self.form = self.select = self.label = None
        self.show = []
        self.wrapping = None  # a <label> around its control: its text, until the control comes

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href", "").startswith("/"):
            self.links.append(a["href"].split("#")[0])
        if tag == "form":
            self.form = Form(a)
        if self.form is None:
            return
        if tag == "div":
            self.show.append(a.get("data-show-when", ""))
        classes = a.get("class", "").split()
        if tag in ("label", "span") and "form-label" in classes:
            self.label = {"for": a.get("for", ""), "text": "", "star": "is-required" in classes}
        if tag == "option" and self.select is not None:
            self.select.options += 1
            self.select.has_empty_option |= a.get("value", "x") == ""
        kind = a.get("type")
        if tag in CONTROLS and a.get("name") and kind not in ("hidden", "submit", "button"):
            control = Control(tag, a["name"], a.get("id", ""), a.get("type", "text"),
                              a.get("data-empty", ""),
                              shown_when=next((s for s in reversed(self.show) if s), ""))
            control.label, control.star = self.form.labels.get(control.id, ("", False))
            if self.wrapping is not None:
                control.label, control.star = self.wrapping
                self.wrapping = None
            self.form.controls.append(control)
            if tag == "select":
                self.select = control

    def handle_endtag(self, tag):
        if tag == "form" and self.form is not None:
            self.forms.append(self.form)
            self.form = None
        if tag == "div" and self.show:
            self.show.pop()
        if tag == "select":
            self.select = None
        if tag in ("label", "span") and self.label is not None and self.form is not None:
            found = (self.label["text"].strip(), self.label["star"])
            if self.label["for"]:
                self.form.labels[self.label["for"]] = found
            else:
                self.wrapping = found
            self.label = None

    def handle_data(self, data):
        if self.label is not None:
            self.label["text"] += data


def nest(values: dict) -> dict:
    body = {}
    for name, value in values.items():
        node = body
        *path, last = name.split(".")
        for part in path:
            node = node.setdefault(part, {})
        node[last] = value
    return body


def flat(fields, prefix=""):
    out = {}
    for key, value in (fields or {}).items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flat(value, path))
        else:
            out[path] = value
    return out


templates: dict[str, list[str]] = {}


def crawl(client):
    seen, routes, queue, pages = set(), set(), ["/"], []
    while queue:
        url = queue.pop(0)
        path = url.split("?")[0]
        if path in seen or SKIP.search(path):
            continue
        seen.add(path)
        try:
            route = resolve(path).route
        except Resolver404:
            continue
        if route in routes:
            continue
        routes.add(route)
        response = client.get(url)
        if response.status_code != 200 or "text/html" not in response.get("Content-Type", ""):
            continue
        parsed = Page()
        parsed.feed(response.content.decode())
        pages.append((path, parsed))
        templates[path] = sorted({t.origin.name for t in response.templates if t.origin})
        queue += parsed.links
    return pages


def audit(settings):
    settings.DEBUG = True  # create_demo refuses otherwise
    call_command("create_demo")
    settings.DEBUG = False
    client = Client(HTTP_HOST="demo.localhost")
    client.cookies["django_language"] = "en"
    assert client.post("/login/", {"username": "owner", "password": PASSWORD}).status_code == 302
    rows = []
    for path, page in crawl(client):
        for form in page.forms:
            method = form.attrs.get("data-method", "POST").upper()
            endpoint = form.attrs.get("data-endpoint", "")
            sent = "data-api-form" in form.attrs or "data-bulk-form" in form.attrs
            if not sent or not endpoint or method == "DELETE":
                continue
            editable = [c for c in form.controls if c.type not in ("checkbox", "radio")]
            if not editable:
                continue
            body = nest({c.name: (None if c.empty == "null" else "") for c in editable
                         if c.empty != "omit"})
            refused = {}
            for payload in ({}, body):
                response = client.generic(method, endpoint, json.dumps(payload),
                                          content_type="application/json")
                try:
                    data = response.json()
                except ValueError:
                    data = {}
                error = data.get("error") or data
                found = flat(error.get("fields") if isinstance(error, dict) else {})
                refused.update(found)
            for control in editable:
                rows.append({"page": path, "route": resolve(path).route, "id": control.id,
                             "name": control.name, "label": control.label, "star": control.star,
                             "tag": control.tag, "templates": templates[path],
                             "open": control.tag != "select" or control.has_empty_option,
                             "refused": control.name in refused,
                             "shown_when": control.shown_when})
    return rows


def test_stars_match_what_the_server_refuses(settings):
    rows = audit(settings)
    assert len({row["page"] for row in rows}) > 40  # the crawl reached the forms

    wrong = []
    for row in rows:
        if not row["label"] or not row["open"]:
            continue
        needed = row["refused"] or (row["route"], row["name"]) in AFTER_THE_BASIC_CHECKS
        if needed != row["star"]:
            wrong.append(f"{row['page']} {row['name']} ({row['label']}): "
                         f"{'needs a star' if needed else 'should not have one'}")
    assert sorted(set(wrong)) == []


def test_a_new_employee_starts_from_the_defaults(tenant_a):
    from conftest import login

    client = login(tenant_a, language="en")
    page = client.get("/employees/new/").content.decode()
    for name, value in (("pay.hours_per_day", "8"), ("pay.overtime_multiplier", "1.5"),
                        ("pay.annual_leave_days", "21")):
        assert re.search(rf'name="{re.escape(name)}"[^>]*value="{re.escape(value)}"', page), name


def test_a_cleared_default_uses_the_servers_value(tenant_a):
    """Left out, as the browser does for a cleared field marked data-empty="omit"."""
    from apps.core.tenancy import tenant_context
    from apps.employees.models import Compensation
    from apps.org.models import Branch
    from conftest import login

    with tenant_context(tenant_a.id):
        branch = Branch.objects.get(code=1)
    client = login(tenant_a, language="en")
    response = client.post(reverse("employee-list"), json.dumps({
        "code": 50, "name": "New Person", "branch_id": branch.pk, "hired_on": "2026-01-01",
        "pay": {"salary": "5000"}, "schedule": {"starts_at": "09:00", "ends_at": "17:00"}}),
        content_type="application/json")
    assert response.status_code == 201, response.content
    with tenant_context(tenant_a.id):
        pay = Compensation.objects.get(employee__code=50)
    assert (pay.hours_per_day, pay.annual_leave_days) == (8, 21)
    assert pay.overtime_multiplier == 1.5
