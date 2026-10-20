"""Directory-install entry point for Hermes.

`hermes plugins install` copies this repository into `~/.hermes/plugins/cua-spaces/`
and loads this file. The code lives in the `hermes_cua_spaces` package next to it, so put
this directory on `sys.path` and re-export `register`.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from hermes_cua_spaces import CuaSpacesProvider, register  # noqa: E402,F401

__all__ = ["CuaSpacesProvider", "register"]
