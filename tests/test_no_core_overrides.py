"""The plugin must only use Hermes's public plugin interfaces and never change Hermes itself.

Hermes's plugin catalog rules break when a plugin overwrites Hermes core. This test imports Hermes,
snapshots every attribute of every Hermes module and class that is loaded, loads the plugin the way
Hermes does, opens environments on Linux and Windows stand-in Spaces, and fails if anything in
Hermes changed.
"""
import importlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("tools.environments.base", reason="needs Hermes installed")


# Modules the plugin has touched in any version, plus the ones Hermes's file and terminal tools live in.
PRELOAD = (
    "tools.file_operations",
    "tools.environments.base",
    "tools.terminal_tool",
    "tools.file_tools",
    "tools.registry",
    "tools.fuzzy_match",
    "agent.terminal_env_provider",
)


def _hermes_root() -> Path:
    import tools

    return Path(tools.__file__).resolve().parent.parent


def _is_hermes(mod) -> bool:
    f = getattr(mod, "__file__", None)
    if not f:
        return False
    try:
        Path(f).resolve().relative_to(_hermes_root())
    except ValueError:
        return False
    return "site-packages" not in str(f) or "hermes" in str(f).lower()


def _snapshot() -> dict:
    snap: dict = {}
    for name, mod in list(sys.modules.items()):
        if mod is None or not _is_hermes(mod):
            continue
        for attr, value in list(vars(mod).items()):
            snap[(name, attr)] = id(value)
            if isinstance(value, type) and getattr(value, "__module__", None) == name:
                for cattr, cvalue in list(vars(value).items()):
                    if cattr in ("__dict__", "__weakref__"):
                        continue
                    snap[(name, attr, cattr)] = id(cvalue)
            # Registries are plain dicts and lists: compare their keys too.
            if attr.lower().endswith(("registry", "_registry", "tools")) and isinstance(value, dict):
                snap[(name, attr, "keys")] = tuple(sorted(map(str, value)))
    return snap


class _Ctx:
    """The part of Hermes's plugin context a terminal backend plugin may call."""

    def __init__(self):
        self.providers = []

    def get_config(self, key, default=None):
        return default

    def register_terminal_environment_provider(self, provider):
        self.providers.append(provider)


def test_loading_and_using_the_plugin_changes_nothing_in_hermes(tmp_path):
    for name in PRELOAD:
        try:
            importlib.import_module(name)
        except Exception:
            pass  # a Hermes without that module has nothing there to change
    before = _snapshot()
    assert len(before) > 500, "the snapshot should cover Hermes"

    import hermes_cua_spaces as plugin

    ctx = _Ctx()
    plugin.register(ctx)
    assert len(ctx.providers) == 1 and ctx.providers[0].name == "cua"

    # Open environments the way Hermes does, on Linux and (when PowerShell is around) Windows.
    from conftest import FakeClient, LocalShellSpace

    space = LocalShellSpace(tmp_path)
    provider = ctx.providers[0]
    provider._client_override = FakeClient(space)
    env = provider.create_environment(cwd="~", timeout=30, task_id="n")
    try:
        env.execute("echo hi")
    finally:
        env.cleanup()

    try:
        from test_windows import PWSH, OneSpaceClient, PowerShellSpace
    except Exception:
        PWSH = None
    if PWSH is not None:
        wprov = plugin.CuaSpacesProvider(
            get_config=lambda k, default=None: default,
            client=OneSpaceClient(PowerShellSpace(tmp_path / "w", with_bash=False)),
        )
        (tmp_path / "w").mkdir()
        wenv = wprov.create_environment(cwd="~", timeout=30, task_id="w")
        try:
            wenv.execute("echo hi")
            wenv.execute("Write-Output hi", bounded_capture=True)
        finally:
            wenv.cleanup()

    after = _snapshot()
    changed = sorted(k for k in before if k in after and before[k] != after[k])
    removed = sorted(k for k in before if k not in after)
    assert not changed and not removed, f"the plugin changed Hermes: {changed[:10]} removed: {removed[:10]}"


def test_plugin_source_never_assigns_into_hermes():
    """A second guard on the source itself: no setattr and no assignment into Hermes modules."""
    import ast

    root = Path(__file__).resolve().parents[1] / "hermes_cua_spaces"
    hermes_names = {"tools", "agent", "hermes_cli", "gateway", "hermes_constants"}
    problems = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in hermes_names:
                imported.update(a.asname or a.name for a in node.names)
            if isinstance(node, ast.Import):
                imported.update((a.asname or a.name).split(".")[0] for a in node.names if a.name.split(".")[0] in hermes_names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("setattr", "delattr"):
                problems.append(f"{path.name}:{node.lineno} {node.func.id}")
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for t in targets:
                if not isinstance(t, (ast.Attribute, ast.Subscript)):
                    continue
                base = t
                while isinstance(base, (ast.Attribute, ast.Subscript)):
                    base = base.value
                if isinstance(base, ast.Name) and base.id in imported | hermes_names:
                    problems.append(f"{path.name}:{node.lineno} assigns into {base.id}")
    assert not problems, problems
    assert not (root / "windows_files.py").exists()
