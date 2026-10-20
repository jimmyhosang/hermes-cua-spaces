"""The Hermes terminal environment that runs every command inside a Cua Space."""

from __future__ import annotations

import logging
import os
import shlex
import threading
import uuid
from typing import Any, Callable, Optional

from tools.environments.base import BaseEnvironment

from .client import ExecResult, SpaceHandle, SpacesClient
from .config import Settings, space_name_for
from .errors import CuaSpacesError

logger = logging.getLogger(__name__)

# Hermes passes its generic container default ("/root") when the user set no working folder.
_GENERIC_CWDS = ("", "/root", "~")


class _SpaceProcess:
    """A process-like handle for one command running in a Space.

    Hermes reads `stdout` until it closes and polls `returncode`, so we run the blocking Cua call on a
    thread, write its output into a pipe and close the pipe when the command ends.
    """

    def __init__(self, work: Callable[[], tuple[str, int]], cancel: Callable[[], None]) -> None:
        self._cancel = cancel
        self._done = threading.Event()
        self._returncode: Optional[int] = None
        read_fd, write_fd = os.pipe()
        self._writer = os.fdopen(write_fd, "wb")
        self.stdout = os.fdopen(read_fd, "r", encoding="utf-8-sig", errors="replace")
        threading.Thread(target=self._run, args=(work,), name="hermes-cua-command", daemon=True).start()

    def _run(self, work: Callable[[], tuple[str, int]]) -> None:
        try:
            output, code = work()
            self._returncode = code
            self._writer.write(output.encode("utf-8", errors="replace"))
        except Exception:
            logger.debug("command in Space failed", exc_info=True)
            if self._returncode is None:
                self._returncode = 1
        finally:
            try:
                self._writer.close()
            except OSError:
                pass
            self._done.set()

    @property
    def returncode(self) -> Optional[int]:
        return self._returncode

    def poll(self) -> Optional[int]:
        return self._returncode if self._done.is_set() else None

    def kill(self) -> None:
        try:
            self._cancel()
        except Exception:
            logger.debug("cancel failed", exc_info=True)

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        self._done.wait(timeout=timeout)
        return self._returncode


class CuaSpaceEnvironment(BaseEnvironment):
    """Runs each Hermes command as `bash -c` inside a Cua Space.

    Terminal, file and code tools all go through `execute()`, so they all land in the Space.
    """

    # Input for a command is staged as a file in the Space (see _run_bash), not embedded in the command.
    _stdin_mode = "payload"
    _snapshot_timeout = 60

    def __init__(
        self,
        *,
        cwd: str,
        timeout: int,
        task_id: str = "default",
        settings: Settings,
        client: SpacesClient,
        persistent: bool = True,
        **_unused: Any,
    ) -> None:
        self._settings = settings
        self._client = client
        self._persistent = persistent
        self._lock = threading.Lock()
        self._closed = False

        if settings.creates:
            self._space, created = client.ensure(space_name_for(task_id), settings)
            self._delete_on_cleanup = not persistent
            logger.info("Cua Space %s %s", self._space.name, "created" if created else "reused")
        else:
            self._space = client.attach(settings.space)
            self._delete_on_cleanup = False  # a Space you named is yours: never delete it

        if cwd in _GENERIC_CWDS:
            cwd = self._space.home()
        super().__init__(cwd=cwd, timeout=timeout)
        self.init_session()

    # -- identity (used in messages and by the README's "watch it live" step) --
    @property
    def space_name(self) -> str:
        return self._space.name

    @property
    def space_id(self) -> str:
        return self._space.id

    # -- running commands --
    def _run_bash(
        self, cmd_string: str, *, login: bool = False, timeout: int = 120, stdin_data: Optional[str] = None
    ) -> _SpaceProcess:
        run_id = uuid.uuid4().hex[:16]
        script = f": hermes-cua-run-{run_id}\n{cmd_string}"
        staged: Optional[str] = None
        if stdin_data is not None:
            staged = self._staged_stdin_path()
        shell = "bash -l -c" if login else "bash -c"

        def exec_fn() -> tuple[str, int]:
            body = script
            if staged is not None:
                self._call(lambda sp: sp.write(staged, (stdin_data or "").encode("utf-8", "surrogateescape")))
                body = f": hermes-cua-run-{run_id}\n" + self._redirect_stdin_from_file(cmd_string, staged)
            line = f"exec {shell} {shlex.quote(body)} 2>&1"
            try:
                result: ExecResult = self._call(lambda sp: sp.run(line, timeout))
            except CuaSpacesError as exc:
                return (f"[Cua Space error: {exc}]\n", 1)
            return (result.output, result.exit_code)

        def cancel() -> None:
            # Best effort: stop the command's process tree. The Space has no per-command cancel.
            pattern = shlex.quote(f"[h]ermes-cua-run-{run_id}")
            kill = (
                f"for p in $(pgrep -f {pattern}); do pkill -TERM -P $p; kill -TERM $p; done; "
                f"sleep 1; for p in $(pgrep -f {pattern}); do pkill -KILL -P $p; kill -KILL $p; done; true"
            )
            try:
                self._space.run(kill, 20)
            except Exception:
                logger.debug("could not stop command %s in the Space", run_id, exc_info=True)

        return _SpaceProcess(exec_fn, cancel)

    def _call(self, fn):
        """Run `fn(space)`; if the connection dropped, reconnect once and retry."""
        try:
            return fn(self._space)
        except CuaSpacesError:
            with self._lock:
                try:
                    self._space = self._client.attach(self._space.id)
                except CuaSpacesError:
                    raise
            return fn(self._space)

    # -- cleanup --
    def cleanup(self) -> None:
        with self._lock:
            if self._closed or getattr(self, "_space", None) is None:
                return
            self._closed = True
            if not self._delete_on_cleanup:
                logger.info("Leaving Cua Space %s running", self._space.name)
                return
            try:
                self._client.delete(self._space.id)
                logger.info("Deleted Cua Space %s", self._space.name)
            except Exception as exc:
                self._closed = False  # let a later cleanup try again
                logger.warning(
                    "Could not delete Cua Space %s: %s. Delete it with `cua spaces delete %s`.",
                    self._space.name, exc, self._space.name,
                )
