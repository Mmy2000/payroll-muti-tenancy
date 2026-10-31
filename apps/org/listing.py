"""One way to search and filter a list (the many "enquiry" screens, استعلام): a search box, a
date range, the branch, the list's own choices (status, kind…) and, from a link, one party such
as an employee (`?party=<id>`, shown as a removable chip). The template side is
components/list_filters.html, components/list_totals.html and components/pager.html.

    found = ListQuery(request, permission="loans.loan.view",
                      search=("number", "employee__name"),
                      party="employee_id", party_model="employees.Employee",
                      choices=[Choice("status", _("Status"), DocStatus.choices, "status")])
    loans = found.apply(queryset)
    render(..., {"filters": found, "page": found.page(loans.order_by(...))})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import reduce
from operator import or_
from urllib.parse import urlencode

from django.apps import apps
from django.core.paginator import Paginator
from django.db.models import Q


def by_status(queryset, value: str):
    """A `Choice.apply` for lists with an "all" tab."""
    return queryset if value == "all" else queryset.filter(status=value)


@dataclass
class Choice:
    name: str  # the query parameter
    label: object
    options: list  # [(value, label)]
    lookup: str = ""  # the field to filter on; or `apply` for anything else
    apply: object = None  # callable(queryset, value) -> queryset
    value: str = ""  # the default when the address has none
    tabs: bool = False  # shown as tabs above the list (the page renders filters.tabs)
    depends_on: str = ""  # the filter chosen first (selects.js `data-depends-on`), e.g. "branch"
    parents: dict = field(default_factory=dict)  # {value: the parent's value it belongs to}

    @property
    def rows(self) -> list:
        return [(value, label, self.parents.get(value, "")) for value, label in self.options]


@dataclass
class Total:
    label: object
    value: object
    places: int = 2
    unit: str = ""


def _date(text: str) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


@dataclass
class ListQuery:
    request: object
    permission: str
    search: tuple = ()  # fields matched with icontains
    search_label: object = ""
    date_field: str = "business_date"  # "" for no date range
    branch_field: str = "branch_id"  # "" for no branch filter; a callable(qs, ids) for two
    party: object = ""  # the field `?party=<id>` filters on, or callable(queryset, id)
    party_param: str = "party"  # the address's name for it
    party_model: str = ""  # "app_label.Model" whose `name` labels the chip
    choices: list = field(default_factory=list)
    per_page: int = 25
    keep: tuple = ()  # other query parameters the page owns (e.g. "month"), kept in its links

    def __post_init__(self):
        from apps.org.models import Branch

        get = self.request.GET
        self.q = get.get("q", "").strip()[:100]
        self.date_from, self.date_to = _date(get.get("from", "")), _date(get.get("to", ""))
        allowed = self.request.actor.branch_ids(self.permission)
        branches = Branch.objects.filter(is_active=True).order_by("code")
        self.branches = list(branches if allowed is None else branches.filter(pk__in=allowed))
        branch = get.get("branch", "")
        self.branch = int(branch) if branch.isdigit() and int(branch) in {
            b.pk for b in self.branches} else None
        party = get.get(self.party_param, "")
        self.party_id = int(party) if self.party and party.isdigit() else None
        self.party_name = ""
        if self.party_id and self.party_model:
            model = apps.get_model(self.party_model)
            self.party_name = model.objects.filter(pk=self.party_id).values_list(
                "name", flat=True).first() or ""
        for choice in self.choices:
            value = get.get(choice.name, choice.value)
            choice.value = value if value in {str(v) for v, _label in choice.options} else ""

    @property
    def show_branches(self) -> bool:
        return bool(self.branch_field) and len(self.branches) > 1

    @property
    def active(self) -> bool:
        return bool(self.q or self.date_from or self.date_to or self.branch or self.party_id
                    or any(c.value for c in self.choices if not c.tabs))

    def apply(self, queryset, *, search: bool = True):
        if search and self.q and self.search:
            queryset = queryset.filter(reduce(or_, (Q(**{f"{name}__icontains": self.q})
                                                    for name in self.search))).distinct()
        if self.date_field and self.date_from:
            queryset = queryset.filter(**{f"{self.date_field}__gte": self.date_from})
        if self.date_field and self.date_to:
            queryset = queryset.filter(**{f"{self.date_field}__lte": self.date_to})
        if self.branch is not None:
            if callable(self.branch_field):
                queryset = self.branch_field(queryset, {self.branch})
            elif self.branch_field:
                queryset = queryset.filter(**{self.branch_field: self.branch})
        if self.party_id and self.party:
            queryset = (self.party(queryset, self.party_id) if callable(self.party)
                        else queryset.filter(**{self.party: self.party_id}))
        for choice in self.choices:
            if not choice.value:
                continue
            if choice.apply is not None:
                queryset = choice.apply(queryset, choice.value)
            elif choice.lookup:
                queryset = queryset.filter(**{choice.lookup: choice.value})
        return queryset

    def page(self, queryset):
        return Paginator(queryset, self.per_page).get_page(self.request.GET.get("page"))

    @property
    def query(self) -> str:
        """The filters as a query string (without the page), for the pager and print links."""
        return self._encode(party=True)

    def _encode(self, *, party: bool, **override) -> str:
        values = {"q": self.q, "from": self.date_from or "", "to": self.date_to or "",
                  "branch": self.branch or "",
                  self.party_param: (self.party_id or "") if party else "",
                  **{c.name: c.value for c in self.choices},
                  **{name: self.request.GET.get(name, "") for name in self.keep}, **override}
        return urlencode({k: v for k, v in values.items() if v not in ("", None)})

    @property
    def tabs(self) -> list[dict]:
        """The choices shown as tabs: each option with its address (the other filters kept)."""
        return [{"label": label, "active": choice.value == str(value),
                 "query": self._encode(party=True, **{choice.name: value})}
                for choice in self.choices if choice.tabs for value, label in choice.options]

    @property
    def kept(self) -> dict:
        """The `keep` parameters and their values, for the filter form's hidden fields."""
        return {name: self.request.GET[name] for name in self.keep if self.request.GET.get(name)}

    def without_party(self) -> str:
        return self._encode(party=False)
