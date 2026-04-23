"""
RestReminder.py - Rest Reminder Module for ErgoProtect
-------------------------------------------------------
Monitors continuous keyboard/mouse usage and prompts the user to take
regular rest breaks, reducing the risk of RSI, tendinitis, and MSD.

Functionality overview
----------------------
- Tracks usage via three timestamps:
    usage_start_timestamp            - when this work session started
    last_activity_timestamp          - last keyboard OR mouse activity
    last_keyboard_activity_timestamp - last keyboard key press
    last_mouse_activity_timestamp    - last physical mouse button press

- Every 2 seconds the monitor thread:
    1. Checks idle time (last_activity -> now). If > reset_of_work_time_minutes,
       resets all timers (user took a break on their own).
    2. Checks session length (usage_start -> last_activity). If >
       continuous_work_minutes AND no postpone timer is active, shows the
       Pause Screen.

- Pause Screen
    - Captures all keyboard and mouse input via pynput global suppressing hooks.
    - Counts down rest_time_seconds.
    - "Dismiss Rest"  -> releases input, resets timers, closes screen.
    - "Postpone Rest" -> releases input, starts a background delay of
      delay_pause_minutes before re-showing; max 3 postpones.
    - Timer elapses  -> releases input, resets timers, closes screen.

Config.ini section: [RestReminder]
    Active                     = true
    continuous_work_minutes    = 50     (range 40-120)
    delay_pause_minutes        = 10     (range 2-15)
    reset_of_work_time_minutes = 5      (range 1-10)
    rest_time_seconds          = 300    (range 60-300)

Thread safety
-------------
All timestamp mutations go through a threading.Lock.  Tkinter widgets are
only created / destroyed on the main Tkinter thread via root.after().
"""

import threading
import time
import tkinter as tk
from tkinter import ttk

try:
    from pynput import keyboard as _pynput_kb
    from pynput import mouse as _pynput_mouse
    _PYNPUT_OK = True
except ImportError:
    _PYNPUT_OK = False

try:
    from src.AppLogging import log_debug, log_info, log_warning, log_error
except ImportError:
    from AppLogging import log_debug, log_info, log_warning, log_error

_MOD = "RestReminder"

# ---------------------------------------------------------------------------
# Config section and defaults
# ---------------------------------------------------------------------------
_SECTION = "RestReminder"

_DEFAULTS = {
    "Active":                    "true",
    "continuous_work_minutes":   "50",
    "delay_pause_minutes":       "10",
    "reset_of_work_time_minutes":"5",
    "rest_time_seconds":         "300",
}

# Clamp ranges for each numeric parameter (inclusive)
_RANGES = {
    "continuous_work_minutes":    (40, 120),
    "delay_pause_minutes":        (2, 15),
    "reset_of_work_time_minutes": (1, 10),
    "rest_time_seconds":          (60, 300),
}

# Maximum number of times the user may postpone a rest before the button
# is disabled and they must wait or dismiss.
_MAX_POSTPONES = 3

# How often the monitor thread wakes to check timers (seconds).
_POLL_INTERVAL = 2.0

# Milliseconds to stagger between writing usage_start and the three
# last_*_activity timestamps (per specification).
_STAGGER_MS = 50


# ---------------------------------------------------------------------------
# Module-level service singleton
# ---------------------------------------------------------------------------
_service: "RestReminderService | None" = None


# ===========================================================================
# RestReminderService
# ===========================================================================

class RestReminderService:
    """
    Background thread that tracks activity timestamps and triggers the
    Pause Screen when the continuous-work threshold is exceeded.
    """

    def __init__(self, config_manager, tk_root: tk.Tk,
                 icon_image=None, icon_path: str | None = None) -> None:
        self._cfg        = config_manager
        self._root       = tk_root
        self._icon_image = icon_image
        self._icon_path  = icon_path

        # Thread safety
        self._lock       = threading.Lock()
        self._stop_event = threading.Event()

        # Activity timestamps (seconds since epoch)
        self._usage_start:          float = 0.0
        self._last_activity:        float = 0.0
        self._last_kb_activity:     float = 0.0
        self._last_mouse_activity:  float = 0.0

        # Postpone state
        self._postpone_count:  int                          = 0
        self._postpone_active: bool                         = False
        self._postpone_timer:  threading.Timer | None       = None

        # Pause screen state
        self._pause_open: bool                              = False
        self._pause_win:  "PauseScreen | None"              = None

        # pynput listeners for activity tracking
        self._kb_listener    = None
        self._mouse_listener = None

        # Daemon thread
        self._thread = threading.Thread(
            target=self._run,
            name="RestReminderThread",
            daemon=True,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the monitor thread and global input listeners."""
        log_info(_MOD, "RestReminderService starting.")
        self._reset_timers()
        if _PYNPUT_OK:
            self._start_listeners()
        self._thread.start()

    def stop(self) -> None:
        """Stop the monitor thread and release all hooks cleanly."""
        log_info(_MOD, "RestReminderService stopping.")
        self._stop_event.set()
        self._stop_listeners()
        if self._postpone_timer:
            self._postpone_timer.cancel()
            self._postpone_timer = None
        # Schedule pause screen closure on the Tk thread if it is open.
        if self._pause_open and self._pause_win is not None:
            try:
                self._root.after(0, self._pause_win.force_close)
            except Exception:
                pass

    def is_running(self) -> bool:
        """Return True if the monitor thread is alive and not stopping."""
        return self._thread.is_alive() and not self._stop_event.is_set()

    def get_timer_snapshot(self) -> dict:
        """
        Return a dict with elapsed seconds for the three activity timers.
        Keys: 'general', 'mouse', 'keyboard'.
        """
        now = time.time()
        with self._lock:
            start       = self._usage_start
            last_act    = self._last_activity
            last_kb     = self._last_kb_activity
            last_mouse  = self._last_mouse_activity
        return {
            "general":  max(0.0, last_act   - start),
            "mouse":    max(0.0, last_mouse  - start),
            "keyboard": max(0.0, last_kb     - start),
        }

    # ------------------------------------------------------------------
    # Timer management
    # ------------------------------------------------------------------

    def _reset_timers(self) -> None:
        """
        Reset all session timers.

        Per specification:
          1. Write current timestamp to usage_start_timestamp.
          2. After _STAGGER_MS milliseconds write current timestamp to the
             three last_*_activity variables.
        """
        now = time.time()
        with self._lock:
            self._usage_start = now
        threading.Timer(_STAGGER_MS / 1000.0, self._stagger_activity_reset).start()
        log_debug(_MOD, "Timers reset. usage_start=%s",
                  time.strftime("%H:%M:%S", time.localtime(now)))

    def _stagger_activity_reset(self) -> None:
        """Second half of _reset_timers: sets the three last_*_activity vars."""
        now = time.time()
        with self._lock:
            self._last_activity       = now
            self._last_kb_activity    = now
            self._last_mouse_activity = now

    # ------------------------------------------------------------------
    # pynput listener management
    # ------------------------------------------------------------------

    def _start_listeners(self) -> None:
        """Register global pynput keyboard and mouse listeners."""
        try:
            self._kb_listener = _pynput_kb.Listener(
                on_press=self._on_key_press,
                daemon=True,
            )
            self._kb_listener.start()
            log_debug(_MOD, "Keyboard activity listener started.")
        except Exception as exc:
            log_error(_MOD, "Failed to start keyboard listener: %s", exc, exc_info=True)

        try:
            self._mouse_listener = _pynput_mouse.Listener(
                on_click=self._on_mouse_click,
                daemon=True,
            )
            self._mouse_listener.start()
            log_debug(_MOD, "Mouse activity listener started.")
        except Exception as exc:
            log_error(_MOD, "Failed to start mouse listener: %s", exc, exc_info=True)

    def _stop_listeners(self) -> None:
        """Stop pynput activity listeners (best-effort)."""
        for lst in (self._kb_listener, self._mouse_listener):
            if lst:
                try:
                    lst.stop()
                except Exception:
                    pass
        self._kb_listener    = None
        self._mouse_listener = None

    # ------------------------------------------------------------------
    # pynput event callbacks (activity tracking only – no suppression)
    # ------------------------------------------------------------------

    def _on_key_press(self, key) -> None:
        """Update last_activity and last_kb_activity on any key press."""
        try:
            now = time.time()
            with self._lock:
                self._last_activity    = now
                self._last_kb_activity = now
        except Exception as exc:
            log_error(_MOD, "_on_key_press error: %s", exc, exc_info=True)

    def _on_mouse_click(self, x, y, button, pressed) -> None:
        """
        Update last_activity and last_mouse_activity on physical mouse button
        presses.

        Keyboard-simulated clicks (F7/F8/F9/F10 and user-configured keys)
        are filtered out by a 20 ms heuristic: if the last keyboard event
        occurred within 20 ms before this mouse event, it is treated as
        synthetic and ignored.
        """
        if not pressed:
            return
        try:
            now = time.time()
            with self._lock:
                last_kb = self._last_kb_activity
                # Synthetic if keyboard event within 20 ms before this click.
                is_synthetic = (now - last_kb) < 0.020
            if not is_synthetic:
                with self._lock:
                    self._last_activity       = now
                    self._last_mouse_activity = now
        except Exception as exc:
            log_error(_MOD, "_on_mouse_click error: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Monitor loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """
        Main monitor loop – runs every _POLL_INTERVAL seconds in its own
        daemon thread (RestReminderThread).
        """
        log_info(_MOD, "RestReminder monitor loop started.")
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=_POLL_INTERVAL)
                if self._stop_event.is_set():
                    break
                self._check_timers()
        except Exception as exc:
            log_error(_MOD, "Monitor loop crashed: %s", exc, exc_info=True)
            # Per specification: on any error stop all hooks to give the user
            # full control again.
            self._stop_listeners()
            if self._postpone_timer:
                self._postpone_timer.cancel()
            log_warning(_MOD,
                        "RestReminder functionality stopped due to an error. "
                        "Full user control restored.")
        log_info(_MOD, "RestReminder monitor loop exited.")

    def _check_timers(self) -> None:
        """
        Evaluate idle and session durations and trigger the pause screen
        when appropriate.  Raises on error so the monitor loop can stop.
        """
        now = time.time()
        cfg = self._read_config()

        with self._lock:
            last_act       = self._last_activity
            usage_start    = self._usage_start
            pause_open     = self._pause_open
            postpone_active = self._postpone_active

        idle_seconds    = now - last_act
        session_seconds = last_act - usage_start

        reset_threshold = cfg["reset_of_work_time_minutes"] * 60.0
        work_threshold  = cfg["continuous_work_minutes"] * 60.0

        # 1. Idle reset: user has been away long enough – start fresh.
        if idle_seconds > reset_threshold and not pause_open:
            log_info(_MOD,
                     "Idle reset triggered (idle=%.0fs >= threshold=%.0fs).",
                     idle_seconds, reset_threshold)
            self._reset_timers()
            return

        # 2. Work limit exceeded: show pause screen.
        if (session_seconds > work_threshold
                and not pause_open
                and not postpone_active):
            log_info(_MOD,
                     "Work limit reached (session=%.0fs >= limit=%.0fs). "
                     "Showing pause screen.",
                     session_seconds, work_threshold)
            self._root.after(0, self._open_pause_screen)

    # ------------------------------------------------------------------
    # Pause screen lifecycle
    # ------------------------------------------------------------------

    def _open_pause_screen(self) -> None:
        """Open the PauseScreen (must be called on the Tkinter main thread)."""
        if self._pause_open:
            log_debug(_MOD, "Pause screen already open; skipping.")
            return
        try:
            cfg = self._read_config()
            with self._lock:
                self._pause_open    = True
                postpone_count_now  = self._postpone_count
            self._pause_win = PauseScreen(
                tk_root       = self._root,
                rest_seconds  = cfg["rest_time_seconds"],
                delay_minutes = cfg["delay_pause_minutes"],
                postpone_count= postpone_count_now,
                on_dismiss    = self._on_dismiss,
                on_postpone   = self._on_postpone,
                on_elapsed    = self._on_elapsed,
                icon_image    = self._icon_image,
                icon_path     = self._icon_path,
            )
            log_info(_MOD, "Pause screen opened.")
        except Exception as exc:
            log_error(_MOD, "Failed to open pause screen: %s", exc, exc_info=True)
            with self._lock:
                self._pause_open = False
            # Re-raise so the monitor loop handles it per specification.
            raise

    def _on_dismiss(self) -> None:
        """Called when the user clicks 'Dismiss Rest'."""
        log_info(_MOD, "Pause screen dismissed by user; resetting timers.")
        with self._lock:
            self._pause_open      = False
            self._pause_win       = None
            self._postpone_count  = 0
            self._postpone_active = False
        self._reset_timers()

    def _on_postpone(self) -> None:
        """Called when the user clicks 'Postpone Rest'."""
        cfg = self._read_config()
        with self._lock:
            self._postpone_count += 1
            count                 = self._postpone_count
            self._pause_open      = False
            self._pause_win       = None
            self._postpone_active = True

        log_info(_MOD, "Rest postponed (%d/%d). Resuming check in %d min.",
                 count, _MAX_POSTPONES, cfg["delay_pause_minutes"])

        delay_s = cfg["delay_pause_minutes"] * 60.0
        self._postpone_timer = threading.Timer(delay_s, self._postpone_elapsed)
        self._postpone_timer.daemon = True
        self._postpone_timer.start()

    def _postpone_elapsed(self) -> None:
        """Called when the postpone countdown finishes."""
        log_info(_MOD, "Postpone timer elapsed; re-showing pause screen.")
        with self._lock:
            self._postpone_active = False
        self._root.after(0, self._open_pause_screen)

    def _on_elapsed(self) -> None:
        """Called when the rest countdown on the PauseScreen reaches zero."""
        log_info(_MOD, "Rest countdown elapsed; resetting timers.")
        with self._lock:
            self._pause_open      = False
            self._pause_win       = None
            self._postpone_count  = 0
            self._postpone_active = False
        self._reset_timers()

    # ------------------------------------------------------------------
    # Config helper
    # ------------------------------------------------------------------

    def _read_config(self) -> dict:
        """Read and clamp numeric [RestReminder] settings from config.ini."""
        def _clamped(key: str, default: int) -> int:
            lo, hi = _RANGES.get(key, (1, 9999))
            return max(lo, min(hi, self._cfg.get_int(_SECTION, key, default)))

        return {
            "continuous_work_minutes":    _clamped("continuous_work_minutes",    50),
            "delay_pause_minutes":        _clamped("delay_pause_minutes",        10),
            "reset_of_work_time_minutes": _clamped("reset_of_work_time_minutes",  5),
            "rest_time_seconds":          _clamped("rest_time_seconds",          300),
        }


# ===========================================================================
# PauseScreen – modal rest-break window (Tk main thread only)
# ===========================================================================

class PauseScreen:
    """
    A fixed-size, always-on-top modal window that captures all keyboard and
    mouse input while the rest countdown is running.

    Must be instantiated from the Tkinter main thread.
    """

    def __init__(
        self,
        tk_root: tk.Tk,
        rest_seconds: int,
        delay_minutes: int,
        postpone_count: int,
        on_dismiss,
        on_postpone,
        on_elapsed,
        icon_image=None,
        icon_path: str | None = None,
    ) -> None:
        self._root          = tk_root
        self._rest_seconds  = rest_seconds
        self._delay_minutes = delay_minutes
        self._postpone_count= postpone_count
        self._on_dismiss    = on_dismiss
        self._on_postpone   = on_postpone
        self._on_elapsed    = on_elapsed
        self._icon_image    = icon_image
        self._icon_path     = icon_path

        self._remaining = rest_seconds
        self._closed    = False

        # pynput suppressing listeners (block all user input)
        self._kb_suppress    = None
        self._mouse_suppress = None

        self._build_window()
        self._install_input_capture()
        # Start countdown after window is drawn
        self._win.after(1000, self._tick)

    # ------------------------------------------------------------------
    # Window construction
    # ------------------------------------------------------------------

    def _build_window(self) -> None:
        """Build and display the pause window, centred on the primary monitor."""
        self._win = tk.Toplevel(self._root)
        self._win.title("Time to Rest – ErgoProtect")

        # Fixed size centred on screen
        width, height = 540, 360
        sw = self._win.winfo_screenwidth()
        sh = self._win.winfo_screenheight()
        x  = (sw - width)  // 2
        y  = (sh - height) // 2
        self._win.geometry(f"{width}x{height}+{x}+{y}")
        self._win.resizable(False, False)

        # Remove ALL title-bar decorations (no minimize / maximize / close).
        self._win.overrideredirect(True)

        # Always on top.
        self._win.attributes("-topmost", True)

        # Apply application icon (best-effort)
        if self._icon_image is not None:
            try:
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(self._icon_image)
                self._win._ergo_icon_ref = photo          # prevent GC
                self._win.wm_iconphoto(False, photo)
            except Exception:
                pass
        elif self._icon_path:
            try:
                import os
                if os.path.exists(self._icon_path):
                    self._win.iconbitmap(self._icon_path)
            except Exception:
                pass

        # Prevent OS close (belt-and-suspenders alongside overrideredirect)
        self._win.protocol("WM_DELETE_WINDOW", lambda: None)

        # Grab all events for this window on the Tk level too
        self._win.grab_set()
        self._win.focus_force()

        # ------------------------------------------------------------------
        # Layout
        # ------------------------------------------------------------------
        BG      = "#1e3a5f"
        FG      = "#ffffff"
        FG_SOFT = "#d0e8ff"
        FG_CD   = "#ffd700"   # countdown colour

        outer = tk.Frame(self._win, bg=BG, padx=32, pady=24)
        outer.pack(fill="both", expand=True)

        # Title
        tk.Label(
            outer,
            text="\U0001f33f  Time to Rest",
            font=("Segoe UI", 18, "bold"),
            bg=BG, fg=FG,
        ).pack(pady=(0, 10))

        # Friendly message
        tk.Label(
            outer,
            text=(
                "You have been working hard!\n"
                "Please step away, gently stretch your hands and wrists,\n"
                "and take a short break before continuing.\n"
                "Looking after your body is the best investment. \U0001f60a"
            ),
            font=("Segoe UI", 11),
            bg=BG, fg=FG_SOFT,
            justify="center",
        ).pack(pady=(0, 16))

        # Countdown display
        self._countdown_var = tk.StringVar()
        self._update_countdown_label()
        tk.Label(
            outer,
            textvariable=self._countdown_var,
            font=("Segoe UI", 28, "bold"),
            bg=BG, fg=FG_CD,
        ).pack(pady=(0, 22))

        # Buttons
        btn_frame = tk.Frame(outer, bg=BG)
        btn_frame.pack(side="bottom", pady=(0, 4))

        tk.Button(
            btn_frame,
            text="Dismiss Rest",
            command=self._btn_dismiss,
            font=("Segoe UI", 10),
            bg="#c0392b", fg=FG,
            relief="flat",
            padx=18, pady=7,
            cursor="hand2",
            activebackground="#96281b",
            activeforeground=FG,
        ).pack(side="left", padx=(0, 18))

        postpone_label = f"Postpone Rest for {self._delay_minutes} min"
        self._postpone_btn = tk.Button(
            btn_frame,
            text=postpone_label,
            command=self._btn_postpone,
            font=("Segoe UI", 10),
            bg="#27ae60", fg=FG,
            relief="flat",
            padx=18, pady=7,
            cursor="hand2",
            activebackground="#1e8449",
            activeforeground=FG,
        )
        self._postpone_btn.pack(side="left")

        # Disable postpone if max postpones already reached
        if self._postpone_count >= _MAX_POSTPONES:
            self._postpone_btn.config(state="disabled", bg="#7f8c8d",
                                      cursor="arrow")

    def _update_countdown_label(self) -> None:
        mins = self._remaining // 60
        secs = self._remaining % 60
        self._countdown_var.set(f"{mins:02d}:{secs:02d}")

    # ------------------------------------------------------------------
    # Countdown tick
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        """Decrement countdown by 1 second; schedule next tick or fire elapsed."""
        if self._closed:
            return
        if self._remaining <= 0:
            self._elapsed_action()
            return
        self._remaining -= 1
        self._update_countdown_label()
        self._win.after(1000, self._tick)

    # ------------------------------------------------------------------
    # Input capture (pynput suppressing listeners)
    # ------------------------------------------------------------------

    def _install_input_capture(self) -> None:
        """
        Install pynput suppressing listeners so no keyboard or mouse input
        reaches any other application while the pause screen is open.
        """
        if not _PYNPUT_OK:
            log_warning(_MOD, "pynput unavailable – input capture inactive.")
            return

        try:
            self._kb_suppress = _pynput_kb.Listener(
                on_press=self._swallow_key,
                suppress=True,
                daemon=True,
            )
            self._kb_suppress.start()
            log_debug(_MOD, "Keyboard suppressing listener started.")
        except Exception as exc:
            log_error(_MOD, "Could not start keyboard suppressor: %s", exc, exc_info=True)

        try:
            self._mouse_suppress = _pynput_mouse.Listener(
                on_click=self._swallow_click,
                suppress=True,
                daemon=True,
            )
            self._mouse_suppress.start()
            log_debug(_MOD, "Mouse suppressing listener started.")
        except Exception as exc:
            log_error(_MOD, "Could not start mouse suppressor: %s", exc, exc_info=True)

    def _swallow_key(self, key) -> None:
        """Consume keyboard events during rest."""
        pass  # suppress=True already blocks propagation

    def _swallow_click(self, x, y, button, pressed) -> None:
        """Consume mouse click events during rest."""
        pass  # suppress=True already blocks propagation

    def _release_input_capture(self) -> None:
        """Stop the suppressing listeners and restore normal user control."""
        for lst in (self._kb_suppress, self._mouse_suppress):
            if lst:
                try:
                    lst.stop()
                except Exception:
                    pass
        self._kb_suppress    = None
        self._mouse_suppress = None
        log_debug(_MOD, "Input capture released; user control restored.")

    # ------------------------------------------------------------------
    # Button and timer callbacks
    # ------------------------------------------------------------------

    def _btn_dismiss(self) -> None:
        """User clicked 'Dismiss Rest'."""
        if self._closed:
            return
        self._closed = True
        self._release_input_capture()
        self._destroy_window()
        self._on_dismiss()

    def _btn_postpone(self) -> None:
        """User clicked 'Postpone Rest'."""
        if self._closed:
            return
        self._closed = True
        self._release_input_capture()
        self._destroy_window()
        self._on_postpone()

    def _elapsed_action(self) -> None:
        """Countdown reached zero naturally."""
        if self._closed:
            return
        self._closed = True
        self._release_input_capture()
        self._destroy_window()
        self._on_elapsed()

    def force_close(self) -> None:
        """
        Forcefully close the screen without firing any service callback.
        Called when the service is stopped externally (app exit / deactivation).
        """
        if self._closed:
            return
        self._closed = True
        self._release_input_capture()
        self._destroy_window()

    def _destroy_window(self) -> None:
        """Release the Tk grab and destroy the Toplevel."""
        try:
            self._win.grab_release()
        except Exception:
            pass
        try:
            self._win.destroy()
        except Exception:
            pass


# ===========================================================================
# GUI tab entry point
# ===========================================================================

def _ensure_config_defaults(config_manager) -> None:
    """
    Add any missing [RestReminder] keys with their defaults to config.ini.
    Uses ConfigManager.set_config() which is thread-safe and non-blocking.
    """
    for key, default in _DEFAULTS.items():
        if config_manager.get_config(_SECTION, key, None) is None:
            config_manager.set_config(_SECTION, key, default)
            log_debug(_MOD, "Config default applied: [%s] %s = %s",
                      _SECTION, key, default)


def _fmt_elapsed(seconds: float) -> str:
    """Format elapsed seconds as HH:MM:SS."""
    s      = int(seconds)
    h, rem = divmod(s, 3600)
    m, s2  = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s2:02d}"


def create_tab(parent: tk.Widget, config_manager,
               tk_root: tk.Tk | None = None,
               icon_image=None,
               icon_path: str | None = None) -> tk.Widget:
    """
    Build the 'Rest Reminder' settings tab and start the background service
    if Active = true.

    GraphicalInterface calls this as  loaded.create_tab(tab_frame, self._cfg).
    The extra keyword arguments (tk_root, icon_image, icon_path) have defaults
    so the standard two-argument call still works; GraphicalInterface is updated
    to pass them when available.

    Returns the outermost widget.
    """
    global _service

    _ensure_config_defaults(config_manager)
    log_info(_MOD, "Building Rest Reminder tab.")

    # Resolve the Tk root for after() and PauseScreen instantiation.
    root = tk_root if tk_root is not None else parent.winfo_toplevel()

    # ------------------------------------------------------------------
    # Service control helpers (closures, safe to call from Tk main thread)
    # ------------------------------------------------------------------
    def _start_service() -> None:
        global _service
        if _service and _service.is_running():
            return
        _service = RestReminderService(
            config_manager=config_manager,
            tk_root=root,
            icon_image=icon_image,
            icon_path=icon_path,
        )
        _service.start()
        log_info(_MOD, "RestReminderService started.")

    def _stop_service() -> None:
        global _service
        if _service:
            _service.stop()
            _service = None
            log_info(_MOD, "RestReminderService stopped.")

    # ------------------------------------------------------------------
    # Config read/write helpers
    # ------------------------------------------------------------------
    def _read_int(key: str, default: int) -> int:
        lo, hi = _RANGES.get(key, (1, 9999))
        return max(lo, min(hi, config_manager.get_int(_SECTION, key, default)))

    def _save_int(key: str, value: int) -> None:
        lo, hi = _RANGES.get(key, (1, 9999))
        clamped = max(lo, min(hi, value))
        config_manager.set_config(_SECTION, key, str(clamped))
        log_info(_MOD, "Config written: [%s] %s = %d", _SECTION, key, clamped)

    # ------------------------------------------------------------------
    # Build tab layout
    # ------------------------------------------------------------------
    frame = ttk.Frame(parent, padding=20)
    frame.pack(fill="both", expand=True)

    # Title
    ttk.Label(
        frame,
        text="Rest Reminder Settings",
        font=("Segoe UI", 13, "bold"),
    ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

    # --- Activate / Deactivate toggle -----------------------------------
    active_val = config_manager.get_bool(_SECTION, "Active", True)
    active_var = tk.BooleanVar(value=active_val)

    def _on_toggle() -> None:
        enabled = active_var.get()
        config_manager.set_config(_SECTION, "Active", str(enabled))
        log_info(_MOD, "RestReminder Active toggled to %s.", enabled)
        if enabled:
            _start_service()
            toggle_btn.config(text="Activated  \u2713")
        else:
            _stop_service()
            toggle_btn.config(text="Activate")

    toggle_btn = ttk.Button(
        frame,
        text="Activated  \u2713" if active_val else "Activate",
        command=_on_toggle,
    )
    toggle_btn.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 14))

    # Separator
    ttk.Separator(frame, orient="horizontal").grid(
        row=2, column=0, columnspan=3, sticky="ew", pady=(0, 14)
    )

    # --- Parameter spinboxes --------------------------------------------
    def _add_spinbox(label_text: str, cfg_key: str, default: int,
                     hint: str, row: int) -> None:
        lo, hi = _RANGES[cfg_key]
        ttk.Label(frame, text=label_text).grid(
            row=row, column=0, sticky="w", pady=4, padx=(0, 12)
        )
        var  = tk.IntVar(value=_read_int(cfg_key, default))
        spin = ttk.Spinbox(frame, from_=lo, to=hi, increment=1,
                           textvariable=var, width=8)
        spin.grid(row=row, column=1, sticky="w", pady=4)

        def _save(*_args) -> None:
            try:
                _save_int(cfg_key, int(var.get()))
            except (ValueError, tk.TclError):
                pass

        spin.bind("<FocusOut>", _save)
        spin.bind("<Return>",   _save)
        var.trace_add("write",  _save)

        ttk.Label(
            frame, text=hint, foreground="#888888", font=("Segoe UI", 8)
        ).grid(row=row + 1, column=1, columnspan=2, sticky="w")

    base = 3

    _add_spinbox(
        "Work Limit (minutes):",
        "continuous_work_minutes", 50,
        f"Show rest reminder after this many consecutive minutes "
        f"({_RANGES['continuous_work_minutes'][0]}\u2013"
        f"{_RANGES['continuous_work_minutes'][1]}).",
        base,
    )
    _add_spinbox(
        "Postpone Duration (min):",
        "delay_pause_minutes", 10,
        f"Delay before re-showing after postpone "
        f"({_RANGES['delay_pause_minutes'][0]}\u2013"
        f"{_RANGES['delay_pause_minutes'][1]}).",
        base + 2,
    )
    _add_spinbox(
        "Idle Reset (minutes):",
        "reset_of_work_time_minutes", 5,
        f"Idle time that automatically resets the session timer "
        f"({_RANGES['reset_of_work_time_minutes'][0]}\u2013"
        f"{_RANGES['reset_of_work_time_minutes'][1]}).",
        base + 4,
    )

    # --- Separator before timers ----------------------------------------
    sep_row = base + 7
    ttk.Separator(frame, orient="horizontal").grid(
        row=sep_row, column=0, columnspan=3, sticky="ew", pady=(12, 10)
    )

    ttk.Label(
        frame,
        text="Session Timers",
        font=("Segoe UI", 10, "bold"),
    ).grid(row=sep_row + 1, column=0, columnspan=3, sticky="w", pady=(0, 6))

    # Timer display rows
    general_var  = tk.StringVar(value="00:00:00")
    mouse_var    = tk.StringVar(value="00:00:00")
    keyboard_var = tk.StringVar(value="00:00:00")

    def _timer_row(label: str, var: tk.StringVar, row: int) -> None:
        ttk.Label(frame, text=label).grid(
            row=row, column=0, sticky="w", pady=2, padx=(0, 12)
        )
        ttk.Label(
            frame,
            textvariable=var,
            font=("Courier New", 11, "bold"),
            foreground="#1a6ea8",
        ).grid(row=row, column=1, sticky="w", pady=2)

    _timer_row("General Interaction:",  general_var,  sep_row + 2)
    _timer_row("Mouse Interaction:",    mouse_var,    sep_row + 3)
    _timer_row("Keyboard Interaction:", keyboard_var, sep_row + 4)

    # Let the entry column expand
    frame.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------
    # Live timer refresh (1 second cadence via after())
    # ------------------------------------------------------------------
    def _refresh_timers() -> None:
        try:
            if _service and _service.is_running():
                snap = _service.get_timer_snapshot()
                general_var.set(_fmt_elapsed(snap["general"]))
                mouse_var.set(_fmt_elapsed(snap["mouse"]))
                keyboard_var.set(_fmt_elapsed(snap["keyboard"]))
            else:
                general_var.set("--:--:--")
                mouse_var.set("--:--:--")
                keyboard_var.set("--:--:--")
        except Exception as exc:
            log_error(_MOD, "_refresh_timers error: %s", exc, exc_info=True)
        finally:
            try:
                frame.after(1000, _refresh_timers)
            except Exception:
                pass   # Widget was destroyed (app shutdown)

    frame.after(1000, _refresh_timers)

    # ------------------------------------------------------------------
    # Auto-start if Active = true
    # ------------------------------------------------------------------
    if active_val:
        try:
            _start_service()
        except Exception as exc:
            log_error(_MOD, "Auto-start of RestReminderService failed: %s",
                      exc, exc_info=True)

    log_info(_MOD, "Rest Reminder tab built successfully.")
    return frame
