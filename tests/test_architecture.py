"""The structure of every app (docs/standards/architecture.md), checked so that it can't drift."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "apps"
SUB_APPS = {"platform"}  # a folder of apps, not an app


def _apps() -> list[Path]:
    found = []
    for folder in sorted(p for p in APPS.iterdir() if p.is_dir() and p.name != "__pycache__"):
        if folder.name in SUB_APPS:
            found += sorted(p for p in folder.iterdir() if p.is_dir() and p.name != "__pycache__")
        else:
            found.append(folder)
    return found


def _code(folder: Path = APPS):
    for path in folder.rglob("*.py"):
        if not {"migrations", "tests", "__pycache__"} & set(path.parts):
            yield path


def _name(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def test_json_is_in_api_and_pages_are_in_web():
    misplaced = [_name(app / f"{name}.py") for app in _apps()
                 for name in ("views", "api", "web_api", "serializers", "forms", "urls")
                 if (app / f"{name}.py").exists()]
    assert not misplaced, f"move these into the app's api/ or web/ package: {misplaced}"


def test_routes_are_in_urls_py():
    routed = []
    for path in _code():
        if path.name == "urls.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {t.id for n in tree.body if isinstance(n, ast.Assign) for t in n.targets
                 if isinstance(t, ast.Name)}
        if "urlpatterns" in names:
            routed.append(_name(path))
    assert not routed, f"move these routes into urls.py: {routed}"


ORM_CALLS = {"filter", "exclude", "annotate", "aggregate", "select_related", "prefetch_related",
             "values", "values_list", "order_by", "only", "defer", "distinct", "get_or_create",
             "update_or_create", "bulk_create", "bulk_update", "select_for_update", "save",
             "delete"}
NOT_VIEWS = {"serializers", "forms", "urls", "fields", "__init__"}


def _imported_names(tree) -> set[str]:
    return {alias.asname or alias.name.split(".")[0] for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}


def _queries_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = _imported_names(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        calls_a_module = isinstance(node.value, ast.Name) and node.value.id in modules
        if node.attr == "objects" or (node.attr in ORM_CALLS and not calls_a_module):
            found.append(f"{_name(path)}:{node.lineno}: .{node.attr}")
    return found


def test_views_hold_no_queries():
    """A view reads its input, calls a selector or a service, and answers."""
    views = [path for path in _code() if {"api", "web"} & set(path.parts)
             and "core" not in path.parts and path.stem not in NOT_VIEWS]
    found = [query for path in sorted(views) for query in _queries_in(path)]
    assert not found, "move these to selectors or services:\n" + "\n".join(found)


def test_the_standards_point_at_what_exists():
    """A standard that names files which do not exist stops being followed."""
    wrong = []
    for page in sorted((ROOT / "docs" / "standards").glob("*.md")):
        text = page.read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)#\s]+\.md)", text):
            if not (page.parent / link).exists():
                wrong.append(f"{page.name}: {link}")
        for path in re.findall(r"`((?:apps|tests|config|ops)/[\w./-]+\.py)", text):
            if not (ROOT / path).exists():
                wrong.append(f"{page.name}: {path}")
    assert not wrong, wrong


def test_no_function_assigns_over_an_imported_module():
    """`calendars = calendars.x()` fails only when that line runs, and nothing else reports it."""
    found = []
    for path in _code():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = {alias.asname or alias.name for node in tree.body
                   if isinstance(node, ast.ImportFrom) and "services" in (node.module or "")
                   or isinstance(node, ast.ImportFrom) and node.level
                   for alias in node.names}
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            names = list(ast.walk(function))
            stored = {n.id for n in names if isinstance(n, ast.Name)
                      and isinstance(n.ctx, ast.Store)}
            used_as_module = {n.value.id for n in names if isinstance(n, ast.Attribute)
                              and isinstance(n.value, ast.Name)}
            for name in stored & used_as_module & modules:
                found.append(f"{_name(path)}: {function.name}: {name}")
    assert not found, found


# Lowest first. An app imports its own row and the rows above it, never below.
LAYERS = (
    ("core",),
    ("platform.tenants",),
    ("org",),
    ("iam", "audit", "printing", "platform.jobs"),
    ("policies",),
    ("employees",),
    ("attendance", "compensation", "loans", "adjustments", "devices"),
    ("payroll",),
    ("evaluations", "messaging", "notifications", "mobile", "reports"),
    ("platform.console",),
)
RANK = {app: rank for rank, row in enumerate(LAYERS) for app in row}
# What every app plugs into: the registries, and the check of who may do what.
EVERYONE_USES = ("apps.iam.catalog", "apps.iam.authz", "apps.platform.tenants.features",
                 "apps.platform.jobs.registry")


def _module(path: Path) -> list[str]:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    return parts[:-1] if parts[-1] == "__init__" else parts


def _app_of(parts: list[str]) -> str:
    if len(parts) < 2:
        return ""
    return ".".join(parts[1:3]) if parts[1] == "platform" else parts[1]


def _imports(path: Path):
    """Each import's module, absolute, with the names it brings in."""
    here = _module(path)
    package = here if path.name == "__init__.py" else here[:-1]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module != "__future__":
            base = package[:len(package) - node.level + 1] if node.level else []
            yield node, base + (node.module or "").split(".") if node.module else base


def _dependencies() -> list[tuple[str, str, str]]:
    """(importing app, imported app, where), for what is not everyone's."""
    found = []
    for path in _code():
        if "management" in path.parts:
            continue
        mine = _app_of(_module(path))
        if mine in ("", "platform"):
            continue
        for node, target in _imports(path):
            if target[0] != "apps" or len(target) < 2:
                continue
            names = [".".join(target)] + [".".join([*target, a.name]) for a in node.names]
            if any(name.startswith(EVERYONE_USES) for name in names):
                continue
            theirs = _app_of(target)
            if theirs != mine and theirs != "platform":
                found.append((mine, theirs, f"{_name(path)}:{node.lineno}"))
    return found


def test_every_app_is_in_a_layer():
    missing = [path.relative_to(APPS).as_posix() for path in _apps()
               if path.relative_to(APPS).as_posix().replace("/", ".") not in RANK]
    assert not missing


def test_dependencies_point_down_the_layers():
    upward = [f"{where}: {mine} imports {theirs}" for mine, theirs, where in _dependencies()
              if RANK[theirs] > RANK[mine]]
    assert not upward, "use a domain event or a registry:\n" + "\n".join(upward)


def test_core_imports_no_app():
    assert not [where for mine, _theirs, where in _dependencies() if mine == "core"]


def test_nobody_imports_a_private_name():
    found = [f"{_name(path)}:{node.lineno}: {alias.name}" for path in _code()
             for node, _target in _imports(path) for alias in node.names
             if alias.name.startswith("_") and not alias.name.startswith("__")
             and alias.name != "_"]
    assert not found, found


def test_selectors_only_read():
    writes = {"save", "delete", "create", "bulk_create", "bulk_update", "update_or_create",
              "get_or_create"}
    found = []
    for path in _code():
        if path.stem != "selectors" and "selectors" not in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in writes:
                found.append(f"{_name(path)}:{node.lineno}: .{node.attr}")
    assert not found, found


def test_domain_is_pure():
    """A calculation takes values and gives values, so it can be tested without a database."""
    found = []
    for path in _code():
        if "domain" not in path.parts:
            continue
        found += [f"{_name(path)}:{node.lineno}" for node, target in _imports(path)
                  if target[-1] in {"models", "selectors"} or "services" in target
                  or target[:2] == ["django", "db"]]
    assert not found, found
