"""The browser's API for WhatsApp: the link (start, look, unlink), the wording, a test, sending
a run's payslips, and sending a failed message again."""

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .. import services
from .serializers import PayslipsSerializer, TestSerializer, WordingSerializer


def _valid(serializer_class, data) -> dict:
    payload = serializer_class(data=data)
    payload.is_valid(raise_exception=True)
    return dict(payload.validated_data)


class WhatsAppViewSet(viewsets.GenericViewSet):
    """/whatsapp/link/ GET (look) POST (start) DELETE (unlink); /whatsapp/wording/ PUT;
    /whatsapp/test/ POST; /whatsapp/payslips/ POST; /whatsapp/<id>/again/ POST."""

    required_permissions = {"link": services.LINK, "wording": services.LINK,
                            "test": services.LINK, "payslips": services.SEND,
                            "again": services.SEND}

    @action(detail=False, methods=["get", "post", "delete"])
    def link(self, request):
        if request.method == "POST":
            return Response(services.start_link(actor=request.actor))
        if request.method == "DELETE":
            services.unlink(actor=request.actor)
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(services.look(actor=request.actor))

    @action(detail=False, methods=["put"])
    def wording(self, request):
        link = services.save_wording(services.WordingInput(**_valid(WordingSerializer,
                                                                    request.data)),
                                     actor=request.actor)
        return Response({"payslip_message": link.payslip_message,
                         "gap_seconds": link.gap_seconds})

    @action(detail=False, methods=["post"])
    def test(self, request):
        message = services.send_test(_valid(TestSerializer, request.data)["phone"],
                                     actor=request.actor)
        return Response({"id": message.pk}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"])
    def payslips(self, request):
        data = _valid(PayslipsSerializer, request.data)
        outcome = services.send_payslips(data["run_id"], slip_ids=data["slip_ids"] or None,
                                         again=data["again"], actor=request.actor)
        return Response({"queued": outcome.queued, "no_phone": outcome.no_phone,
                         "already": outcome.already}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def again(self, request, pk=None):
        message = services.send_again(int(pk), actor=request.actor)
        return Response({"id": message.pk, "status": message.status})
