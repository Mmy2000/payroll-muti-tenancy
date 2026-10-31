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
