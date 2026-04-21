"""
AppLogging.py - Centralised Application Logger for ErgoProtect
--------------------------------------------------------------
Provides a shared, thread-safe logging system for all ErgoProtect modules.

Key design decisions
--------------------
- Log files are written in standard CSV format for easy parsing/import.
- One new log file is created per calendar day (yyyy-mm-dd_appLog.csv).
- The log directory defaults to the folder containing the executable (or
  project root when running from source), and can be overridden via config.ini.
- A bounded queue (FIFO, max 500 entries) decouples log producers from the
  file writer so that bursts of simultaneous log calls never block callers.
  A single background daemon thread drains the queue and writes to disk.
- On startup, old log files are deleted according to the DaysToKeepLog
  parameter in config.ini ([General] section). Default: 30 days.
- Thread-safe: all public functions are safe to call from any thread.

CSV columns
-----------
timestamp, module, level, message

Healthcare-application rationale
---------------------------------
This app is designed to reduce RSI / MSD. Robust logging is essential so
crashes or unexpected behaviours (e.g. a drag-drop that was not released)
can be diagnosed without requiring the user to reproduce the problem live.

Usage
-----
    from src.AppLogging import log_info, log_warning, log_error, log_debug
    from src.AppLogging import init_logging, cleanup_old_logs

    # Called once at startup (main.py):
    init_logging(log_dir="/path/to/logs", days_to_keep=30)

    # Called from any module at any time:
    log_info("KeyboardActions", "Service started.")
    log_warning("KeyboardActions", "Unknown key ignored: %s", key_name)
    log_error("KeyboardActions", "Unexpected exception", exc_info=True)
    log_debug("KeyboardActions", "Poll tick, active=%s", is_active)
"""

import csv
import datetime
import logging
import os
import queue
import sys
import threading
import traceback
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Queue capacity: 500 entries is enough to absorb any realistic burst while
# keeping memory usage negligible (each entry is a small tuple of strings).
_QUEUE_MAX_SIZE: int = 500

# Background writer polls the queue this often (seconds) to flush and rotate.
_WRITER_POLL_S: float = 0.1

# Default number of days to retain log files.
_DEFAULT_DAYS_TO_KEEP: int = 30

# CSV column headers.
_CSV_HEADERS = ["timestamp", "module", "level", "message"]

# Log file name suffix.
_LOG_SUFFIX: str = "_appLog.csv"

# Module identifier for internal log messages.
_SELF = "AppLogging"

# ---------------------------------------------------------------------------
# Module-level state (initialised by init_logging / _LazyInit)
# ---------------------------------------------------------------------------

_log_dir: str = ""           # Directory where log files are written
_days_to_keep: int = _DEFAULT_DAYS_TO_KEEP
_log_queue: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX_SIZE)
_writer_thread: Optional[threading.Thread] = None
_stop_event: threading.Event = threading.Event()
_initialized: bool = False
_init_lock: threading.Lock = threading.Lock()

# Console handler for warnings and above (always active, even before init).
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setLevel(logging.WARNING)
_console_fmt = logging.Formatter(
    fmt="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_console_handler.setFormatter(_console_fmt)
_console_logger = logging.getLogger("ErgoProtect.console")
_console_logger.addHandler(_console_handler)
_console_logger.setLevel(logging.WARNING)
_console_logger.propagate = False


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _default_log_dir() -> str:
    """
    Return the default directory for log files.

    When running as a frozen executable (PyInstaller), this is the folder
    containing the .exe. When running from source, it is the project root
    (one level above the src/ package).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # Running from source: go up from src/ to project root.
    src_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(src_dir)


def _today_log_path(log_dir: str) -> str:
    """Return the full path for today's CSV log file."""
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    filename = f"{date_str}{_LOG_SUFFIX}"
    return os.path.join(log_dir, filename)


# ---------------------------------------------------------------------------
# Log file writer (background thread)
# ---------------------------------------------------------------------------

def _writer_loop(log_dir: str) -> None:
    """
    Background thread body: drains the log queue and writes CSV rows.

    Design notes:
    - Opens (or creates) today's CSV file on every drain cycle so that a
      date change at midnight automatically triggers rotation.
    - Writes the CSV header only when creating a new file.
    - Flushes after every write batch to minimise data loss on crash.
    - If the queue is full and a caller tries to enqueue, the caller's
      log call silently drops the message (queue.put_nowait raises Full).
      This is intentional: we never block application threads for logging.
    """
    current_date: Optional[datetime.date] = None
    csv_file = None
    csv_writer = None

    def _open_today_file():
        nonlocal csv_file, csv_writer, current_date
        if csv_file:
            try:
                csv_file.flush()
                csv_file.close()
            except OSError:
                pass

        today = datetime.date.today()
        path = _today_log_path(log_dir)
        try:
            os.makedirs(log_dir, exist_ok=True)
            is_new = not os.path.exists(path)
            csv_file = open(path, "a", newline="", encoding="utf-8")
            csv_writer = csv.writer(csv_file, quoting=csv.QUOTE_MINIMAL)
            if is_new:
                csv_writer.writerow(_CSV_HEADERS)
                csv_file.flush()
            current_date = today
        except OSError as exc:
            # Non-fatal: silently fall back to console-only logging.
            print(f"[AppLogging] Could not open log file '{path}': {exc}")
            csv_file = None
            csv_writer = None
            current_date = today  # still update so we don't retry every loop

    _open_today_file()

    while not _stop_event.is_set():
        # Rotate file if date has changed.
        if datetime.date.today() != current_date:
            _open_today_file()

        # Drain all available entries from the queue.
        drained = 0
        while True:
            try:
                entry = _log_queue.get_nowait()
                if csv_writer is not None:
                    try:
                        csv_writer.writerow(entry)
                    except OSError:
                        pass
                _log_queue.task_done()
                drained += 1
            except queue.Empty:
                break

        if drained > 0 and csv_file is not None:
            try:
                csv_file.flush()
            except OSError:
                pass

        _stop_event.wait(timeout=_WRITER_POLL_S)

    # Final drain after stop is requested (flush remaining entries).
    while not _log_queue.empty():
        try:
            entry = _log_queue.get_nowait()
            if csv_writer is not None:
                try:
                    csv_writer.writerow(entry)
                except OSError:
                    pass
            _log_queue.task_done()
        except queue.Empty:
            break

    if csv_file is not None:
        try:
            csv_file.flush()
            csv_file.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Initialisation & cleanup
# ---------------------------------------------------------------------------

def init_logging(log_dir: Optional[str] = None, days_to_keep: int = _DEFAULT_DAYS_TO_KEEP) -> None:
    """
    Initialise the logging system.

    Must be called once at application startup (main.py) before any log
    functions are used. Calling it a second time is a no-op.

    Args:
        log_dir:      Directory where log CSV files will be stored.
                      Defaults to the folder containing the .exe / project root.
        days_to_keep: Log files older than this many days are deleted.
                      Must be a positive integer. Default: 30.
    """
    global _log_dir, _days_to_keep, _writer_thread, _initialized

    with _init_lock:
        if _initialized:
            return

        _log_dir = log_dir or _default_log_dir()
        _days_to_keep = max(1, days_to_keep)

        try:
            os.makedirs(_log_dir, exist_ok=True)
        except OSError as exc:
            print(f"[AppLogging] Could not create log directory '{_log_dir}': {exc}")

        _stop_event.clear()
        _writer_thread = threading.Thread(
            target=_writer_loop,
            args=(_log_dir,),
            name="AppLogWriter",
            daemon=True,
        )
        _writer_thread.start()
        _initialized = True

    # Log the startup event after the writer is running.
    log_info(_SELF, "Logging initialised. Log dir: %s | Days to keep: %s", _log_dir, _days_to_keep)


def shutdown_logging() -> None:
    """
    Flush the queue and stop the writer thread.

    Called automatically by the atexit hook; safe to call manually from
    main.py's shutdown sequence to ensure log data is flushed before exit.
    """
    _stop_event.set()
    if _writer_thread and _writer_thread.is_alive():
        _writer_thread.join(timeout=3.0)


def cleanup_old_logs(log_dir: Optional[str] = None, days_to_keep: Optional[int] = None) -> None:
    """
    Delete CSV log files older than `days_to_keep` days.

    Designed to be called once at application startup after init_logging().
    Only files matching the pattern yyyy-mm-dd_appLog.csv are considered;
    other files in the log directory are left untouched.

    Args:
        log_dir:      Directory to scan. Defaults to the configured log dir.
        days_to_keep: Retention threshold. Defaults to the configured value.
    """
    target_dir = log_dir or _log_dir or _default_log_dir()
    retention = days_to_keep if days_to_keep is not None else _days_to_keep
    cutoff = datetime.date.today() - datetime.timedelta(days=retention)

    if not os.path.isdir(target_dir):
        log_warning(_SELF, "Log directory does not exist, skipping cleanup: %s", target_dir)
        return

    deleted = 0
    errors = 0
    for filename in os.listdir(target_dir):
        if not filename.endswith(_LOG_SUFFIX):
            continue
        # Parse the date from the filename prefix (yyyy-mm-dd).
        date_part = filename[: -len(_LOG_SUFFIX)]
        try:
            file_date = datetime.date.fromisoformat(date_part)
        except ValueError:
            continue  # Not a date-named file — skip it.

        if file_date < cutoff:
            full_path = os.path.join(target_dir, filename)
            try:
                os.remove(full_path)
                deleted += 1
                log_debug(_SELF, "Deleted old log file: %s", filename)
            except OSError as exc:
                errors += 1
                log_error(_SELF, "Could not delete log file '%s': %s", filename, exc)

    log_info(
        _SELF,
        "Log cleanup complete. Deleted %d file(s) older than %d days. Errors: %d.",
        deleted, retention, errors,
    )


# ---------------------------------------------------------------------------
# Internal enqueue helper
# ---------------------------------------------------------------------------

def _enqueue(level: str, module: str, message: str) -> None:
    """
    Place a log entry onto the queue for the writer thread to process.

    If the queue is full the entry is silently dropped to avoid blocking
    the calling thread. A warning is printed to stderr in that case.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    entry = (timestamp, module, level, message)
    try:
        _log_queue.put_nowait(entry)
    except queue.Full:
        # Queue overflow: print directly to stderr, never block caller.
        print(
            f"[AppLogging] WARNING: Log queue full — entry dropped: [{level}] [{module}] {message}",
            file=sys.stderr,
        )

    # Mirror WARNING+ to the console handler regardless of queue state.
    if level in ("WARNING", "ERROR", "CRITICAL"):
        print(f"{timestamp}  {level:<8}  [{module}] {message}", file=sys.stdout)


def _format_message(message: str, args: tuple) -> str:
    """Interpolate %-style format args into the message string."""
    if args:
        try:
            return message % args
        except (TypeError, ValueError):
            return f"{message} {args}"
    return message


def _format_exc() -> str:
    """Return the current exception traceback as a single-line string."""
    tb = traceback.format_exc()
    if tb and tb.strip() != "NoneType: None":
        # Collapse newlines so the CSV cell stays on one row.
        return " | " + tb.replace("\n", " ").replace("\r", "").strip()
    return ""


# ---------------------------------------------------------------------------
# Public logging API
# ---------------------------------------------------------------------------

def log_debug(module: str, message: str, *args, exc_info: bool = False) -> None:
    """
    Log a DEBUG-level message.

    Use for granular tracing useful during development (poll ticks, state
    changes, raw key events). Too verbose for production by default.

    Args:
        module:   Short identifier for the calling module, e.g. "KeyboardActions".
        message:  Log message, optionally with %-style format placeholders.
        *args:    Positional arguments interpolated into `message`.
        exc_info: If True, append the current exception traceback.
    """
    _lazy_init()
    msg = _format_message(message, args)
    if exc_info:
        msg += _format_exc()
    _enqueue("DEBUG", module, msg)


def log_info(module: str, message: str, *args, exc_info: bool = False) -> None:
    """
    Log an INFO-level message.

    Use for significant lifecycle events: service started/stopped,
    configuration loaded, user-changed settings, drag-drop initiated.

    Args:
        module:   Short identifier for the calling module.
        message:  Log message, optionally with %-style format placeholders.
        *args:    Positional arguments interpolated into `message`.
        exc_info: If True, append the current exception traceback.
    """
    _lazy_init()
    msg = _format_message(message, args)
    if exc_info:
        msg += _format_exc()
    _enqueue("INFO", module, msg)


def log_warning(module: str, message: str, *args, exc_info: bool = False) -> None:
    """
    Log a WARNING-level message.

    Use for recoverable anomalies: an unknown hotkey was ignored, a config
    value was out of range and was clamped, a dependency is missing.

    Args:
        module:   Short identifier for the calling module.
        message:  Log message, optionally with %-style format placeholders.
        *args:    Positional arguments interpolated into `message`.
        exc_info: If True, append the current exception traceback.
    """
    _lazy_init()
    msg = _format_message(message, args)
    if exc_info:
        msg += _format_exc()
    _enqueue("WARNING", module, msg)


def log_error(module: str, message: str, *args, exc_info: bool = False) -> None:
    """
    Log an ERROR-level message.

    Use for failures that affect functionality but do not crash the app:
    a click injection failed, a thread raised an unexpected exception,
    the config file could not be saved.

    Always pass exc_info=True when calling from an except block.

    Args:
        module:   Short identifier for the calling module.
        message:  Log message, optionally with %-style format placeholders.
        *args:    Positional arguments interpolated into `message`.
        exc_info: If True, append the current exception traceback.
    """
    _lazy_init()
    msg = _format_message(message, args)
    if exc_info:
        msg += _format_exc()
    _enqueue("ERROR", module, msg)


def log_critical(module: str, message: str, *args, exc_info: bool = False) -> None:
    """
    Log a CRITICAL-level message.

    Reserved for unrecoverable failures that cause immediate shutdown or
    data loss: the GUI could not be initialised, a required resource is
    unavailable, an unhandled exception in the main thread.

    Args:
        module:   Short identifier for the calling module.
        message:  Log message, optionally with %-style format placeholders.
        *args:    Positional arguments interpolated into `message`.
        exc_info: If True, append the current exception traceback.
    """
    _lazy_init()
    msg = _format_message(message, args)
    if exc_info:
        msg += _format_exc()
    _enqueue("CRITICAL", module, msg)


# ---------------------------------------------------------------------------
# Lazy initialisation guard
# ---------------------------------------------------------------------------

def _lazy_init() -> None:
    """
    If init_logging() has not been called yet (e.g. during testing or if a
    module logs before main.py runs), initialise with defaults silently.
    """
    if not _initialized:
        init_logging()


# ---------------------------------------------------------------------------
# Accessors (used by GraphicalInterface General tab)
# ---------------------------------------------------------------------------

def get_log_dir() -> str:
    """Return the current log directory path."""
    return _log_dir or _default_log_dir()


def get_days_to_keep() -> int:
    """Return the current log retention period in days."""
    return _days_to_keep


def update_log_dir(new_dir: str) -> None:
    """
    Update the log directory at runtime.

    The writer thread will start writing to the new directory on its next
    poll cycle. Already-open file handles in the old directory will be
    closed gracefully by the writer thread's rotation logic.

    Args:
        new_dir: Absolute path to the new log directory. Must be writable.
    """
    global _log_dir
    if new_dir == _log_dir:
        return
    try:
        os.makedirs(new_dir, exist_ok=True)
    except OSError as exc:
        log_error(_SELF, "Cannot create new log directory '%s': %s", new_dir, exc)
        return
    old = _log_dir
    _log_dir = new_dir
    log_info(_SELF, "Log directory changed from '%s' to '%s'.", old, new_dir)


def update_days_to_keep(days: int) -> None:
    """
    Update the log retention period at runtime.

    Args:
        days: New retention period (must be >= 1).
    """
    global _days_to_keep
    days = max(1, days)
    if days == _days_to_keep:
        return
    old = _days_to_keep
    _days_to_keep = days
    log_info(_SELF, "DaysToKeepLog changed from %d to %d.", old, days)


# ---------------------------------------------------------------------------
# Atexit: ensure queue is flushed on normal Python exit
# ---------------------------------------------------------------------------

import atexit
atexit.register(shutdown_logging)
