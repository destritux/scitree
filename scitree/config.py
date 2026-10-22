"""Minimal bootstrap configuration and OS-specific default root location logic."""

from __future__ import annotations

import json
import os
import platform
import secrets
from pathlib import Path
from typing import Any


def get_recommended_root_path(system_name: str | None = None) -> Path:
    """Return the recommended default root folder path for the operating system.

    Rules:
    - Windows: %USERPROFILE%\\Documents\\sciTree
    - macOS: ~/Documents/sciTree
    - Linux: $XDG_DATA_HOME/scitree if set, otherwise ~/.local/share/scitree,
             falling back to ~/Documents/sciTree
    """
    sys_name = (system_name or platform.system()).lower()
    home = Path.home()

    if sys_name.startswith("win"):
        user_profile = os.environ.get("USERPROFILE")
        base = Path(user_profile) if user_profile else home
        return base / "Documents" / "sciTree"

    if sys_name == "darwin":
        return home / "Documents" / "sciTree"

    # Linux and other POSIX systems
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home and xdg_data_home.strip():
        return Path(xdg_data_home.strip()).expanduser() / "scitree"

    local_share = home / ".local" / "share"
    try:
        if local_share.exists() or home.exists():
            return local_share / "scitree"
    except OSError:
        pass
    return home / "Documents" / "sciTree"


def get_bootstrap_state_file() -> Path:
    """Return the path to the minimal bootstrap state file."""
    override = os.environ.get("SCITREE_STATE_FILE")
    if override:
        return Path(override).expanduser().resolve()

    config_dir_override = os.environ.get("SCITREE_CONFIG_DIR")
    if config_dir_override:
        return Path(config_dir_override).expanduser().resolve() / "bootstrap.json"

    sys_name = platform.system().lower()
    home = Path.home()
    if sys_name.startswith("win"):
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else (home / "AppData" / "Roaming")
        return base / "sciTree" / "bootstrap.json"
    if sys_name == "darwin":
        return home / "Library" / "Application Support" / "sciTree" / "bootstrap.json"

    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config and xdg_config.strip():
        return Path(xdg_config.strip()).expanduser() / "scitree" / "bootstrap.json"
    return home / ".config" / "scitree" / "bootstrap.json"


class BootstrapStateManager:
    """Manages minimal onboarding state (onboarding_completed and effective root_path)."""

    def __init__(self, state_file: Path | None = None) -> None:
        self.state_file = state_file or get_bootstrap_state_file()

    def load(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {
                "onboarding_completed": False,
                "root_path": None,
                "api_token": None,
                "ui_state": {"last_view": "board"},
            }
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return {
                "onboarding_completed": bool(data.get("onboarding_completed", False)),
                "root_path": data.get("root_path"),
                "api_token": data.get("api_token"),
                "ui_state": data.get("ui_state", {"last_view": "board"}),
            }
        except (OSError, json.JSONDecodeError):
            return {
                "onboarding_completed": False,
                "root_path": None,
                "api_token": None,
                "ui_state": {"last_view": "board"},
            }

    def save(
        self,
        onboarding_completed: bool,
        root_path: str | Path | None,
        api_token: str | None = None,
        ui_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.load()
        token = api_token or current.get("api_token") or secrets.token_urlsafe(24)
        payload = {
            "onboarding_completed": bool(onboarding_completed),
            "root_path": str(Path(root_path).expanduser().resolve()) if root_path else None,
            "api_token": token,
            "ui_state": ui_state if ui_state is not None else current.get("ui_state", {"last_view": "board"}),
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def update_ui_state(self, **kwargs: Any) -> dict[str, Any]:
        current = self.load()
        ui_state = dict(current.get("ui_state") or {})
        ui_state.update(kwargs)
        return self.save(
            onboarding_completed=current["onboarding_completed"],
            root_path=current["root_path"],
            api_token=current.get("api_token"),
            ui_state=ui_state,
        )

    def reset(self) -> dict[str, Any]:
        current = self.load()
        payload = {
            "onboarding_completed": False,
            "root_path": None,
            "api_token": current.get("api_token") or secrets.token_urlsafe(24),
            "ui_state": {"last_view": "board"},
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
