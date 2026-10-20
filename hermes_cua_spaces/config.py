"""Plugin settings. No secrets live here: sign-in comes from `cua auth login`."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

CREATE = "create"
DEFAULT_IMAGE = "linux"
DEFAULT_CREATE_TIMEOUT_S = 600

# Environment variables win over config.yaml, so one shell can point Hermes at a different Space.
ENV_SPACE = "HERMES_CUA_SPACE"
ENV_ON = "HERMES_CUA_ON"
ENV_IMAGE = "HERMES_CUA_IMAGE"


@dataclass(frozen=True)
class Settings:
    """What the user chose.

    space   "create" makes a Space; anything else names (or gives the id of) an existing one.
    on      where to create: "local", "cloud", "host:<machine>" or a machine name. "" = Cua default.
    image   image for a new Space.
    """

    space: str = CREATE
    on: str = ""
    image: str = DEFAULT_IMAGE
    create_timeout_s: int = DEFAULT_CREATE_TIMEOUT_S

    @property
    def creates(self) -> bool:
        return self.space.strip().lower() == CREATE

    def validate(self) -> "Settings":
        if not self.space.strip():
            raise ValueError("The Space setting is empty. Use `create` or the name of a Space.")
        if self.create_timeout_s <= 0:
            raise ValueError("create_timeout must be a positive number of seconds.")
        return self


def load_settings(
    get_config: Optional[Callable[..., Any]] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> Settings:
    """Read settings from Hermes plugin config (`get_config(key, default=...)`), then the environment."""
    env = os.environ if environ is None else environ

    def cfg(key: str, default: Any) -> Any:
        if get_config is None:
            return default
        try:
            value = get_config(key, default=default)
        except Exception:  # a broken config read must not stop the backend from loading
            return default
        return default if value is None else value

    space = str(env.get(ENV_SPACE) or cfg("space", CREATE)).strip()
    on = str(env.get(ENV_ON) or cfg("on", "")).strip()
    image = str(env.get(ENV_IMAGE) or cfg("image", DEFAULT_IMAGE)).strip() or DEFAULT_IMAGE
    try:
        timeout = int(cfg("create_timeout", DEFAULT_CREATE_TIMEOUT_S))
    except (TypeError, ValueError):
        timeout = DEFAULT_CREATE_TIMEOUT_S
    return Settings(space=space or CREATE, on=on, image=image, create_timeout_s=timeout).validate()


_SAFE = re.compile(r"[^a-z0-9-]+")


def space_name_for(task_id: str, profile: str = "") -> str:
    """A stable, valid Space name for a Hermes task: `hermes-<task>`."""
    base = _SAFE.sub("-", f"{task_id or 'default'}".lower()).strip("-")[:24] or "default"
    return f"hermes-{base}"
