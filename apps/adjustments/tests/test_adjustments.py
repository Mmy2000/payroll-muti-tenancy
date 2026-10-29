"""Incentives and penalties: amount methods, targets, permissions per kind, and batches through
their life: drafts edited freely, approval, reopening and cancelling with a reason, and
corrections once a payroll has paid them."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.utils import translation

from apps.adjustments import services
from apps.adjustments.domain.amounts import METHODS
from apps.adjustments.models import Adjustment, AdjustmentBatch, AdjustmentType, BatchStatus
from apps.core.errors import Conflict, DomainError, ValidationError
from apps.core.tenancy import tenant_context
from apps.employees.domain.rates import PayTerms
from apps.employees.targets import Target
from apps.iam.models import Role
from apps.iam.services import assign_role, set_role_permissions
from apps.org.models import Department
from apps.payroll import services as payroll
from apps.platform.tenants import features
from apps.platform.tenants.models import TenantFeature
from conftest import login

MONTHLY = PayTerms("fixed", "monthly", D(6000), D(8))
OCTOBER = date(2026, 10, 5)


def test_amount_methods():
    assert METHODS["fixed"].amount(D("150.5"), MONTHLY) == D("150.50")
    assert METHODS["percent"].amount(D(10), MONTHLY) == D(600)
    assert METHODS["days"].amount(D(2), MONTHLY) == D(400)  # 6000 / 30 × 2
    assert METHODS["hours"].amount(D(3), MONTHLY) == D(75)  # 200 / 8 × 3
    daily = PayTerms("daily", "monthly", D(250), D(10))
    assert METHODS["percent"].amount(D(10), daily) == D(25)  # of the day's wage, as PayRole


def _type(tenant, kind):
    with tenant_context(tenant.id):
        return AdjustmentType.objects.filter(kind=kind).first().pk


BATCHES = {"incentive": "/api/web/adjustments/incentive-batches/",
           "penalty": "/api/web/adjustments/penalty-batches/"}


def _give(client, kind, tenant, target_kind, target_id, method="fixed", quantity="100", **extra):
    return client.post(BATCHES[kind], {
        "type_id": _type(tenant, kind), "target_kind": target_kind, "target_id": target_id,
        "date": "2026-10-05", "method": method, "quantity": quantity, **extra},
        content_type="application/json")


def _post(client, url, body=None):
    return client.post(url, body or {}, content_type="application/json")


@pytest.mark.django_db
def test_new_clients_get_types(tenant_a):
    with tenant_context(tenant_a.id):
        assert AdjustmentType.objects.filter(kind="incentive").count() == 2
        assert AdjustmentType.objects.filter(kind="penalty").count() == 3


@pytest.mark.django_db
def test_a_department_gets_a_draft_batch_of_one_row_each(tenant_a, make_employee):
    with tenant_context(tenant_a.id):
        sales = Department.objects.create(code=1, name="Sales")
    make_employee(tenant_a, 1, department_id=sales.pk, salary=D(6000))
    make_employee(tenant_a, 2, department_id=sales.pk, salary=D(3000))
    make_employee(tenant_a, 3, department_id=sales.pk, hired_on=date(2026, 11, 1))  # not yet
    make_employee(tenant_a, 4)  # another department
    response = _give(login(tenant_a), "penalty", tenant_a, "department", sales.pk, "days", "1")
    assert response.status_code == 201, response.content
    batch = response.json()
    assert batch["status"] == "draft" and batch["target_kind"] == "department"
    assert sorted(r["amount"] for r in batch["rows"]) == ["100.00", "200.00"]


@pytest.mark.django_db
def test_a_draft_is_edited_freely(tenant_a, make_employee):
    first = make_employee(tenant_a, 1, salary=D(6000))
    second = make_employee(tenant_a, 2, salary=D(3000))
    client = login(tenant_a)
    batch = _give(client, "incentive", tenant_a, "employee", first.pk, "days", "1").json()
    url = f"{BATCHES['incentive']}{batch['id']}/"

    edited = client.put(url, {"type_id": batch["adjustment_type"], "date": "2026-10-06",
                              "method": "days", "quantity": "2", "change_reason": "Two days"},
                        content_type="application/json")
    assert edited.status_code == 200 and edited.json()["rows"][0]["amount"] == "400.00"
    added = _post(client, f"{url}add/", {"target_kind": "employee", "target_id": second.pk})
    assert added.status_code == 200 and len(added.json()["rows"]) == 2
    again = _post(client, f"{url}add/", {"target_kind": "employee", "target_id": second.pk})
    assert "target_id" in again.json()["error"]["fields"]

    row = next(r for r in added.json()["rows"] if r["employee"] == second.pk)
    one = client.patch(f"/api/web/adjustments/incentives/{row['id']}/", {"quantity": "1"},
                       content_type="application/json")
    assert one.json()["amount"] == "100.00"  # one day of 3000
    assert client.delete(f"/api/web/adjustments/incentives/{row['id']}/").status_code == 204
    last = client.delete(f"/api/web/adjustments/incentives/{batch['rows'][0]['id']}/")
    assert last.json()["error"]["code"] == "ADJUSTMENTS_LAST_ROW"

    with tenant_context(tenant_a.id):
        saved = AdjustmentBatch.objects.get(pk=batch["id"])
        assert (saved.revision, saved.change_reason) == (5, "")  # four changes after "Two days"
    assert client.delete(url).status_code == 204
    with tenant_context(tenant_a.id):
        assert not Adjustment.objects.exists()


@pytest.mark.django_db
def test_approval_then_reopening_or_cancelling_with_a_reason(tenant_a, make_employee):
    employee = make_employee(tenant_a)
    client = login(tenant_a)
    batch = _give(client, "penalty", tenant_a, "employee", employee.pk).json()
    url = f"{BATCHES['penalty']}{batch['id']}/"
    assert _post(client, f"{url}approve/").json()["status"] == "approved"

    refused = client.put(url, {"type_id": batch["adjustment_type"], "date": "2026-10-05",
                               "method": "fixed", "quantity": "50"},
                         content_type="application/json")
    assert refused.json()["error"]["code"] == "ADJUSTMENTS_STATE"
    assert "reason" in _post(client, f"{url}reopen/").json()["error"]["fields"]
    reopened = _post(client, f"{url}reopen/", {"reason": "Wrong amount"}).json()
    assert (reopened["status"], reopened["change_reason"]) == ("draft", "Wrong amount")
    _post(client, f"{url}approve/")
    cancelled = _post(client, f"{url}cancel/", {"reason": "Forgiven"}).json()
    assert cancelled["status"] == "cancelled"


@pytest.mark.django_db
def test_approving_needs_its_own_permission(tenant_a, make_employee, make_member):
    employee = make_employee(tenant_a)
    member = make_member(tenant_a, "ines", "viewer")
    with tenant_context(tenant_a.id):
        role = Role.objects.create(code="bonuses", name="Bonuses")
        set_role_permissions(role, ["adjustments.incentive.view",
                                    "adjustments.incentive.manage", "employees.employee.view"])
        member.roles.all().delete()
        assign_role(member, role)
    client = login(tenant_a, "ines")
    batch = _give(client, "incentive", tenant_a, "employee", employee.pk)
    assert batch.status_code == 201
    assert _post(client, f"{BATCHES['incentive']}{batch.json()['id']}/approve/"
                 ).status_code == 403
    assert _give(client, "incentive", tenant_a, "employee", employee.pk,
                 approve=True).status_code == 403
    assert _give(client, "penalty", tenant_a, "employee", employee.pk).status_code == 403
    # A penalty type sent to the incentives endpoint is refused.
    wrong = client.post(BATCHES["incentive"], {
        "type_id": _type(tenant_a, "penalty"), "target_kind": "employee",
        "target_id": employee.pk, "date": "2026-10-05", "method": "fixed", "quantity": "5"},
        content_type="application/json")
    assert "type_id" in wrong.json()["error"]["fields"]


@pytest.mark.django_db
def test_the_amount_is_kept_after_a_raise(tenant_a, make_employee):
    employee = make_employee(tenant_a, salary=D(6000))
    client = login(tenant_a)
    _give(client, "incentive", tenant_a, "employee", employee.pk, "percent", "10")
    client.post(f"/api/web/employees/employees/{employee.pk}/pay/",
                {"effective_from": "2026-10-10", "salary": "9000"},
                content_type="application/json")
    with tenant_context(tenant_a.id):
        assert Adjustment.objects.get().amount == D(600)


@pytest.mark.django_db
def test_nobody_there_is_an_error(tenant_a):
    with tenant_context(tenant_a.id):
        empty = Department.objects.create(code=9, name="Empty")
    response = _give(login(tenant_a), "incentive", tenant_a, "department", empty.pk)
    assert "target_id" in response.json()["error"]["fields"]


# --- with payroll ------------------------------------------------------------------------------


def _lines(run):
    return {line.code: (line.kind, line.amount, line.label)
            for line in run.payslips.get().lines.all()}


def _payroll(day):
    run = payroll.create_run(payroll.RunInput(frequency="monthly", day=day))
    return run, _lines(run)


@pytest.fixture
def pay_client(tenant_a):
    TenantFeature.objects.create(tenant=tenant_a, key="attendance", enabled=False)
    features.forget(tenant_a.pk)
    return tenant_a


@pytest.mark.django_db
def test_payroll_pays_approved_batches_and_corrections_settle_the_difference(pay_client,
                                                                            make_employee):
    employee = make_employee(pay_client, salary=D(6000))
    with tenant_context(pay_client.id), translation.override("en"):
        penalty = services.give(services.AdjustmentInput(
            type_id=AdjustmentType.objects.filter(kind="penalty").first().pk,
            target=Target.employee(employee.pk), date=OCTOBER, method="days",
            quantity=D(2)))
        run, lines = _payroll(OCTOBER)
        assert "penalty" not in lines  # a draft is never paid
        services.approve(penalty.pk)
        lines = _lines(payroll.calculate_run(run.pk))  # the draft run sees it now
        assert lines["penalty"][1] == D(400)
        payroll.approve_run(run.pk)

        with pytest.raises(DomainError) as paid:
            services.reopen(penalty.pk, "Too much")
        assert paid.value.code == "ADJUSTMENTS_PAID"
        with pytest.raises(DomainError):
            services.cancel(penalty.pk, "Too much")

        row = penalty.rows.get()
        fix = services.correct(penalty.pk, services.CorrectionInput(
            date=date(2026, 11, 3), reason="One day, not two", quantities={row.pk: D(1)}))
        assert fix.status == BatchStatus.DRAFT and fix.rows.get().amount == D(-200)
        with pytest.raises(Conflict):  # one draft correction at a time
            services.correct(penalty.pk, services.CorrectionInput(
                date=date(2026, 11, 3), reason="Again", quantities={row.pk: D(0)}))
        with pytest.raises(DomainError):  # a correction isn't edited, it's redone
            services.update_draft(fix.pk, services.BatchInput(
                type_id=fix.adjustment_type_id, date=fix.date, method="days",
                quantity=D(1)))
        services.approve(fix.pk)
        assert services.effective_amounts(penalty) == {row.pk: D(200)}
        penalty.refresh_from_db()
        assert penalty.rows.get().amount == D(400)  # the original never changes

        _run, november = _payroll(date(2026, 11, 15))
        kind, amount, label = november["penalty"]
        assert (kind, amount) == ("earning", D(200))  # given back
        assert "correction of 2026-10-05" in label

        with pytest.raises(ValidationError):  # already what it should be
            services.correct(penalty.pk, services.CorrectionInput(
                date=date(2026, 11, 3), reason="Same", quantities={row.pk: D(1)}))
        back = services.correct(penalty.pk, services.CorrectionInput(
            date=date(2026, 11, 4), reason="Forgiven", quantities={row.pk: D(0)}),
            approve=True)
        assert back.rows.get().amount == D(-200)  # what is left of it


@pytest.mark.django_db
def test_a_batch_history_shows_why_and_its_rows(tenant_a, make_employee):
    employee = make_employee(tenant_a, name="Mona Adel")
    client = login(tenant_a, language="en")
    batch = _give(client, "incentive", tenant_a, "employee", employee.pk).json()
    url = f"{BATCHES['incentive']}{batch['id']}/"
    _post(client, f"{url}approve/")
    _post(client, f"{url}reopen/", {"reason": "Wrong amount"})
    page = client.get(f"/pay/incentives/{batch['id']}/").content.decode()
    assert "Wrong amount" in page
    assert "/settings/activity/?table=adjustments_adjustmentbatch" in page
    history = client.get(f"/settings/activity/?table=adjustments_adjustmentbatch"
                         f"&row={batch['id']}").content.decode()
    assert "Why it changed" in history and "Wrong amount" in history
    assert "Mona Adel" in history  # the row, a part of the batch


@pytest.mark.django_db
def test_pages_render(tenant_a, make_employee):
    client = login(tenant_a, language="en")
    draft = _give(client, "incentive", tenant_a, "employee", make_employee(tenant_a).pk).json()
    approved = _give(client, "penalty", tenant_a, "employee",
                     make_employee(tenant_a, 2).pk, approve=True).json()
    for path in ("/pay/incentives/", "/pay/incentives/new/", "/pay/incentives/types/",
                 f"/pay/incentives/{draft['id']}/", "/pay/penalties/", "/pay/penalties/new/",
                 "/pay/penalties/types/", f"/pay/penalties/{approved['id']}/"):
        assert client.get(path).status_code == 200, path
    draft_page = client.get(f"/pay/incentives/{draft['id']}/").content.decode()
    assert "Change the details" in draft_page and "Approve" in draft_page
    approved_page = client.get(f"/pay/penalties/{approved['id']}/").content.decode()
    assert "Reopen to edit" in approved_page and "Save the correction" in approved_page
    assert client.get(f"/pay/penalties/{draft['id']}/").status_code == 404  # another kind
    with tenant_context(tenant_a.id):  # seeded in the client's language
        name = AdjustmentType.objects.get(pk=_type(tenant_a, "incentive")).name
    assert name in client.get("/pay/incentives/?status=all").content.decode()
