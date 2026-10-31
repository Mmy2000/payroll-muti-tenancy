"""The structure of every app (docs/standards/architecture.md), checked so that it can't drift."""

import ast
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
