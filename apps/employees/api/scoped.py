"""A ViewSet over rows that belong to employees (leave, advances, loans, penalties…): it lists
only the rows of employees the member may see, in the branches of `view_permission`."""

from rest_framework import viewsets

from ..selectors import all_rows, employee_rows


class EmployeeRowsViewSet(viewsets.GenericViewSet):
    model = None
    view_permission = ""
    related = ("employee",)  # select_related for the list

    def rows(self):
        """The model's rows to start from (a subclass may narrow them, e.g. by kind)."""
        return all_rows(self.model)

    def get_queryset(self):
        return employee_rows(self.rows(), self.request.actor, self.view_permission, self.related)

    def list(self, request):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(self.get_serializer(page, many=True).data)
