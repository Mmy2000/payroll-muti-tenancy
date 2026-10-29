from .base import *  # noqa: F403
from .base import env

SECRET_KEY = "test-secret-key-for-the-test-suite-only"  # 32+ bytes: it signs tokens
DEBUG = False
FIXED_HOSTS = [".localhost", "testserver"]

# Tests create the test database, so they connect as the owner role (CREATEDB). The owner is
# NOT a superuser and every tenant table has FORCE ROW LEVEL SECURITY, so RLS policies apply to
# it exactly as they do to payroll_rw. Never point this at a superuser: superusers bypass RLS.
DATABASES = {
    "default": env.db(
        "TEST_DATABASE_URL",
        default=env("DATABASE_OWNER_URL", default="postgres://payroll_owner@localhost:5432/payroll"),
    )
}
DATABASES["default"]["ATOMIC_REQUESTS"] = False
DATABASES["default"]["TEST"] = {"NAME": "test_payroll"}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed only
FIELD_ENCRYPTION_KEY = derived_dev_key(SECRET_KEY, "field")  # noqa: F405
BLIND_INDEX_KEY = derived_dev_key(SECRET_KEY, "blind")  # noqa: F405

WHATSAPP_CONSOLE = True  # no gateway: messages land in apps.messaging.gateways.OUTBOX
