"""Centralized platform detection and OS-specific path resolution.

Every part of the codebase that needs to know "which OS am I on" or "where
should application data live" must go through this module. No other module
should call `platform.system()`, `sys.platform`, or `os.name` directly, and
no module should hardcode an absolute, OS-specific path. This keeps the
project portable across macOS, Windows, and (in the future) Linux without
scattering conditionals throughout the code base.
"""

from __future__ import annotations

import platform as _platform
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from platformdirs import PlatformDirs

_APP_NAME = "Orquestrador"
_APP_AUTHOR = "Orquestrador"


class OperatingSystem(str, Enum):
    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"
    UNKNOWN = "unknown"


class ShellKind(str, Enum):
    """Which shell abstraction should be used to run subprocesses."""

    POSIX = "posix"
    POWERSHELL = "powershell"


def get_os() -> OperatingSystem:
    system = _platform.system().lower()
    if system == "darwin":
        return OperatingSystem.MACOS
    if system == "windows":
        return OperatingSystem.WINDOWS
    if system == "linux":
        return OperatingSystem.LINUX
    return OperatingSystem.UNKNOWN


def get_shell_kind() -> ShellKind:
    """Return which runner abstraction should execute shell commands.

    macOS and Linux share a POSIX-compatible runner; Windows uses a
    PowerShell-based runner. This is the single place that decision is made.
    """
    return ShellKind.POWERSHELL if get_os() == OperatingSystem.WINDOWS else ShellKind.POSIX


def is_windows() -> bool:
    return get_os() == OperatingSystem.WINDOWS


def is_macos() -> bool:
    return get_os() == OperatingSystem.MACOS


def is_linux() -> bool:
    return get_os() == OperatingSystem.LINUX


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path
    config_dir: Path
    cache_dir: Path
    log_dir: Path
    db_path: Path


def get_app_paths(
    *, app_name: str = _APP_NAME, override_root: Path | str | None = None
) -> AppPaths:
    """Resolve platform-appropriate application directories.

    On macOS this resolves under `~/Library/Application Support/<app>`.
    On Windows it resolves under `%APPDATA%\\<app>`.
    On Linux it follows the XDG base directory spec.

    `override_root` allows tests and the dev environment to redirect all
    paths under a single temporary directory, without any OS-specific
    branching at the call site.
    """
    if override_root is not None:
        root = Path(override_root)
        data_dir = root / "data"
        config_dir = root / "config"
        cache_dir = root / "cache"
        log_dir = root / "logs"
    else:
        dirs = PlatformDirs(appname=app_name, appauthor=_APP_AUTHOR, roaming=True)
        data_dir = Path(dirs.user_data_dir)
        config_dir = Path(dirs.user_config_dir)
        cache_dir = Path(dirs.user_cache_dir)
        log_dir = Path(dirs.user_log_dir)

    for path in (data_dir, config_dir, cache_dir, log_dir):
        path.mkdir(parents=True, exist_ok=True)

    return AppPaths(
        data_dir=data_dir,
        config_dir=config_dir,
        cache_dir=cache_dir,
        log_dir=log_dir,
        db_path=data_dir / "orchestrator.db",
    )


def python_executable() -> str:
    """Return the path to the currently running Python interpreter."""
    return sys.executable
