"""Errors, in plain words. Every message says what happened and what to do next."""

from __future__ import annotations


class CuaSpacesError(RuntimeError):
    """Something went wrong talking to Cua. The message is safe to show to the user."""


class NotSignedInError(CuaSpacesError):
    pass


class SpaceNotFoundError(CuaSpacesError):
    pass


class SpaceCreateError(CuaSpacesError):
    pass


class UnsupportedSpaceError(CuaSpacesError):
    pass


def explain(exc: BaseException, *, space: str = "") -> CuaSpacesError:
    """Turn an error from the Cua SDK into a CuaSpacesError with a next step.

    The SDK raises `CuaError.<Kind>` classes. We go by the kind name so this keeps working when the
    message wording changes, and we never echo anything that could hold a token.
    """
    if isinstance(exc, CuaSpacesError):
        return exc
    kind = type(exc).__name__
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else kind
    where = f" '{space}'" if space else ""
    if kind in ("Unauthenticated", "PermissionDenied"):
        return NotSignedInError(
            "Cua did not accept your sign-in. Run `cua auth login` in a terminal, then try again."
        )
    if kind == "NotFound":
        return SpaceNotFoundError(
            f"Cua can't find the Space{where}. Run `cua spaces ls` to see your Spaces, "
            "or set the Space to `create` to make a new one."
        )
    if kind in ("AmbiguousSandbox",):
        return SpaceNotFoundError(
            f"More than one Space is called{where}. Use its full id from `cua spaces ls`, "
            "for example `local:name`."
        )
    if kind in ("InvalidPlacement", "InvalidArgument"):
        return SpaceCreateError(
            f"Cua rejected the Space settings: {detail}. Check `on` and `image` in the plugin settings."
        )
    if kind in ("InsufficientDisk",):
        return SpaceCreateError(f"There is not enough free disk space to create a Space: {detail}")
    if kind in ("ProviderNotConfigured", "DaemonNotRunning", "Runtime"):
        return SpaceCreateError(
            f"Cua can't start a Space here yet: {detail}. Run `cua doctor` to see what is missing."
        )
    if kind in ("Timeout",):
        return SpaceCreateError(
            f"The Space{where} took too long to answer. It may still be starting; try again in a minute."
        )
    if kind in ("Transport", "Http", "Closed", "Env"):
        return CuaSpacesError(
            f"Could not reach the Space{where}: {detail}. Check it is running with `cua spaces ls`."
        )
    if kind == "Cloud":
        return SpaceCreateError(f"Cua Cloud said: {detail}. Use `on: local`, or a machine of your own.")
    if kind == "CapabilityMissing" or kind == "SpacesdNotAvailable":
        return UnsupportedSpaceError(
            f"The Space{where} can't run commands for Hermes ({detail}). "
            "Use a Cua Spaces image such as `linux`."
        )
    return CuaSpacesError(f"Cua error{(' for Space' + where) if where else ''}: {detail}")
