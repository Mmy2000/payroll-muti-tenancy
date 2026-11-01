"""Development only: a whole company to try every screen on, in a client of its own, so the demo
clients stay as they are (apps/platform/console/sample.py).

    manage.py create_sample
    manage.py create_sample --people 300 --months 6
    manage.py create_sample --slug nile2      # another copy, to start clean

A client that already has employees is left alone; one without any, from a run that failed, is
filled in. Refused unless DEBUG is on, because every login gets the same well-known password.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.employees.models import Employee
from apps.org import timezones
from apps.platform.console import sample
from apps.platform.console.services.provisioning import ProvisionTenantCommand, provision_tenant
from apps.platform.tenants.models import Tenant

from .create_demo import PASSWORD


class Command(BaseCommand):
    help = "Create a whole sample company to test the product on (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="nile")
        parser.add_argument("--people", type=int, default=120)
        parser.add_argument("--months", type=int, default=3)

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("create_sample only runs with DEBUG on (it uses a known password).")
        slug = options["slug"]
        tenant = Tenant.objects.filter(slug=slug).first()
        if tenant is None:
            tenant = provision_tenant(ProvisionTenantCommand(
                slug=slug, name="شركة النيل للتجارة",
                domain=f"{slug}.{settings.TENANT_BASE_DOMAIN}", owner_username="owner",
                owner_password=PASSWORD, owner_email=f"owner@{slug}.test",
                owner_display_name="مالك الشركة", head_office_name=sample.HEAD_OFFICE, locale="ar"))
        with tenant_context(tenant.id):
            filled = Employee.objects.exists()
        if filled:
            self.stdout.write(f"Client '{slug}' already has employees: left as it is. "
                              "Use --slug for another copy.")
            return
        with tenant_context(tenant.id), timezone.override(
                timezones.zone(timezones.tenant_zone_name(tenant.id))):
            made = sample.seed(tenant, PASSWORD, people=options["people"], months=options["months"],
                               say=lambda text: self.stdout.write(f"  {text}…"))
        url = f"http://{slug}.{settings.TENANT_BASE_DOMAIN}{settings.SITE_PORT}/"
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{url}   password for every login: {PASSWORD}"))
        self.stdout.write(f"  {made['employees']} employees, {made['punches']} clock times")
        for username, what in [("owner", "Owner, sees everything"), *made["logins"],
                               (made["app"], "Mobile app (employee)")]:
            self.stdout.write(f"  {username:<12} {what}")
