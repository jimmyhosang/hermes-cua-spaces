"""Put the display stack Hermes needs for Bot Desktop, `computer_use` and the browser into a Linux Space.

The default `linux` image has an Xfce desktop but not what Hermes launches itself: TigerVNC (Xvnc),
Playwright Chromium, `agent-browser` and `cua-driver`. `desktop-stack.sh` installs the same set as
Hermes's `nousresearch/hermes-sandbox:desktop` image. It is idempotent and needs `sudo` in the Space.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .client import SpaceHandle

logger = logging.getLogger(__name__)

SCRIPT = Path(__file__).with_name("desktop-stack.sh")
REMOTE_PATH = "/tmp/hermes-cua-desktop-stack.sh"
REQUIRED = ("Xvnc", "xfwm4", "xdpyinfo", "cua-driver", "agent-browser")
INSTALL_TIMEOUT_S = 1200


def has_stack(space: SpaceHandle) -> bool:
    check = "for b in " + " ".join(REQUIRED) + '; do command -v "$b" >/dev/null 2>&1 || exit 1; done'
    return space.run(check, 60).exit_code == 0


def ensure_desktop_stack(space: SpaceHandle) -> bool:
    """Install the stack when the Space lacks it. True when it is there afterwards. Never raises:
    the terminal and file tools work without it, so a failure is logged with what to do."""
    try:
        if has_stack(space):
            return True
        logger.info("Installing the desktop stack in Space %s (a few minutes, once)", space.name)
        space.write(REMOTE_PATH, SCRIPT.read_bytes())
        result = space.run(f"bash {REMOTE_PATH}", INSTALL_TIMEOUT_S)
        if result.exit_code != 0:
            tail = "\n".join(result.output.strip().splitlines()[-8:])
            logger.warning(
                "Could not install the desktop stack in Space %s (exit %s). Bot Desktop, computer_use "
                "and the browser need it; the terminal and file tools are unaffected. Last output:\n%s",
                space.name, result.exit_code, tail,
            )
            return False
        return True
    except Exception:  # an install problem must not take the terminal down with it
        logger.warning("Could not install the desktop stack in Space %s", space.name, exc_info=True)
        return False
