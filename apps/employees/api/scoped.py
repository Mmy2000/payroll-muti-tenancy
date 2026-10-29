"""A ViewSet over rows that belong to employees (leave, advances, loans, penalties…): it lists
only the rows of employees the member may see, in the branches of `view_permission`."""

from rest_framework import viewsets

from apps.employees.services import visible_employees


class EmployeeRowsViewSet(viewsets.GenericViewSet):
    model = None
    view_permission = ""
    related = ("employee",)  # select_related for the list

    def rows(self):
        """The model's rows to start from (a subclass may narrow them, e.g. by kind)."""
        return self.model.objects.all()

    def get_queryset(self):
        employees = visible_employees(self.request.actor, self.view_permission)
        return self.rows().filter(employee__in=employees).select_related(*self.related)

    def list(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)
