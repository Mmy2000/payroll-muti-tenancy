# PayRole's business rules, checked against its source

Every rule here was read in PayRole's code (`D:\software house\PayRole`), with the file and line,
and compared with this project. **Status**: *same* = ported as it is; *fixed* = PayRole's
behaviour was a bug (docs/PLAN.md "Behaviour changes"); *phase N* = still to build; *gap* = not
built, decision needed.

Checked 2026-10-29 for phases 1–4.

## Departments and branches (Enp/models.py `Pfn`, Enp/views.py)

| Rule | Source | Status |
|---|---|---|
| A department belongs to one branch; its code is the branch's own, next code per branch | `Pfn.br1`, :741, :773 | same (aligned 2026-10-30: org.0007, departments had been tenant-wide) |
| An employee's department must be in the employee's branch | :1300–1302 | same, also when moving an employee and in the Excel import |

## Rates (Enp/salary_base.py)

| Rule | Source | Status |
|---|---|---|
| Monthly: day = salary ÷ 30; hour = day ÷ hours a day | `daily_and_hourly_rate` :24 | same (`employees/domain/rates.py`) |
| Daily-paid: the day's wage is typed in | :46 | same (basis "daily") |
| Weekly: day = weekly wage ÷ 30 | :45 | fixed; rule still to be decided (PLAN "Open questions") |
| "% of salary" is of the monthly/weekly salary, or of the day's wage for daily-paid | `salary_base` :4 | same (`adjustments/domain/amounts.py`) |
| A work day opens 4 h before the shift starts (night shifts belong to the day they start) | :58–81 | same (`attendance/domain/workday.py`) |

## Attendance (Salary/payroll.py, zkk)

| Rule | Source | Status |
|---|---|---|
| A day's check-in is its first "in" punch, its check-out the last "out" after it; a day with only "out" punches is ignored; an in without an out is a day with no check-out | `day_punches` :96 | partly: punches carry no in/out yet, so first and last punch are used; add the direction with devices (phase 6) |
| An out early the next morning before any in closes the previous day's shift (< 24 h) | :118–135 | covered by the work-day window; check again with devices (phase 6) |
| Manual entry replaces the device punches of the day | zkk/signals.py | fixed: the entry wins without deleting the punches |
| Absent = an expected working day without attendance, up to today | :523–526 | same (`domain/days.py`) |
| A day marked weekly off on which the employee worked: all of it is overtime, and it isn't counted as a working day | :396–417 | same (aligned 2026-10-29) |
| A day marked "إجازة بإذن" (no leave request): not absent, not paid | :509–523, zkk/models.py `status_label` | same (aligned 2026-10-29: "excused") |
| Approved leave covering a day: not absent | :387, :521 | same |

## Leave and hourly permissions (zkk/views.py)

| Rule | Source | Status |
|---|---|---|
| Yearly balance = the employee's leave days; only approved leave counts | `_leave_used` :198 | same (`attendance/leave.py`) |
| Leave periods may not overlap | :215 | same |
| The days of a request are typed in, at most the length of the range | :225–235 | changed: counted from the schedule (days off and holidays are free) |
| Hourly permission: same day only; hours rounded to the hour; capped by the month's permission hours; no two at the same time | :1395–1440, `_perm_hours` :254 | kept in minutes, may cross midnight; several a day if they don't overlap |
| Hourly permission for a group or a branch at once | :1408–1420 | same, with a preview (`attendance/hourly.py`) |

## Pay items, incentives, penalties (Allow, Pun/batch_entry.py)

| Rule | Source | Status |
|---|---|---|
| An allowance is for an employee, a group or a branch, expanded per employee | Allow/views.py :70–257 | same (`employees/targets.py`) |
| The same item once a month per employee | Allow/views.py :58 | same |
| Daily items × days worked, monthly items as they are | Salary/payroll.py :321 | fixed: PayRole multiplied the items its form labels "monthly" (`templates/Allow/GHB11a.html` :372, help text :452) |
| Incentives/penalties: fixed amount or % of salary for the batch; days or hours per row | Pun/batch_entry.py :139, :270 | same (four methods) |
| Employee, group or branch; employees still working on the date | :244–262 | same |
| A batch, or one row of it, can be edited | `edit_batch` :290 | changed: a draft is edited freely; an approved one is reopened or cancelled with a reason while unpaid, and corrected once paid |
| Entries are locked once a paid payroll covers their date | `paid_payroll` :73 | same (`core/locks.py`: an approved run) |

## Advances and loans (Loans/views.py)

| Rule | Source | Status |
|---|---|---|
| A month's advances ≤ the salary | :425 | same (`loans/advances.py`; daily-paid: 30 days) |
| Installments equal to the piastre, remainder on the last | `_split_instalments` :79 | same |
| Each installment at least a piastre | :671 | same (added 2026-10-29) |
| No new loan while any installment of another is unpaid | :681 | same |
| A loan can't be deleted once an installment is paid | :626 | same (cancel) |
| Installment due dates: start date + n months | :708 | same (by month) |
| Advances and installments can't be changed once a payroll covers them | `_payroll_covers` :71 | same (`core/locks.py`) |

## The payroll of one employee (Salary/payroll.py `run_employee`)

| Rule | Source |
|---|---|
| Period: from hiring (if later) to leaving (if earlier) | :361 |
| Worked hours rounded to the hour; overtime = ⌈worked − hours a day⌉, only for employees with overtime | :411–446 |
| Overtime pay = hours × hourly rate × overtime multiplier (default 1.5); the group's overtime bands are **not** used | :436–446 → fixed: overtime policies apply |
| A day worked on a public holiday or approved leave is paid × the holiday multiplier | :429 |
| Missing hours (no permission, no lateness policy): deducted at the hourly rate, less allowed early leave | :462 |
| With a permission: the permitted hours are paid; what is still missing is deducted | :453 |
| Lateness bands: only when the day is short of its hours (who made the time up isn't deducted); late minutes from the shift start; one band applies; deduction = band hours × hourly rate | :471, `lateness_discount` :149 |
| Unworked weekly days off and public holidays are paid a day each | :518–533 |
| Absence: the day is unpaid, and costs (absence multiplier − 1) days more | :535–548 |
| Approved leave not worked is paid a day each | :552–556 |
| Monthly-paid, whole calendar month: pay adjusted to 30 days (capped in February at the salary) | :587–600 |
| Pay items: additions and deductions, taxable parts apart | :315 |
| Advances in the period, installments due in the period | :567–571 |
| Incentives and penalties dated in the period | :574 |
| Insurance: insured salary × employee rate; default 14 % / 26 % when none is set | :22, :611 → fixed: no rates blocks approval, 0 % is deliberate, employer share reported apart |
| Tax base: day pay + paid days off, holidays, leave − absence penalty − insurance + taxable additions + incentives − taxable deductions; monthly tax = tax on base × 12 less exemptions, ÷ 12 | :617–620 |
| Net = additions + incentives + paid days + day pay − advances − installments − deductions − penalties − tax − insurance − absence penalty; rounded to the pound | :623–631 → to the piastre here |
| Runs per branch or per group, for any date range; a group paid in an overlapping period is skipped; re-running deletes the unpaid run first; a paid run can't be re-run | Salary/views.py :284–373 → periods from a pay calendar, plus off-cycle runs with a reason; a draft recalculates in place |
| Incomplete employee cards are skipped and listed | `missing_card_fields` :80 |

## Gaps found (decisions)

1. **Editing** an incentive/penalty batch or row: decided (the four gaps, 2026-10-29): drafts,
   approval, reopening or cancelling with a reason, corrections once paid. Done.
2. **Hourly permissions** several in a day, and for a group or a branch: decided, done.
3. **Changing hours for a whole department or branch**: decided (from a date, for good or until
   a last day, with a preview), done. A break isn't modelled (PayRole had none either).
4. **Manual attendance with given times for a group**: decided (the same times or each their
   own, with a reason and a preview), done.
5. **Payroll period**: decided (Phase 4 Payroll Decisions): pay calendars with a start day or an
   anchor, plus off-cycle runs. Done.
6. **Insurance default**: decided: no default (done). **Tax tables per branch**: kept out (one
   table for the client).
