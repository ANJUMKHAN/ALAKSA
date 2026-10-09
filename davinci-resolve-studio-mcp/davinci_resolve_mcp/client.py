"""Connection management for the DaVinci Resolve scripting API.

External scripting (anything outside Resolve's own Workspace > Scripts menu)
is only available in DaVinci Resolve *Studio*, with
Preferences > System > General > "External scripting using" set to "Local".
"""

from __future__ import annotations

import importlib
import os
import platform
import sys
from typing import Any


class ResolveError(RuntimeError):
    """Raised for any failure talking to Resolve."""


def _default_paths() -> tuple[str, str]:
    system = platform.system()
    if system == "Windows":
        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        api = os.path.join(
            program_data, "Blackmagic Design", "DaVinci Resolve", "Support",
            "Developer", "Scripting",
        )
        lib = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
    elif system == "Darwin":
        api = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        lib = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
    else:
        api = "/opt/resolve/Developer/Scripting"
        lib = "/opt/resolve/libs/Fusion/fusionscript.so"
    return api, lib


def load_scripting_module() -> Any:
    """Import ``DaVinciResolveScript`` using Blackmagic's documented env vars.

    ``RESOLVE_SCRIPT_API`` points at the ``Developer/Scripting`` directory (its
    ``Modules`` subfolder holds the module); ``RESOLVE_SCRIPT_LIB`` points at
    ``fusionscript``. Both fall back to the standard install locations.
    """
    api, lib = _default_paths()
    api = os.environ.setdefault("RESOLVE_SCRIPT_API", api)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", lib)

    for candidate in (os.path.join(api, "Modules"), api):
        if os.path.isdir(candidate) and candidate not in sys.path:
            sys.path.insert(0, candidate)
    try:
        return importlib.import_module("DaVinciResolveScript")
    except ImportError as exc:
        raise ResolveError(
            "Could not import DaVinciResolveScript. Install DaVinci Resolve "
            "Studio, or set RESOLVE_SCRIPT_API to its Developer/Scripting "
            f"folder (tried: {api}). Original error: {exc}"
        ) from exc


class Session:
    """Lazily connects to Resolve and reconnects if the handle goes stale."""

    def __init__(self) -> None:
        self._resolve: Any = None

    def set(self, resolve: Any) -> None:
        self._resolve = resolve

    def resolve(self) -> Any:
        if self._resolve is not None:
            try:
                self._resolve.GetVersionString()
                return self._resolve
            except Exception:
                self._resolve = None
        module = load_scripting_module()
        try:
            resolve = module.scriptapp("Resolve")
        except Exception as exc:
            raise ResolveError(f"scriptapp('Resolve') failed: {exc}") from exc
        if resolve is None:
            raise ResolveError(
                "Could not reach DaVinci Resolve. Make sure Resolve Studio is "
                "running and Preferences > System > General > External "
                "scripting using is set to 'Local'. (The free edition does "
                "not allow external scripting.)"
            )
        self._resolve = resolve
        return resolve


session = Session()
