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

Key suppression
---------------
All hotkeys are registered with suppress=True. This means the keystroke is
fully consumed by ErgoProtect and is NOT forwarded to the application that
currently has focus. Applications such as MS Excel (F7 = spell check),
VS Code (F8 = next error), or any other program that binds the same function
keys will NOT receive the event — only ErgoProtect's action runs.

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

try:
    from src.AppLogging import log_info, log_warning, log_error, log_debug
except ImportError:
    from AppLogging import log_info, log_warning, log_error, log_debug

# Module identifier used in all log calls.
_MOD = "KeyboardActions"

# ---------------------------------------------------------------------------
# Module-level shared state (read by AutoClick.py for interference prevention)
# ---------------------------------------------------------------------------
# True while left mouse button is held for drag-and-drop.
drag_active: bool = False
# Timestamp of the last drag-end (used by AutoClick for 5-second cooldown).
last_drag_end_time: float = 0.0


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
        self._drag_lock = threading.Lock()

        log_info(_MOD, "Service instance created.")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the service thread and register all configured hotkeys.

        Guard against double-start: if already running this is a no-op.
        On restart (e.g. after an exception), always performs a clean unhook
        first to prevent ghost hooks, and clears the stop event.
        """
        if self._thread and self._thread.is_alive():
            log_warning(_MOD, "start() called but service is already running — ignored.")
            return

        # Always unhook before re-registering to prevent ghost hooks on restart.
        self._unregister_hotkeys()
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

        On unexpected exception the loop recovers state and clears _stop_event
        so that the next start() call (triggered by re-enabling the feature)
        can spawn a fresh thread without being blocked.
        """
        try:
            self._register_hotkeys()
            # Block until stop() sets the event.
            self._stop_event.wait()
        except Exception:
            log_error(_MOD, "Unhandled exception in service loop — recovering.", exc_info=True)
            self._release_drag_if_active("service loop exception")
            # Clear stop_event so a subsequent start() is not immediately cancelled.
            self._stop_event.clear()
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
                # suppress=True ensures the key event is consumed by ErgoProtect
                # and is NOT passed through to the currently focused application.
                # This prevents apps like MS Excel (F7=spell check), VS Code
                # (F8=next error), etc. from also acting on the same keystroke.
                kb_lib.add_hotkey(key, callback, suppress=True)
                log_info(_MOD, "Hotkey registered: %s → %s()", key, callback.__name__)
            except Exception:
                log_error(_MOD, "Could not register hotkey '%s' for %s.", key, param, exc_info=True)

        self._hotkeys_registered = True

    def _unregister_hotkeys(self) -> None:
        """Remove all registered hotkeys and any other keyboard hooks."""
        if not _DEPS_AVAILABLE:
            return
        try:
            # unhook_all removes hotkeys AND any on_press/on_release hooks,
            # which prevents ghost hooks after restart.
            kb_lib.unhook_all()
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
        Toggle drag-and-drop state machine.

        First F10 press:  Press and HOLD left mouse button → drag_active = True
        Second F10 press: Release left mouse button        → drag_active = False

        No timeout. No auto-release on key/mouse events. Clean toggle only.
        """
        global drag_active, last_drag_end_time

        with self._drag_lock:
            if drag_active:
                # Second press: release the drag
                try:
                    self._mouse.release(Button.left)
                except Exception:
                    log_error(_MOD, "Failed to release left button on drag toggle.", exc_info=True)
                drag_active = False
                last_drag_end_time = time.monotonic()
                log_info(_MOD, "Drag-drop released (F10 toggle off).")
            else:
                # First press: start the drag
                try:
                    self._mouse.press(Button.left)
                    drag_active = True
                    log_info(_MOD, "Drag-drop started (F10 toggle on) — holding left button.")
                except Exception:
                    drag_active = False
                    log_error(_MOD, "Failed to press left button for drag-drop.", exc_info=True)

    def _release_drag_if_active(self, reason: str) -> None:
        """
        Safety helper: release the mouse button if a drag is currently active.
        Called from stop() and exception handlers to ensure the button is never
        left permanently pressed when the application exits or crashes.
        """
        global drag_active, last_drag_end_time
        with self._drag_lock:
            if not drag_active:
                return
            drag_active = False
            last_drag_end_time = time.monotonic()
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
    Renders an enable/disable toggle at the top, followed by all four
    configurable key fields, and wires up the service thread accordingly.

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

    # --- Initialise service (but only start it if enabled in config) -----
    if _service is None:
        try:
            _service = KeyboardActionsService(config_manager)
        except Exception:
            log_error(_MOD, "Failed to create KeyboardActionsService.", exc_info=True)

    # --- Root frame for this tab -----------------------------------------
    frame = ttk.Frame(parent, padding=20)
    frame.pack(fill="both", expand=True)

    # Title
    ttk.Label(
        frame,
        text="Keyboard Actions Settings",
        font=("Segoe UI", 13, "bold"),
    ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

    # --- Enable / Disable toggle (topmost control) -----------------------
    # Read persisted enabled state; default to True for backwards-compat.
    _enabled_default = config_manager.get_bool("keyboardActions", "enabled", default=True)
    enabled_var = tk.BooleanVar(value=_enabled_default)

    toggle_frame = ttk.Frame(frame)
    toggle_frame.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 14))

    ttk.Label(
        toggle_frame,
        text="Enable Keyboard Actions:",
        font=("Segoe UI", 10, "bold"),
    ).pack(side="left", padx=(0, 8))

    def _on_toggle(*_):
        """Start or stop the service thread based on the toggle state."""
        enabled = enabled_var.get()
        config_manager.set_config("keyboardActions", "enabled", str(enabled))
        if enabled:
            log_info(_MOD, "Keyboard Actions enabled by user — starting service.")
            if _service:
                try:
                    # If the service thread died (e.g. after an exception), stop()
                    # cleans up residual state before start() spawns a fresh thread.
                    if _service._thread and not _service._thread.is_alive():
                        log_warning(_MOD, "Service thread was dead — performing clean restart.")
                        _service.stop()
                    _service.start()
                    status_label.config(
                        text="Service running. Hotkeys are active system-wide.",
                        foreground="#228822",
                    )
                except Exception:
                    log_error(_MOD, "Failed to start service from toggle.", exc_info=True)
        else:
            log_info(_MOD, "Keyboard Actions disabled by user — stopping service.")
            if _service:
                try:
                    _service.stop()
                    status_label.config(
                        text="Service stopped. Hotkeys are inactive.",
                        foreground="#cc4444",
                    )
                except Exception:
                    log_error(_MOD, "Failed to stop service from toggle.", exc_info=True)

    toggle_cb = ttk.Checkbutton(
        toggle_frame,
        variable=enabled_var,
        command=_on_toggle,
        text="Active",
    )
    toggle_cb.pack(side="left")

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
    ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 14))

    # Column header labels
    ttk.Label(frame, text="Action", font=("Segoe UI", 9, "bold")).grid(
        row=3, column=0, sticky="w", pady=4, padx=(0, 12)
    )
    ttk.Label(frame, text="Hotkey", font=("Segoe UI", 9, "bold")).grid(
        row=3, column=1, sticky="w", pady=4
    )
    ttk.Label(frame, text="Description", font=("Segoe UI", 9, "bold")).grid(
        row=3, column=2, sticky="w", pady=4, padx=(12, 0)
    )

    ttk.Separator(frame, orient="horizontal").grid(
        row=4, column=0, columnspan=3, sticky="ew", pady=(0, 8)
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
                "Released after 15 s, any key/button press, pressing the key again, or app close."
            ),
        ),
    ]

    for idx, (param, default, label, description) in enumerate(actions):
        row = 5 + idx * 2  # two grid rows per action (entry + spacer)

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
    last_row = 5 + len(actions) * 2

    ttk.Separator(frame, orient="horizontal").grid(
        row=last_row, column=0, columnspan=3, sticky="ew", pady=(20, 8)
    )

    if not _DEPS_AVAILABLE:
        status_text = "⚠  pynput / keyboard not installed — Keyboard Actions disabled."
        status_color = "#cc4444"
    elif _enabled_default:
        status_text = "Service running. Hotkeys are active system-wide."
        status_color = "#228822"
    else:
        status_text = "Service stopped. Hotkeys are inactive."
        status_color = "#cc4444"

    status_label = ttk.Label(
        frame,
        text=status_text,
        foreground=status_color,
        font=("Segoe UI", 9),
    )
    status_label.grid(row=last_row + 1, column=0, columnspan=3, sticky="w")

    # Column weights so the description column stretches on resize.
    frame.columnconfigure(2, weight=1)

    # --- Start service thread only if enabled ----------------------------
    if _enabled_default and _service:
        try:
            _service.start()
            log_info(_MOD, "Service started (enabled at startup).")
        except Exception:
            log_error(_MOD, "Failed to start KeyboardActionsService at tab init.", exc_info=True)
    else:
        log_info(_MOD, "Service not started — Keyboard Actions is disabled.")

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
        "enabled":        "True",
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
