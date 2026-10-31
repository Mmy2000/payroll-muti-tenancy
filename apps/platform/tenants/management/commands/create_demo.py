"""Development only: a platform admin and two demo clients to sign in to and click through,
with example pay set-up and employees (apps/platform/console/demo.py).

    manage.py create_demo

Safe to run again: what already exists is left alone. Refused unless DEBUG is on, because every
login gets the same well-known password.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.tenancy import tenant_context
from apps.iam.catalog import MANAGER, VIEWER
from apps.iam.models import Membership, Role, User
from apps.iam.services import assign_role
from apps.org import timezones
from apps.org.models import Branch
from apps.platform.console import demo
from apps.platform.console.services.provisioning import ProvisionTenantCommand, provision_tenant
from apps.platform.tenants.models import Tenant

PASSWORD = "Demo-Pass-2026"
PLATFORM_ADMIN = "admin@platform.test"
CLIENTS = [  # slug, name, owner's email, other branches
    ("demo", "Demo Company", "owner@demo.test", ["Alexandria"]),
    ("acme", "Acme Industries", "owner@acme.test", []),
]
MEMBERS = [  # client, username, display name, role, branch names (None: every branch)
    ("demo", "manager", "Mona Manager", MANAGER, ["Alexandria"]),
    ("demo", "viewer", "Victor Viewer", VIEWER, None),
]


class Command(BaseCommand):
    help = "Create a platform admin and two demo clients with users (development only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("create_demo only runs with DEBUG on (it uses a known password).")

        if not User.objects.filter(email=PLATFORM_ADMIN).exists():
            User.objects.create_superuser(email=PLATFORM_ADMIN, password=PASSWORD,
                                          display_name="Platform Admin")
            self.stdout.write(f"Platform admin {PLATFORM_ADMIN} created.")

        for slug, name, owner_email, branches in CLIENTS:
            tenant = Tenant.objects.filter(slug=slug).first()
            if tenant is None:
                tenant = provision_tenant(ProvisionTenantCommand(
                    slug=slug, name=name, domain=f"{slug}.{settings.TENANT_BASE_DOMAIN}",
                    owner_username="owner", owner_password=PASSWORD, owner_email=owner_email,
                    owner_display_name=f"{name} Owner", locale="en"))
                self.stdout.write(f"Client '{slug}' created.")
            with tenant_context(tenant.id):
                for code, branch_name in enumerate(branches, start=2):
                    Branch.objects.get_or_create(code=code, defaults={"name": branch_name})
                for client, username, display_name, role, scope in MEMBERS:
                    if client == slug:
                        self._member(slug, username, display_name, role, scope)
                demo.seed_pay_setup()
                demo.seed_employees(demo.PEOPLE if slug == "demo" else demo.PEOPLE[:2])
                with timezone.override(timezones.zone(timezones.tenant_zone_name(tenant.id))):
                    demo.seed_attendance()
                    demo.seed_pay_entries()
                    demo.seed_payroll()
                    demo.seed_evaluations()
                if slug == "demo":
                    demo.seed_integrations(tenant, PASSWORD)

        base = f"{settings.TENANT_BASE_DOMAIN}{settings.SITE_PORT}"
        rows = [("Platform admin", f"http://admin.{base}/", PLATFORM_ADMIN)]
        rows += [(name, f"http://{slug}.{base}/", "owner") for slug, name, *_rest in CLIENTS]
        names = {slug: name for slug, name, *_rest in CLIENTS}
        rows += [(f"{names[client]} ({role})", f"http://{client}.{base}/", username)
                 for client, username, _name, role, _scope in MEMBERS]
        rows.append(("Demo (mobile app)", f"http://demo.{base}/api/v1/", "ahmed"))
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Password for every login: {PASSWORD}"))
        for who, url, login in rows:
            self.stdout.write(f"  {who:<26} {url:<32} {login}")

    def _member(self, slug, username, display_name, role, branch_names):
        if Membership.objects.filter(username=username).exists():
            return
        user = User.objects.create_user(email=f"{username}@{slug}.test", password=PASSWORD,
                                        display_name=display_name)
        membership = Membership.objects.create(user=user, username=username)
        branches = (None if branch_names is None
                    else list(Branch.objects.filter(name__in=branch_names)))
        assign_role(membership, Role.objects.get(code=role), branches=branches)
        self.stdout.write(f"  {slug}: {username} ({role}) created.")
