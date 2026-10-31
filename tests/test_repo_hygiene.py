import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("apps", "config", "templates", "static", "assets", "ops", "tests", "locale")
SUFFIXES = {".py", ".html", ".css", ".js", ".mjs", ".json", ".po", ".sql", ".toml"}


def test_no_byte_order_marks():
    """A UTF-8 BOM before <!doctype> puts browsers in quirks mode (it happened: PowerShell
    5.1's `Set-Content -Encoding utf8` writes one). Keep every source file BOM-free."""
    offenders = [
        str(path.relative_to(ROOT))
        for base in SOURCE_DIRS
        for path in (ROOT / base).rglob("*")
        if path.suffix in SUFFIXES and b"\xef\xbb\xbf" in path.read_bytes()
    ]
    assert offenders == []


def test_template_comments_are_closed_on_their_line():
    """{# … #} only works on one line; an unclosed one prints the rest as page text."""
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in [*root.glob("templates/**/*.html"), *root.glob("apps/**/templates/**/*.html")]:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "{#" in line and "#}" not in line[line.index("{#"):]:
                offenders.append(f"{path.relative_to(root)}:{number}")
    assert offenders == [], "Use {% comment %} for comments over several lines."


def test_every_search_form_answers_as_you_type():
    """A filter form with no data-live-filter would be the one list that still needs a button."""
    offenders = []
    for path in [*ROOT.glob("templates/**/*.html"), *ROOT.glob("apps/**/templates/**/*.html")]:
        for tag in re.findall(r"<form\b[^>]*>", path.read_text(encoding="utf-8")):
            if 'method="get"' in tag and "data-live-filter" not in tag:
                offenders.append(f"{path.relative_to(ROOT)}: {tag[:60]}")
    assert offenders == []


def test_serializers_live_in_serializers_py():
    """A view handles the request; the shape of the data has its own file. `fields.py` is the
    one other home: reusable field types, not serializers."""
    offenders = []
    for path in ROOT.joinpath("apps").rglob("*.py"):
        parts = path.relative_to(ROOT).parts
        if path.name in ("serializers.py", "fields.py") or {"tests", "migrations"} & set(parts):
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef) and any(
                    "Serializer" in ast.unparse(base) or "serializers." in ast.unparse(base)
                    for base in node.bases):
                offenders.append(f"{path.relative_to(ROOT)}: {node.name}")
    assert offenders == []


def test_every_static_file_a_template_loads_exists():
    """{% static 'x' %} names a file in static/: a missing one silently breaks the page (the user
    and role forms once loaded an iam/js/forms.js that did not exist, so they could not save)."""
    pattern = re.compile(r"""\{%\s*static\s+['"]([^'"]+)['"]""")
    missing = []
    for path in [*ROOT.glob("templates/**/*.html"), *ROOT.glob("apps/**/templates/**/*.html")]:
        for name in pattern.findall(path.read_text(encoding="utf-8")):
            if not (ROOT / "static" / name).exists():
                missing.append(f"{path.relative_to(ROOT)}: {name}")
    assert missing == []
