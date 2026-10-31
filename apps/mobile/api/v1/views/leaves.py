"""Leave requests."""

from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from .... import selectors
from ....services import leaves
from .. import serializers as s
from .base import AppView, valid


def _year(request):
    raw = request.GET.get("year")
    return int(raw) if raw else None  # PayRole: a non-number fails (500); kept


class LeavesView(AppView):
    def get(self, request):
        return Response([s.leave(row) for row in selectors.leaves(self.employee(),
                                                                 _year(request))])

    def post(self, request):
        person = self.employee()
        data = valid(s.LeaveCreateSerializer, request.data)
        row = leaves.ask_leave(person, self.member, data["date1"], data["date2"])
        return Response(s.leave(row), status=status.HTTP_201_CREATED)


class LeaveDetailView(AppView):
    def delete(self, request, ser):
        leaves.withdraw_leave(self.employee(status_code=400), self.member, ser)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LeaveBalanceView(AppView):
    def get(self, request):
        return Response(selectors.balance(self.employee(),
                                         _year(request) or timezone.localdate().year))
