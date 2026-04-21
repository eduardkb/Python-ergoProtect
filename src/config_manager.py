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
        logfilePath = C:\\\\Users\\\\user\\\\AppData\\\\Local\\\\ErgoProtect\\\\logs
        DaysToKeepLog = 30

        [autoClick]
        active = False
        activate_key = F6
        milliseconds_stopped = 200
        pixels_threshold = 5

Thread safety
-------------
config.ini must never be written concurrently. All writes are serialised
through a dedicated background writer thread that drains a queue. Callers
never block: set_config() and save_config() are non-blocking; they enqueue
a write task which the writer thread performs in FIFO order.

The in-memory ConfigParser state is protected by a re-entrant lock so that
reads from any thread always see a consistent snapshot.
"""

import configparser
import os
import queue
import sys
import threading
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

    All writes are serialised through a single background writer thread to
    ensure config.ini is never written concurrently by multiple modules.
    The in-memory state is protected by a re-entrant lock for thread-safe reads.

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
        # Re-entrant lock: guards all reads/writes to self._parser
        self._lock = threading.RLock()

        # Write queue: each item is a sentinel or a callable that performs
        # the actual file write. Using a queue serialises all disk writes
        # in FIFO order without ever blocking the calling thread.
        self._write_queue: queue.Queue = queue.Queue()
        self._writer_stop = threading.Event()
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="ConfigWriterThread",
            daemon=True,
        )
        self._writer_thread.start()

        self._load_or_create()

    # ------------------------------------------------------------------
    # Background writer thread
    # ------------------------------------------------------------------

    def _writer_loop(self) -> None:
        """
        Drain the write queue and serialise all config.ini writes.

        Items in the queue are zero-argument callables. A None sentinel
        signals the thread to exit.
        """
        while not self._writer_stop.is_set():
            try:
                task = self._write_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if task is None:
                # Sentinel: exit the loop
                self._write_queue.task_done()
                break

            try:
                task()
            except Exception as exc:
                print(f"[ConfigManager] Writer thread error: {exc}")
            finally:
                self._write_queue.task_done()

    def _enqueue_write(self) -> None:
        """
        Snapshot the current in-memory parser state and enqueue a write task.

        A snapshot is taken immediately (under the lock) so that subsequent
        set_config() calls cannot race with the queued write. The writer
        thread only performs the disk I/O, never modifying the snapshot.
        """
        with self._lock:
            # Snapshot: create a fresh parser and copy all current sections/keys
            snapshot = configparser.ConfigParser()
            for section in self._parser.sections():
                snapshot.add_section(section)
                for key, value in self._parser.items(section):
                    snapshot.set(section, key, value)

        config_path = self.config_path  # capture for closure

        def _do_write():
            try:
                os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
                with open(config_path, "w", encoding="utf-8") as f:
                    snapshot.write(f)
            except OSError as exc:
                print(f"[ConfigManager] Warning: Could not save config — {exc}")

        self._write_queue.put(_do_write)

    def stop_writer(self) -> None:
        """
        Flush all pending writes and stop the background writer thread.

        Should be called during application shutdown to ensure no writes
        are lost. After this call, set_config() and save_config() will
        still enqueue tasks but the writer thread will no longer drain them;
        call this only on final exit.
        """
        self._write_queue.put(None)
        self._writer_thread.join(timeout=5.0)
        self._writer_stop.set()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_or_create(self) -> None:
        """
        Load config.ini if it exists; otherwise create it with defaults.

        Creating on first run ensures the app always has a valid config
        even if the user has never opened the settings panel.
        """
        with self._lock:
            if os.path.exists(self.config_path):
                self._parser.read(self.config_path, encoding="utf-8")
                # Ensure all default sections/keys exist (handles partial files
                # and new keys added in software updates).
                self._apply_defaults_locked()
            else:
                # No config file found — populate with factory defaults
                self._apply_defaults_locked()
                self._enqueue_write()

    def _apply_defaults_locked(self) -> None:
        """
        Add any missing sections or keys from _DEFAULTS without overwriting
        existing user values. Must be called while self._lock is held.

        This lets us add new keys in future versions without breaking existing
        config files.
        """
        changed = False
        for section, keys in _DEFAULTS.items():
            if not self._parser.has_section(section):
                self._parser.add_section(section)
                changed = True
            for key, value in keys.items():
                if not self._parser.has_option(section, key):
                    self._parser.set(section, key, value)
                    changed = True
        if changed:
            self._enqueue_write()

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
        with self._lock:
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
        Set a config value and enqueue an asynchronous persist to disk.

        The in-memory state is updated synchronously (under the lock) so
        subsequent get_config() calls immediately see the new value.
        The disk write is serialised through the writer queue so concurrent
        calls from multiple modules are ordered safely.

        Args:
            section: INI section name.
            key:     Key within that section.
            value:   Value to store (will be converted to string).
        """
        with self._lock:
            if not self._parser.has_section(section):
                self._parser.add_section(section)
            self._parser.set(section, key, str(value))
        # Enqueue the disk write outside the lock to minimise contention.
        self._enqueue_write()

    def save_config(self) -> None:
        """
        Enqueue an explicit persist of the current in-memory configuration.

        Prefer set_config() for normal usage (it calls this automatically).
        Use save_config() only when you need to flush multiple in-memory
        changes that were made by directly manipulating the parser (internal use).

        The write is asynchronous and serialised through the writer queue,
        ensuring no concurrent writes to config.ini.
        """
        self._enqueue_write()
