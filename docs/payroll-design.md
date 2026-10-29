# Payroll (phase 4): design and rules

The client's decisions are in "PayRole — Phase 4 Payroll Decisions" (2026-10-29). This page
turns them into rules. PayRole's own calculation, rule by rule with source lines, is in
[payrole-rules.md](payrole-rules.md); where this page differs, it says so.

## 1. What an employee is paid on (two separate things)

| | Values | Means |
|---|---|---|
| **Wage type** (`Compensation.wage_type`) | fixed salary · daily wage · hourly wage | how pay is *counted* |
| **Pay frequency** (`Compensation.pay_frequency`) | monthly · biweekly · weekly | how often pay is *run* |

`salary` is the amount for one unit of the wage type: the salary for one pay period (a month, two
weeks, a week) for a fixed salary; the day's wage; the hour's wage. Both are effective-dated, like
the rest of the pay record.

**Rates** (`employees/domain/rates.py`):

- Fixed salary: day = salary ÷ calendar days of its period length (monthly 30, as PayRole;
  biweekly 14; weekly 7). Hour = day ÷ hours a day.
- Daily wage: day = the wage; hour = day ÷ hours a day.
- Hourly wage: hour = the wage; day = hour × hours a day.

## 2. Pay calendars, periods and runs

- **Pay calendar** (one per frequency per client): monthly with a **start day** (1 = calendar
  months; 26 = 26th to 25th); weekly and biweekly with an **anchor date** (the first day of one
  period, e.g. a Saturday). Periods are worked out from it.
- **Payroll period**: a start date, an end date, a frequency, and a status (open, closed). A
  regular period comes from the calendar; an **off-cycle** period has any dates and a reason.
- **Payroll run**: a calculation for one period and a scope (everyone, a branch, or a
  department; everyone and a department need the permission in every branch, as do the
  calendars), with states **draft → approved → paid**. A run can be **reversed** (approved, not
  paid) to correct it.
- **Overlaps**: an employee is in at most one live regular run (draft, approved or paid) per
  overlapping period. Employees already in one are left out of a new run and listed as skipped,
  as PayRole skipped groups already paid (Salary/views.py :328).
- **Off-cycle runs** pay no salary and read no attendance. They take what is dated in their
  range and not yet paid by another run: one-time pay items, incentives, penalties, advances,
  and lines a manager adds.

## 3. The workflow

1. **Draft**: the run is calculated; it can be recalculated at any time (rates or attendance
   changed), each payslip in place (it keeps its address). A manager may add manual lines to a
   payslip.
2. **Review**: every payslip lists its issues. **Blocking** issues stop approval (insurance
   missing for an insured employee, a daily-paid employee without attendance…); **warnings**
   don't (no check-out on a day, the period isn't over…).
3. **Approval**: re-checks, then numbers the run, freezes every payslip with a **snapshot** of
   everything it was calculated from, and **consumes** what it paid: installments become paid,
   advances recovered, and each pay item, incentive and penalty is recorded as paid by this
   payslip, so no other run can pay it again (a database constraint).
4. **Payment**: records the date, method and reference.
5. **Correction**: an approved run is **reversed** with a reason: its payslips stay visible,
   what it consumed is released, and a new run can be calculated. A paid run is corrected by the
   next run or an off-cycle run with manual lines. Every step is in the audit trail.

## 4. What payroll reads, and how it is allocated to a period

Everything payroll adds or deducts has a date or a schedule; each is allocated to periods by one
rule, and recorded as consumed when a payslip that paid it is approved.

| Source | Allocated to |
|---|---|
| Incentives, penalties, advances, one-time pay items | the period containing their date |
| Loan installments | **the regular run of the employee's frequency whose period contains the due date** (the 1st of the due month), **whole**, never split. A weekly-paid employee's monthly installment falls in the week containing the 1st. Once paid it is never taken again. |
| Recurring pay items, same frequency as the employee | the full amount every period, prorated by days when the employee (or the item) covers only part of the period |
| Recurring **monthly** items for a **weekly/biweekly** employee | **split by calendar days**: a period gets the share of each calendar month it covers. The shares telescope (each period takes "allocated up to its last day" minus "allocated up to the day before it"), so a month's shares add up to the item exactly. A client may choose **whole in the first run of the month** instead (the period containing the 1st). |
| Recurring weekly items for a monthly employee | amount × days in the period ÷ 7 |

## 5. One payslip (the calculation)

The engine is a pipeline of calculators (`payroll/domain/engine.py`); each belongs to a feature and
is skipped when the feature is off for the client. Days come from attendance
(`attendance.selectors.evaluate`), the same as the screens.

1. **Base pay**
   - Fixed salary: the salary for a full period; for part of a period (hired or left in it), the
     day rate × days employed (PayRole: day by day).
   - Daily wage: the day's wage × paid days (worked days, paid days off, paid holidays, paid
     leave), as PayRole pays weekly days off and holidays to everyone (:518–533).
   - Hourly wage: the hour's wage × hours worked, plus hours a day × paid days not worked.
2. **Days not paid** (fixed salary): absent days, unpaid leave and excused absences × day rate.
3. **Absence penalty**: absent days × (absence multiplier − 1) × day rate (:535).
4. **Holiday work**: a day worked on a public holiday or approved leave is paid × the holiday
   multiplier: the extra (multiplier − 1) days for a fixed salary (the day is in the salary), the
   whole for a daily wage (:429).
5. **Overtime** (feature overtime; employees whose hours have an overtime policy): per day, the
   minutes worked beyond the hours a day; on a day marked "day off", all of it (:415). Minutes up to
   the policy's "starts after" are not overtime; bands turn minutes into paid hours; without
   bands, whole hours rounded up (:419). Pay = hours × hour rate × overtime multiplier.
   *Changed:* PayRole ignored the overtime bands and "starts after".
6. **Missing time** (per working day short of its hours, not a rest day):
   - approved hourly leave covers missing time first (paid);
   - leaving early within the allowed early-leave minutes is not deducted;
   - with a **lateness policy**: only when the day is short of its hours and the employee was
     later than the grace minutes, the minutes late fall in a band, and its hours are deducted
     (:471); without one, the missing time is deducted as it is, at the hour rate (:462). *Changed:* kept in minutes, not rounded to
     hours.
   - a day with no check-out is a warning for the reviewer (PayRole deducted the whole day).
7. **Pay items**: additions and deductions as allocated (§4); per-day items × days worked (:321).
8. **Incentives, penalties, advances, installments** as allocated (§4).
9. **Social insurance** (feature insurance; employees with an insured salary): the insured salary
   in effect at the period's end, kept within the rates' minimum and maximum; employee share
   deducted, **employer share reported separately** as a cost (not a deduction). Monthly, split
   by days for weekly and biweekly periods.
   - No rates set for the period: nothing deducted, a **blocking** issue.
   - Rates set to 0 %: nothing deducted, no issue (a deliberate setting).
   - *Changed:* PayRole used 14 % / 26 % when nothing was set (:22).
10. **Income tax** (feature income_tax): taxable = base pay − unpaid days − absence penalty +
    holiday work + overtime − missing time + taxable additions + incentives − taxable deductions
    − employee insurance (:617); annualized by periods a year (12, 26, 52), less the yearly
    exemption, taxed by brackets, back to one period. No table: a warning, no tax.
11. **Net** = earnings − deductions, to the piastre. (PayRole rounded to the pound; a client
    setting can come later.)

## 6. What is frozen

An approved payslip keeps: its lines (code, label, quantity, rate, amount), its issues, and a
snapshot (JSON) of its inputs: the pay records, schedules, policies, rates, tax table and
insurance rates in effect, the days, the features on, and the sources consumed. Changing a
salary, a policy or a rate afterwards changes nothing in it. While a run is approved or paid,
the screens that would change what it paid refuse: cancelling an advance, an installment, an
incentive, a penalty or a pay item it paid; cancelling leave or correcting attendance on days it
covers; deleting a pay change, a tax table or insurance rates it used.
