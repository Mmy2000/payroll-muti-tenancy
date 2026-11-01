from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from apps.iam import selectors, signins
from apps.iam.authz import permission_required
from apps.iam.catalog import WILDCARD
from apps.iam.member_links import employee_link
from apps.iam.models import SignInOutcome
from apps.org.listing import page_of
from apps.org.selectors import active_branches_by_code


@permission_required("admin.users.view")
def users(request):
    return render(request, "iam/users.html",
                  {"page": page_of(request, selectors.members_with_last_sign_in())})


@permission_required("admin.signins.history")
def sign_ins(request):
    events, filters = signins.search(request.GET)
    page = page_of(request, events)
    for event in page.object_list:
        event.device = signins.device(event.user_agent)
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "iam/sign_ins.html", {
        "page": page, "filters": filters, "query": query.urlencode(),
        "outcomes": SignInOutcome.choices, "failed_today": signins.failed_recently(),
        "members": selectors.members_by_name(),
    })


def _user_form(request, membership=None):
    assigned = {}
    if membership is not None:
        for assignment in selectors.role_assignments(membership):
            assigned[assignment.role_id] = {
                "all": assignment.all_branches,
                "branches": {b.branch_id for b in assignment.branches.all()},
            }
    roles = []
    for role in selectors.roles_with_grants():
        codes = {g.permission for g in role.grants.all()}
        roles.append({"role": role, "is_owner": WILDCARD in codes,
                      "assignment": assigned.get(role.pk),
                      "needs_every_branch": selectors.company_wide_labels(codes)})
    endpoint = (reverse("member-detail", args=[membership.pk]) if membership
                else reverse("member-list"))
    return render(request, "iam/user_form.html", {
        "member": membership,
        "roles": roles,
        "branches": active_branches_by_code(),
        "endpoint": endpoint,
        "method": "PUT" if membership else "POST",
        **_employee_link(request.actor, membership),
    })


def _employee_link(actor, membership) -> dict:
    """The employee this user is, when the mobile app is on."""
    link = employee_link()
    if not link.can_link(actor):
        return {}
    member_id = membership.pk if membership else None
    linked = link.linked(member_id) if member_id else None
    return {"link_employees": link.choices(actor, member_id), "linked_employee": linked}


@permission_required("admin.users.manage")
def user_new(request):
    return _user_form(request)


@permission_required("admin.users.manage")
def user_edit(request, pk):
    membership = selectors.member_with_user(pk)
    if membership is None:
        raise Http404
    return _user_form(request, membership)


@permission_required("admin.users.view")
def roles(request):
    page = page_of(request, selectors.roles_with_member_counts())
    return render(request, "iam/roles.html", {
        "page": page,
        "roles": [{"role": r, "is_owner": any(g.permission == WILDCARD for g in r.grants.all()),
                   "count": len(r.grants.all()),
                   "incomplete": bool(selectors.role_gaps(
                       {g.permission for g in r.grants.all()} - {WILDCARD}))}
                  for r in page.object_list],
    })


def _role_form(request, role=None):
    granted = selectors.granted_codes(role) if role else set()
    endpoint = reverse("role-detail", args=[role.pk]) if role else reverse("role-list")
    return render(request, "iam/role_form.html", {
        "role": role,
        "is_owner": WILDCARD in granted,
        "granted": granted,
        "sections": selectors.permission_sections(request.actor.disabled),
        "gaps": selectors.role_gaps(granted - {WILDCARD}),
        "limited_holders": selectors.limited_holders(role) if role else [],
        "company_wide_held": selectors.company_wide_labels(granted),
        "endpoint": endpoint,
        "method": "PUT" if role else "POST",
    })


@permission_required("admin.roles.manage")
def role_new(request):
    return _role_form(request)


@permission_required("admin.roles.manage")
def role_edit(request, pk):
    role = selectors.role_by_id(pk)
    if role is None:
        raise Http404
    return _role_form(request, role)
