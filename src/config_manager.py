"""
config_manager.py - Configuration Manager for ErgoProtect
----------------------------------------------------------
Handles reading and writing the application's config.ini file using
Python's built-in configparser. The INI format was chosen because it is
human-readable and easy to edit manually without a special tool.

INI File Structure:
    [section]
    key = value

    Example:
        [General]
        logfilePath = C:\\Users\\user\\AppData\\Local\\ErgoProtect\\logs
        DaysToKeepLog = 30

        [autoClick]
        active = False
        activate_key = F6
        milliseconds_stopped = 200
        pixels_threshold = 5
"""

import configparser
import os
import sys
from typing import Any


def _default_app_dir() -> str:
    """
    Return the folder that contains the running executable (frozen) or the
    project root (source). This is the standard location for config.ini and
    the default log directory.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # Running from source: go up from src/ to project root.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Path to the config file, located next to the executable / project root.
_CONFIG_PATH = os.path.join(_default_app_dir(), "config.ini")

# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------
_DEFAULTS: dict[str, dict[str, str]] = {
    # ---------------------------------------------------------------------------
    # [General] — application-wide settings
    #
    #   logfilePath    = <exe dir>   → Log files live next to the executable by
    #                                  default so users can find them easily.
    #   DaysToKeepLog  = 30          → 30 days is a sensible balance between
    #                                  diagnostic history and disk usage for a
    #                                  long-running healthcare application.
    # ---------------------------------------------------------------------------
    "General": {
        "logfilePath": _default_app_dir(),
        "DaysToKeepLog": "30",
    },
    # ---------------------------------------------------------------------------
    # [autoClick] — AutoClick module settings
    #
    #   active             = False  → AutoClick should be OFF at startup for safety.
    #   activate_key       = F6     → Uncommon enough to avoid accidental triggers.
    #   milliseconds_stopped = 200  → 200ms is long enough to ignore micro-wobble
    #                                  but short enough for comfortable use.
    #   pixels_threshold   = 5      → Accounts for minor involuntary hand tremor
    #                                  without treating real movement as stillness.
    # ---------------------------------------------------------------------------
    "autoClick": {
        "active": "False",
        "activate_key": "F6",
        "milliseconds_stopped": "200",
        "pixels_threshold": "5",
    },
    # ---------------------------------------------------------------------------
    # [keyboardActions] — KeyboardActions module settings
    #
    #   leftClickKey   = F7   → F7 is rarely used by applications, minimising
    #                           accidental triggers during normal typing.
    #   rightClickKey  = F8   → Same rationale; adjacent key keeps muscle memory
    #                           intuitive (F7=left, F8=right).
    #   doubleClickKey = F9   → Continues the sequential F-key pattern.
    #   leftDragDrop   = F10  → F10 is slightly separated (by F9 gap on many
    #                           keyboards), which helps avoid accidental activation
    #                           of the drag-hold while performing single clicks.
    # ---------------------------------------------------------------------------
    "keyboardActions": {
        "leftClickKey":   "F7",
        "rightClickKey":  "F8",
        "doubleClickKey": "F9",
        "leftDragDrop":   "F10",
    },
}


class ConfigManager:
    """
    Manages reading and writing ErgoProtect's configuration file.

    Usage:
        cfg = ConfigManager()
        value = cfg.get_config("autoClick", "activate_key", "F6")
        cfg.set_config("autoClick", "active", "True")
    """

    def __init__(self, config_path: str = _CONFIG_PATH) -> None:
        """
        Initialize the manager and load (or create) config.ini.

        Args:
            config_path: Path to the .ini file. Defaults to project root.
        """
        self.config_path = config_path
        self._parser = configparser.ConfigParser()
        self._load_or_create()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_or_create(self) -> None:
        """
        Load config.ini if it exists; otherwise create it with defaults.

        Creating on first run ensures the app always has a valid config
        even if the user has never opened the settings panel.
        """
        if os.path.exists(self.config_path):
            self._parser.read(self.config_path, encoding="utf-8")
            # Ensure all default sections/keys exist (handles partial files
            # and new keys added in software updates).
            self._apply_defaults()
        else:
            # No config file found — populate with factory defaults
            self._apply_defaults()
            self.save_config()

    def _apply_defaults(self) -> None:
        """
        Add any missing sections or keys from _DEFAULTS without overwriting
        existing user values. This lets us add new keys in future versions
        without breaking existing config files.
        """
        for section, keys in _DEFAULTS.items():
            if not self._parser.has_section(section):
                self._parser.add_section(section)
            for key, value in keys.items():
                if not self._parser.has_option(section, key):
                    self._parser.set(section, key, value)
        # Persist any newly added defaults immediately.
        self.save_config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_config(self, section: str, key: str, default: Any = None) -> str:
        """
        Retrieve a config value as a string.

        Args:
            section: INI section name (e.g. "General").
            key:     Key within that section (e.g. "logfilePath").
            default: Value returned if the section/key does not exist.

        Returns:
            The stored string value, or `default` if not found.
        """
        try:
            return self._parser.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def get_bool(self, section: str, key: str, default: bool = False) -> bool:
        """
        Convenience wrapper that returns a boolean from a config value.

        configparser stores everything as strings; this converts "True"/"False"
        into Python booleans so callers don't have to do string comparison.
        """
        raw = self.get_config(section, key, str(default))
        return raw.strip().lower() in ("true", "1", "yes")

    def get_int(self, section: str, key: str, default: int = 0) -> int:
        """
        Convenience wrapper that returns an integer from a config value.
        Falls back to `default` if the value cannot be parsed as int.
        """
        try:
            return int(self.get_config(section, key, str(default)))
        except (ValueError, TypeError):
            return default

    def set_config(self, section: str, key: str, value: Any) -> None:
        """
        Set a config value and immediately persist it to disk.

        Saving immediately (rather than batching) ensures no settings are
        lost if the app crashes or is forcefully closed.

        Args:
            section: INI section name.
            key:     Key within that section.
            value:   Value to store (will be converted to string).
        """
        if not self._parser.has_section(section):
            self._parser.add_section(section)
        self._parser.set(section, key, str(value))
        self.save_config()

    def save_config(self) -> None:
        """
        Write the current in-memory configuration to disk.

        Uses a try/except so that a read-only filesystem or permission
        error doesn't crash the application — it simply skips the save
        and logs a warning.
        """
        try:
            # Ensure the directory exists (important when running from dist/)
            os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                self._parser.write(f)
        except OSError as exc:
            # Non-fatal: config will be re-created on next launch
            print(f"[ConfigManager] Warning: Could not save config — {exc}")
