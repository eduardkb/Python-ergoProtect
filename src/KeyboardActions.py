"""
KeyboardActions.py - Keyboard-Triggered Mouse Actions Tab for ErgoProtect
--------------------------------------------------------------------------
This module has two responsibilities:

  1. create_tab()              – builds the Tkinter "Keyboard Actions" settings
                                 panel shown in the GUI notebook.
  2. KeyboardActionsService    – a background thread that listens for configured
                                 hotkeys and translates them into mouse actions,
                                 reducing the need for repetitive mouse button
                                 presses and therefore mitigating RSI / MSD.

Supported actions
-----------------
  leftClick      - Press the configured key → single left-click at cursor.
  rightClick     - Press the configured key → single right-click at cursor.
  doubleClick    - Press the configured key → double left-click at cursor.
  leftDragDrop   - Press the configured key → hold left button until any of:
                     • 15 seconds have elapsed
                     • Any mouse button is pressed
                     • Any keyboard key is pressed
                     • An exception occurs in the service
                     • The application is closed

Threading model
---------------
The service runs in a single daemon thread. The `keyboard` library's
add_hotkey() hooks are registered system-wide from that thread. All mouse
actions are performed via `pynput.mouse.Controller` which is thread-safe for
our use case (single writer). GUI callbacks use tkinter's variable trace
mechanism and stay on the main thread.

Config.ini section: [keyboardActions]
  leftClickKey   = F7
  rightClickKey  = F8
  doubleClickKey = F9
  leftDragDrop   = F10

Healthcare rationale
--------------------
Each key maps to a mouse action that would otherwise require repeated finger
force on a mouse button. By offloading clicks to function keys (pressed with
minimal force), the module reduces cumulative stress on the hand and wrist
joints, directly supporting users at risk of or recovering from tendinitis
and Musculoskeletal Disorders.
"""

import threading
import time
import tkinter as tk
from tkinter import ttk

try:
    from pynput.mouse import Button, Controller as MouseController
    import keyboard as kb_lib
    _DEPS_AVAILABLE = True
except ImportError:
    _DEPS_AVAILABLE = False

from src.AppLogging import log_info, log_warning, log_error, log_debug

# Module identifier used in all log calls.
_MOD = "KeyboardActions"

# Maximum duration (seconds) for a drag-and-drop hold before auto-release.
_DRAG_TIMEOUT_S: float = 15.0

# How often (seconds) the drag-drop loop checks its release conditions.
_DRAG_POLL_S: float = 0.05


# ---------------------------------------------------------------------------
# Background Service
# ---------------------------------------------------------------------------

class KeyboardActionsService:
    """
    Registers global hotkeys and performs the associated mouse actions.

    Lifecycle:
        service = KeyboardActionsService(config_manager)
        service.start()    # register hotkeys and begin listening
        service.stop()     # unregister hotkeys and exit cleanly
    """

    def __init__(self, config_manager) -> None:
        self._cfg = config_manager
        self._mouse = MouseController() if _DEPS_AVAILABLE else None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._hotkeys_registered = False

        # Drag-drop state — guarded by _drag_lock
        self._drag_lock = threading.Lock()
        self._drag_active: bool = False   # True while left button is held for drag

        log_info(_MOD, "Service instance created.")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the service thread and register all configured hotkeys.

        Guard against double-start: if already running this is a no-op.
        """
        if self._thread and self._thread.is_alive():
            log_warning(_MOD, "start() called but service is already running — ignored.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._service_loop,
            name="KeyboardActionsMonitor",
            daemon=True,
        )
        self._thread.start()
        log_info(_MOD, "Service thread started.")

    def stop(self) -> None:
        """
        Signal the service to stop, release any active drag, unregister hotkeys.
        Waits briefly for the thread to exit cleanly.
        """
        log_info(_MOD, "stop() requested.")
        self._stop_event.set()
        self._release_drag_if_active("application stop")

        if self._thread:
            self._thread.join(timeout=2.0)
        self._unregister_hotkeys()
        log_info(_MOD, "Service stopped.")

    def reload_hotkeys(self) -> None:
        """
        Unregister all current hotkeys and re-register them from config.
        Called by the GUI when the user changes a key assignment.
        """
        log_info(_MOD, "Reloading hotkeys from config.")
        self._unregister_hotkeys()
        self._register_hotkeys()

    # ------------------------------------------------------------------
    # Internal: service loop
    # ------------------------------------------------------------------

    def _service_loop(self) -> None:
        """
        Main thread body: registers hotkeys, then blocks until stop is requested.
        All actual work is done in the hotkey callbacks (which run on keyboard
        library's internal thread) — this loop's job is just to keep the
        thread alive and wait for termination.
        """
        try:
            self._register_hotkeys()
            # Block until stop() sets the event.
            self._stop_event.wait()
        except Exception:
            log_error(_MOD, "Unhandled exception in service loop — service stopping.", exc_info=True)
            self._release_drag_if_active("service loop exception")
        finally:
            self._unregister_hotkeys()

    # ------------------------------------------------------------------
    # Hotkey registration
    # ------------------------------------------------------------------

    def _key_for(self, param: str, default: str) -> str:
        """Read a key name from config, stripping whitespace."""
        return self._cfg.get_config("keyboardActions", param, default).strip()

    def _register_hotkeys(self) -> None:
        """Register all four action hotkeys from the current config."""
        if not _DEPS_AVAILABLE:
            log_warning(_MOD, "pynput/keyboard not installed — hotkeys disabled.")
            return
        if self._hotkeys_registered:
            return

        keys = {
            "leftClickKey":   (self._do_left_click,   "F7"),
            "rightClickKey":  (self._do_right_click,  "F8"),
            "doubleClickKey": (self._do_double_click, "F9"),
            "leftDragDrop":   (self._do_drag_drop,    "F10"),
        }

        for param, (callback, default) in keys.items():
            key = self._key_for(param, default)
            try:
                kb_lib.add_hotkey(key, callback, suppress=False)
                log_info(_MOD, "Hotkey registered: %s → %s()", key, callback.__name__)
            except Exception:
                log_error(_MOD, "Could not register hotkey '%s' for %s.", key, param, exc_info=True)

        self._hotkeys_registered = True

    def _unregister_hotkeys(self) -> None:
        """Remove all registered hotkeys."""
        if not _DEPS_AVAILABLE or not self._hotkeys_registered:
            return
        try:
            kb_lib.unhook_all_hotkeys()
            self._hotkeys_registered = False
            log_info(_MOD, "All hotkeys unregistered.")
        except Exception:
            log_error(_MOD, "Error while unregistering hotkeys.", exc_info=True)

    # ------------------------------------------------------------------
    # Mouse action callbacks
    # ------------------------------------------------------------------

    def _do_left_click(self) -> None:
        """Perform a single left-click at the current cursor position."""
        log_debug(_MOD, "Left-click triggered by hotkey.")
        try:
            self._mouse.press(Button.left)
            self._mouse.release(Button.left)
        except Exception:
            log_error(_MOD, "Left-click action failed.", exc_info=True)

    def _do_right_click(self) -> None:
        """Perform a single right-click at the current cursor position."""
        log_debug(_MOD, "Right-click triggered by hotkey.")
        try:
            self._mouse.press(Button.right)
            self._mouse.release(Button.right)
        except Exception:
            log_error(_MOD, "Right-click action failed.", exc_info=True)

    def _do_double_click(self) -> None:
        """Perform a double left-click at the current cursor position."""
        log_debug(_MOD, "Double-click triggered by hotkey.")
        try:
            self._mouse.press(Button.left)
            self._mouse.release(Button.left)
            self._mouse.press(Button.left)
            self._mouse.release(Button.left)
        except Exception:
            log_error(_MOD, "Double-click action failed.", exc_info=True)

    def _do_drag_drop(self) -> None:
        """
        Press and hold the left mouse button for drag-and-drop.

        The hold is released when any of the following occurs:
          • _DRAG_TIMEOUT_S seconds elapse
          • Any mouse button is pressed (detected via pynput listener)
          • Any keyboard key is pressed (detected via keyboard library hook)
          • An exception occurs inside this method
          • stop() is called (application exit / error)

        Only one drag operation runs at a time. If a drag is already active
        when this hotkey fires again, the call is silently ignored to prevent
        double-press accidents.
        """
        with self._drag_lock:
            if self._drag_active:
                log_warning(_MOD, "Drag-drop triggered while already active — ignored.")
                return
            self._drag_active = True

        log_info(_MOD, "Drag-drop started — holding left button.")

        # Events that signal the hold should end.
        release_event = threading.Event()
        release_reason: list[str] = ["unknown"]   # mutable container for thread closure

        # --- Listeners ---------------------------------------------------

        def _on_mouse_click(x, y, button, pressed):
            """Release drag when any mouse button is pressed."""
            if pressed:
                release_reason[0] = f"mouse button pressed ({button})"
                release_event.set()

        def _on_key_press(event):
            """Release drag when any keyboard key is pressed."""
            release_reason[0] = f"keyboard key pressed ({getattr(event, 'name', '?')})"
            release_event.set()

        mouse_listener = None
        key_hook = None

        try:
            from pynput.mouse import Listener as MouseListener

            # Press and hold the left button.
            self._mouse.press(Button.left)

            # Start listeners AFTER the press so the triggering key event
            # itself doesn't immediately fire _on_key_press.
            # A brief sleep lets the keyboard library finish processing the
            # hotkey event before we hook new_key_press globally.
            time.sleep(0.05)

            mouse_listener = MouseListener(on_click=_on_mouse_click)
            mouse_listener.start()

            key_hook = kb_lib.on_press(_on_key_press)

            # Wait for a release condition or timeout.
            elapsed = 0.0
            while not release_event.is_set() and not self._stop_event.is_set():
                time.sleep(_DRAG_POLL_S)
                elapsed += _DRAG_POLL_S
                if elapsed >= _DRAG_TIMEOUT_S:
                    release_reason[0] = f"timeout ({_DRAG_TIMEOUT_S}s elapsed)"
                    break

            if self._stop_event.is_set():
                release_reason[0] = "application stop"

        except Exception:
            release_reason[0] = "exception in drag-drop handler"
            log_error(_MOD, "Exception during drag-drop hold.", exc_info=True)

        finally:
            # Always release the mouse button, even if an exception occurred.
            try:
                self._mouse.release(Button.left)
            except Exception:
                log_error(_MOD, "Failed to release left button after drag-drop.", exc_info=True)

            # Stop listeners.
            if mouse_listener is not None:
                try:
                    mouse_listener.stop()
                except Exception:
                    pass
            if key_hook is not None:
                try:
                    kb_lib.unhook(key_hook)
                except Exception:
                    pass

            with self._drag_lock:
                self._drag_active = False

            log_info(_MOD, "Drag-drop released. Reason: %s", release_reason[0])

    def _release_drag_if_active(self, reason: str) -> None:
        """
        Safety helper: release the mouse button if a drag is currently active.
        Called from stop() and exception handlers to ensure the button is never
        left permanently pressed when the application exits or crashes.
        """
        with self._drag_lock:
            if not self._drag_active:
                return
        try:
            if self._mouse:
                self._mouse.release(Button.left)
            log_info(_MOD, "Drag-drop force-released. Reason: %s", reason)
        except Exception:
            log_error(_MOD, "Could not force-release drag button.", exc_info=True)


# ---------------------------------------------------------------------------
# GUI Tab
# ---------------------------------------------------------------------------

# Module-level service reference (shared with main.py if needed).
_service: KeyboardActionsService | None = None


def get_service() -> KeyboardActionsService | None:
    """Return the module-level service instance (may be None if not started)."""
    return _service


def create_tab(parent: tk.Widget, config_manager) -> tk.Frame:
    """
    Build and return the "Keyboard Actions" settings tab widget.

    Called by GraphicalInterface.py when constructing the notebook tabs.
    Renders all four configurable key fields and wires up the service.

    Args:
        parent:         The ttk.Notebook tab frame to populate.
        config_manager: Shared ConfigManager instance.

    Returns:
        The populated Frame widget.
    """
    global _service

    log_info(_MOD, "create_tab() called — initialising UI and service.")

    # --- Ensure keyboardActions section exists in config -----------------
    _ensure_config_defaults(config_manager)

    # --- Initialise service (if not already running) ---------------------
    if _service is None:
        try:
            _service = KeyboardActionsService(config_manager)
            _service.start()
        except Exception:
            log_error(_MOD, "Failed to start KeyboardActionsService.", exc_info=True)

    # --- Root frame for this tab -----------------------------------------
    frame = ttk.Frame(parent, padding=20)
    frame.pack(fill="both", expand=True)

    # Title
    ttk.Label(
        frame,
        text="Keyboard Actions Settings",
        font=("Segoe UI", 13, "bold"),
    ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 16))

    # Subtitle / description
    ttk.Label(
        frame,
        text=(
            "Assign function keys to mouse actions to reduce repetitive button pressing.\n"
            "Press <Enter> or click away from a field to apply a new key."
        ),
        foreground="#555555",
        font=("Segoe UI", 9),
        wraplength=520,
        justify="left",
    ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 14))

    # Column header labels
    ttk.Label(frame, text="Action", font=("Segoe UI", 9, "bold")).grid(
        row=2, column=0, sticky="w", pady=4, padx=(0, 12)
    )
    ttk.Label(frame, text="Hotkey", font=("Segoe UI", 9, "bold")).grid(
        row=2, column=1, sticky="w", pady=4
    )
    ttk.Label(frame, text="Description", font=("Segoe UI", 9, "bold")).grid(
        row=2, column=2, sticky="w", pady=4, padx=(12, 0)
    )

    ttk.Separator(frame, orient="horizontal").grid(
        row=3, column=0, columnspan=3, sticky="ew", pady=(0, 8)
    )

    # --- Action row definitions ------------------------------------------
    actions = [
        (
            "leftClickKey",
            "F7",
            "Left Click",
            "Press key → single left-click at current cursor position.",
        ),
        (
            "rightClickKey",
            "F8",
            "Right Click",
            "Press key → single right-click at current cursor position.",
        ),
        (
            "doubleClickKey",
            "F9",
            "Double Click",
            "Press key → double left-click at current cursor position.",
        ),
        (
            "leftDragDrop",
            "F10",
            "Drag & Drop",
            (
                "Press key → hold left button for drag-and-drop.\n"
                "Released after 15 s, any key/button press, or app close."
            ),
        ),
    ]

    for idx, (param, default, label, description) in enumerate(actions):
        row = 4 + idx * 2  # two grid rows per action (entry + spacer)

        # Action label
        ttk.Label(frame, text=label, font=("Segoe UI", 10)).grid(
            row=row, column=0, sticky="nw", pady=6, padx=(0, 12)
        )

        # Key entry
        key_var = tk.StringVar(
            value=config_manager.get_config("keyboardActions", param, default)
        )
        entry = ttk.Entry(frame, textvariable=key_var, width=10)
        entry.grid(row=row, column=1, sticky="nw", pady=6)

        # Description note
        ttk.Label(
            frame,
            text=description,
            foreground="#777777",
            font=("Segoe UI", 8),
            wraplength=320,
            justify="left",
        ).grid(row=row, column=2, sticky="nw", pady=6, padx=(12, 0))

        # Bind save + hotkey reload
        def _make_save_callback(p=param, d=default, var=key_var):
            def _save(*_):
                new_key = var.get().strip()
                if not new_key:
                    log_warning(_MOD, "Empty key value for '%s' — ignored.", p)
                    return
                old_key = config_manager.get_config("keyboardActions", p, d)
                if new_key == old_key:
                    return  # no change
                config_manager.set_config("keyboardActions", p, new_key)
                log_info(_MOD, "Key '%s' updated: '%s' → '%s'", p, old_key, new_key)
                if _service:
                    try:
                        _service.reload_hotkeys()
                    except Exception:
                        log_error(_MOD, "Failed to reload hotkeys after key change.", exc_info=True)
            return _save

        save_cb = _make_save_callback()
        entry.bind("<FocusOut>", save_cb)
        entry.bind("<Return>", save_cb)

    # --- Status bar ------------------------------------------------------
    last_row = 4 + len(actions) * 2

    ttk.Separator(frame, orient="horizontal").grid(
        row=last_row, column=0, columnspan=3, sticky="ew", pady=(20, 8)
    )

    if not _DEPS_AVAILABLE:
        status_text = "⚠  pynput / keyboard not installed — Keyboard Actions disabled."
        status_color = "#cc4444"
    else:
        status_text = "Service running. Hotkeys are active system-wide."
        status_color = "#555555"

    ttk.Label(
        frame,
        text=status_text,
        foreground=status_color,
        font=("Segoe UI", 9),
    ).grid(row=last_row + 1, column=0, columnspan=3, sticky="w")

    # Column weights so the description column stretches on resize.
    frame.columnconfigure(2, weight=1)

    log_info(_MOD, "create_tab() completed successfully.")
    return frame


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _ensure_config_defaults(config_manager) -> None:
    """
    Ensure the [keyboardActions] section exists in config.ini with all
    default values. Safe to call multiple times — existing values are never
    overwritten.
    """
    defaults = {
        "leftClickKey":   "F7",
        "rightClickKey":  "F8",
        "doubleClickKey": "F9",
        "leftDragDrop":   "F10",
    }

    section = "keyboardActions"
    # ConfigManager._apply_defaults() style: only write missing keys.
    for key, value in defaults.items():
        existing = config_manager.get_config(section, key)
        if existing is None:
            config_manager.set_config(section, key, value)
            log_debug(_MOD, "Default config written: [%s] %s = %s", section, key, value)

    log_debug(_MOD, "Config defaults verified for section [keyboardActions].")
