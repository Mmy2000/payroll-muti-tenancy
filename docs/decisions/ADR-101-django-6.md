# ADR-101: Django 6, not the 5.2 LTS Gweb uses

**Status:** Accepted · 2026-10-28

## Context

The foundation is copied from Gweb, which pins Django 5.2 LTS (supported to April 2028). This
project was started on Django 6.1.

## Decision

Use Django 6.x. Ported code is adapted to it as it is copied; its tests must pass on 6.x before
a phase is done.

## Consequences

- Fixes made in Gweb's foundation can't always be copied as they are; check them against 6.x.
- Each 6.x feature release is supported for about 16 months: plan an upgrade to the next one
  (6.2 LTS is due in April 2027) instead of staying on a release that loses support.
- Django 6.1 applies a model's `Meta.ordering` to `union()` / `intersection()` /
  `difference()` results. A combined `values()`/`values_list()` query that doesn't select the
  ordering columns fails ("ORDER BY term does not match any column"): call `.order_by()` (or
  order by a selected column) on the combined queryset.
- Third-party packages must support 6.x before they are added (checked when installing:
  DRF 3.18, django-filter 26.2 and drf-spectacular 0.30 do).
