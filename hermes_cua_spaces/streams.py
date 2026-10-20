"""What Hermes needs to host Bot Desktop, `computer_use` and the browser in a Space.

Hermes asks the terminal environment for `exec_prefix()`: the argv of a local, long-lived process
whose stdin, stdout and stderr are a process inside the Space (the shape of `docker exec -i`).
Here that is `cua sandbox exec -i`, so it needs the `cua` command line tool, version with `--stdin`.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import Optional

logger = logging.getLogger(__name__)

INSTALL_HINT = (
    "Install the Cua command line tool with `curl -fsSL https://cua.ai/install.sh | sh` "
    "(or upgrade it with `cua update`), then start Hermes again."
)

_lock = threading.Lock()
_supported: dict[str, bool] = {}
_warned: set[str] = set()


def hermes_sets_start_dir() -> bool:
    """True when this Hermes lets a provider declare `default_cwd` (and passes it `cwd="~"`)."""
    try:
        from agent.terminal_env_provider import TerminalEnvironmentProvider
    except ImportError:
        return False
    return hasattr(TerminalEnvironmentProvider, "default_cwd")


def hermes_hosts_streams() -> bool:
    """True when this Hermes can place Bot Desktop, `computer_use` and the browser in a plugin sandbox."""
    try:
        from agent.terminal_env_provider import TerminalEnvironmentProvider
    except ImportError:
        return False
    return hasattr(TerminalEnvironmentProvider, "supports_streams")


def _warn_once(key: str, message: str) -> None:
    with _lock:
        if key in _warned:
            return
        _warned.add(key)
    logger.warning(message)


def _has_stdin_flag(cli: str) -> bool:
    with _lock:
        if cli in _supported:
            return _supported[cli]
    try:
        out = subprocess.run(
            [cli, "sandbox", "exec", "--help"], capture_output=True, text=True, timeout=30
        )
        ok = out.returncode == 0 and "--stdin" in (out.stdout + out.stderr)
    except (OSError, subprocess.SubprocessError):
        ok = False
    with _lock:
        _supported[cli] = ok
    return ok


def forget_cli_checks() -> None:
    """Forget what was learned about the `cua` command (for tests)."""
    with _lock:
        _supported.clear()
        _warned.clear()


def stream_argv(space_ref: str, user: Optional[str] = None) -> Optional[list[str]]:
    """`cua sandbox exec -i [--user U] <space> --`, or None (with one logged warning) when the `cua`
    command is missing or too old to stream."""
    cli = shutil.which("cua")
    if cli is None:
        _warn_once(
            "missing",
            "Bot Desktop, computer_use and the browser cannot follow the terminal into the Cua Space: "
            "the `cua` command is not on PATH. " + INSTALL_HINT,
        )
        return None
    if not _has_stdin_flag(cli):
        _warn_once(
            "old",
            f"Bot Desktop, computer_use and the browser cannot follow the terminal into the Cua Space: "
            f"{cli} is too old (its `sandbox exec` has no `-i/--stdin`). " + INSTALL_HINT,
        )
        return None
    argv = [cli, "sandbox", "exec", "-i"]
    if user:
        argv += ["--user", user]
    return argv + [space_ref, "--"]
