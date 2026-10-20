"""One background event loop for the async Cua SDK.

Hermes runs tools on plain threads and the Cua SDK is async, so every SDK call goes through a single
loop that lives on its own daemon thread. That also lets many Hermes sessions share one SDK runtime.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Coroutine, Optional, TypeVar

T = TypeVar("T")

_lock = threading.Lock()
_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _lock:
        if _loop is not None and _loop.is_running():
            return _loop
        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run() -> None:
            asyncio.set_event_loop(loop)
            loop.call_soon(ready.set)
            loop.run_forever()

        threading.Thread(target=run, name="hermes-cua-spaces", daemon=True).start()
        ready.wait(5)
        _loop = loop
        return loop


def run_sync(coro: Coroutine[Any, Any, T], timeout: Optional[float] = None) -> T:
    """Run a coroutine on the shared loop and wait for it. Raises TimeoutError on timeout."""
    future = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    try:
        return future.result(timeout)
    except FutureTimeout:
        future.cancel()
        raise TimeoutError("timed out waiting for Cua") from None
