"""Attendance and leave reports: each day of each employee (PayRole GHZ14), each employee's
totals over a period (GHS13, GHZ19), leave balances (GHZ15), and the leave and hourly leave
given (GHZ12, GHZ16).

Days are worked out by the same code as the screens and payroll (apps.attendance.selectors.
evaluate), so a report never disagrees with the daily sheet: weekly days off, holidays and
leave are not absences (PayRole's daily report counted every day without a punch as absent).
"""

from __future__ import annotations

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.attendance import selectors as attendance_selectors
from apps.attendance.domain.days import Status
from apps.attendance.domain.summary import summarize
from apps.attendance.models import HourlyLeave, LeaveRequest, RequestStatus
from apps.attendance.selectors import evaluate
from apps.attendance.templatetags.attendance import STATUS

from ..registry import DATE_FILTERS, WHO_FILTERS, Column, Filter, Report, Table, register

DAYS = "attendance.day.view"
NOT_COUNTED = (Status.NOT_EMPLOYED,)


def _status(day) -> str:
    label = STATUS[day.status][0]
    return str(day.label) if day.label and day.status in (Status.LEAVE, Status.HOLIDAY) \
        else str(label)


def _time(moment) -> str:
    return timezone.localtime(moment).strftime("%H:%M") if moment else ""


DAY_SHOW = (("all", _("Every day")), ("absent", _("Absences only")),
            ("late", _("Late arrivals only")), ("extra", _("Extra time only")))


@register
class DailyAttendance(Report):
    code, section, permission = "daily_attendance", "attendance", DAYS
    title = _("Attendance day by day")
    description = _("Each employee's days: status, when they came and left, time worked, late, "
                    "early and extra. At most 31 days at a time.")
    filters = (*DATE_FILTERS, *WHO_FILTERS, Filter("show", "choice", _("Show"), DAY_SHOW, "all"))
    max_days = 31

    def run(self, params, scope):
        people = list(scope.employees())
        start, end = params.date("date_from"), params.date("date_to")
        results = evaluate(people, start, end)
        show = params.get("show")
        rows = []
        for person in people:
            for day in results[person.pk]:
                if day.status in NOT_COUNTED or (show == "absent" and day.status != Status.ABSENT) \
                        or (show == "late" and not day.late_minutes) \
                        or (show == "extra" and not day.extra_minutes):
                    continue
                rows.append({"date": day.day, "code": person.code, "name": person.name,
                             "branch": person.branch.name, "status": _status(day),
                             "came": _time(day.check_in), "left": _time(day.check_out),
                             "worked": day.worked_minutes, "late": day.late_minutes,
                             "early": day.early_minutes, "extra": day.extra_minutes})
        columns = [Column("date", _("Day"), "date"), Column("code", _("Code"), "int"),
                   Column("name", _("Employee")), Column("branch", _("Branch")),
                   Column("status", _("Status")), Column("came", _("Came"), "code"),
                   Column("left", _("Left"), "code"), Column("worked", _("Worked"), "minutes"),
                   Column("late", _("Late"), "minutes"), Column("early", _("Early"), "minutes"),
                   Column("extra", _("Extra"), "minutes")]
        return [Table(self.title, columns, rows).add_totals("name", _("Total"), skip=("code",))]


@register
class AttendanceSummary(Report):
    code, section, permission = "attendance_summary", "attendance", DAYS
    title = _("Attendance totals per employee")
    description = _("For each employee over the period: days present, absent, on leave, off "
                    "and on holiday, and the hours worked, late, early and extra.")
    filters = (*DATE_FILTERS, *WHO_FILTERS)

    def run(self, params, scope):
        people = list(scope.employees())
        results = evaluate(people, params.date("date_from"), params.date("date_to"))
        rows = []
        for person in people:
            total = summarize(d for d in results[person.pk] if d.status not in NOT_COUNTED)
            rows.append({
                "code": person.code, "name": person.name, "branch": person.branch.name,
                "present": total.days(Status.PRESENT), "absent": total.days(Status.ABSENT),
                "excused": total.days(Status.EXCUSED), "leave": total.days(Status.LEAVE),
                "off": total.days(Status.DAY_OFF) + total.days(Status.HOLIDAY),
                "worked": total.worked_minutes, "late": total.late_minutes,
                "early": total.early_minutes, "extra": total.extra_minutes,
                "hourly": total.hourly_minutes, "missing": total.missing_check_outs})
        columns = [Column("code", _("Code"), "int"), Column("name", _("Employee")),
                   Column("branch", _("Branch")), Column("present", _("Present"), "int"),
                   Column("absent", _("Absent"), "int"), Column("excused", _("Excused"), "int"),
                   Column("leave", _("On leave"), "int"),
                   Column("off", _("Day off or holiday"), "int"),
                   Column("worked", _("Worked"), "minutes"), Column("late", _("Late"), "minutes"),
                   Column("early", _("Early"), "minutes"), Column("extra", _("Extra"), "minutes"),
                   Column("hourly", _("Hourly leave"), "minutes"),
                   Column("missing", _("No check-out"), "int")]
        return [Table(self.title, columns, rows).add_totals("name", _("Total"), skip=("code",))]


@register
class LeaveBalances(Report):
    code, section, permission = "leave_balances", "attendance", "attendance.leave.view"
    title = _("Annual leave balances")
    description = _("For each employee in the year: the days they are entitled to, taken, "
                    "waiting for approval, and left.")
    filters = (Filter("year", "year", _("Year")), *WHO_FILTERS)

    def run(self, params, scope):
        year = params.get("year")
        rows = []
        for person in scope.employees().exclude(left_on__lt=f"{year}-01-01").exclude(
                hired_on__gt=f"{year}-12-31"):
            left = attendance_selectors.balance(person, year)
            rows.append({"code": person.code, "name": person.name, "branch": person.branch.name,
                         "entitled": left.entitled, "taken": left.taken,
                         "waiting": left.requested, "remaining": left.remaining})
        columns = [Column("code", _("Code"), "int"), Column("name", _("Employee")),
                   Column("branch", _("Branch")), Column("entitled", _("Entitled"), "int"),
                   Column("taken", _("Taken"), "int"), Column("waiting", _("Waiting"), "int"),
                   Column("remaining", _("Left"), "int")]
        return [Table(f"{self.title} {year}", columns, rows)
                .add_totals("name", _("Total"), skip=("code",))]


REQUEST_SHOW = (("approved", _("Approved")), ("pending", _("Waiting for approval")),
                ("all", _("All but cancelled and rejected")))


def _requests(model, params, scope, date_field):
    rows = model.objects.filter(employee__in=scope.employees()).select_related(
        "employee__branch")
    show = params.get("show")
    rows = (rows.filter(status__in=(RequestStatus.APPROVED, RequestStatus.PENDING))
            if show == "all" else rows.filter(status=show))
    return rows.filter(**{f"{date_field}__range": (params.date("date_from"),
                                                   params.date("date_to"))}
                       ).order_by(date_field, "employee__code")


@register
class LeaveRegister(Report):
    code, section, permission = "leave_register", "attendance", "attendance.leave.view"
    title = _("Leave taken")
    description = _("The leave starting in the period: who, which kind, from when to when and "
                    "how many working days.")
    filters = (*DATE_FILTERS, *WHO_FILTERS,
               Filter("show", "choice", _("Show"), REQUEST_SHOW, "approved"))

    def run(self, params, scope):
        rows = [{"code": r.employee.code, "name": r.employee.name,
                 "branch": r.employee.branch.name, "type": r.leave_type.name,
                 "from": r.start_date, "to": r.end_date, "days": r.days,
                 "status": r.get_status_display(), "reason": r.reason}
                for r in _requests(LeaveRequest, params, scope, "start_date")
                .select_related("leave_type")]
        columns = [Column("code", _("Code"), "int"), Column("name", _("Employee")),
                   Column("branch", _("Branch")), Column("type", _("Leave type")),
                   Column("from", _("From"), "date"), Column("to", _("To"), "date"),
                   Column("days", _("Days"), "int"), Column("status", _("Status")),
                   Column("reason", _("Reason"))]
        return [Table(self.title, columns, rows).add_totals("name", _("Total"), skip=("code",))]


@register
class HourlyLeaveRegister(Report):
    code, section, permission = "hourly_leave_register", "attendance", "attendance.hourly.view"
    title = _("Hourly leave taken")
    description = _("Hourly leave in the period: the day, the time away and how long.")
    filters = (*DATE_FILTERS, *WHO_FILTERS,
               Filter("show", "choice", _("Show"), REQUEST_SHOW, "approved"))

    def run(self, params, scope):
        rows = [{"code": r.employee.code, "name": r.employee.name,
                 "branch": r.employee.branch.name, "day": r.work_date,
                 "from": r.starts_at.strftime("%H:%M"), "to": r.ends_at.strftime("%H:%M"),
                 "minutes": r.minutes, "status": r.get_status_display(), "reason": r.reason}
                for r in _requests(HourlyLeave, params, scope, "work_date")]
        columns = [Column("code", _("Code"), "int"), Column("name", _("Employee")),
                   Column("branch", _("Branch")), Column("day", _("Day"), "date"),
                   Column("from", _("From"), "code"), Column("to", _("To"), "code"),
                   Column("minutes", _("Time away"), "minutes"), Column("status", _("Status")),
                   Column("reason", _("Reason"))]
        return [Table(self.title, columns, rows).add_totals("name", _("Total"), skip=("code",))]


PUNCH_STATUS = {"in": _("In"), "out": _("Out"), "break_out": _("Break out"),
                "break_in": _("Break in"), "overtime_in": _("Overtime in"),
                "overtime_out": _("Overtime out")}


@register
class DevicePunches(Report):
    code, section, permission = "device_punches", "attendance", "devices.device.view"
    title = _("Fingerprint device punches")
    description = _("What the devices sent, as they sent it: the time, the device, the PIN and "
                    "the employee it is linked to, and whether it is in attendance.")
    filters = (*DATE_FILTERS, *WHO_FILTERS)
    max_days = 62

    def run(self, params, scope):
        from apps.devices.models import DevicePunch
        from apps.devices.protocol import PUNCH_STATUS as CODES

        start, end = params.date("date_from"), params.date("date_to")
        rows = (DevicePunch.objects.filter(at__date__range=(start, end))
                .select_related("device", "device_user__employee").order_by("at"))
        if scope.branches is not None:
            rows = rows.filter(device__branch_id__in=scope.branches)
        if params.get("branch") is not None:
            rows = rows.filter(device__branch=params.get("branch"))
        chosen = [params.get(k) for k in ("department", "employee")]
        if any(chosen):
            rows = rows.filter(device_user__employee__in=scope.employees())
        data = [{"at": timezone.localtime(p.at).strftime("%Y-%m-%d %H:%M:%S"),
                 "device": p.device.name, "pin": p.device_user.pin,
                 "name": p.device_user.employee.name if p.device_user.employee else "",
                 "status": str(PUNCH_STATUS.get(CODES.get(p.status, ""), p.status)),
                 "in": _("Yes") if p.punch_id else _("Waiting")} for p in rows]
        columns = [Column("at", _("When"), "code"), Column("device", _("Device")),
                   Column("pin", _("PIN"), "code"), Column("name", _("Employee")),
                   Column("status", _("Key pressed")), Column("in", _("In attendance"))]
        table = Table(self.title, columns, data)
        table.note = _("%(count)s punches.") % {"count": len(data)}
        return [table]


@register
class TrackingSessions(Report):
    code, section, permission = "tracking_sessions", "attendance", "mobile.monitor.track"
    title = _("Tracking sessions")
    description = _("Each shift followed by the mobile app: when it started and ended, how "
                    "long, how far and how many positions were sent.")
    filters = (*DATE_FILTERS, *WHO_FILTERS)

    def run(self, params, scope):
        from apps.mobile.models import TrackSession

        rows = (TrackSession.objects.filter(
            employee__in=scope.employees(),
            started_at__date__range=(params.date("date_from"), params.date("date_to")))
            .select_related("employee", "branch").order_by("started_at"))
        data = [{"started": timezone.localtime(r.started_at).strftime("%Y-%m-%d %H:%M"),
                 "ended": timezone.localtime(r.ended_at).strftime("%H:%M") if r.ended_at
                 else "", "code": r.employee.code, "name": r.employee.name,
                 "branch": r.branch.name, "minutes": r.duration_minutes,
                 "distance": r.total_distance_m, "points": r.points_count,
                 "reason": r.get_end_reason_display() if r.end_reason else _("Still on")}
                for r in rows]
        columns = [Column("started", _("Started"), "code"), Column("ended", _("Ended"), "code"),
                   Column("code", _("Code"), "int"), Column("name", _("Employee")),
                   Column("branch", _("Branch")), Column("minutes", _("Duration"), "minutes"),
                   Column("distance", _("Distance (m)"), "money"),
                   Column("points", _("Positions"), "int"), Column("reason", _("Ended by"))]
        return [Table(self.title, columns, data).add_totals("name", _("Total"), skip=("code",))]
