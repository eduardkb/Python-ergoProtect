"""
AutoClick.py - AutoClick Tab UI and Background Service for ErgoProtect
-----------------------------------------------------------------------
This module has two responsibilities:

  1. create_tab()       - builds the Tkinter settings panel shown in the GUI.
  2. AutoClickService   - a background thread that monitors the mouse and
                          performs a left-click when the cursor stays still
                          for the configured duration.

Threading model
---------------
The service runs in a daemon thread so Python's interpreter can exit cleanly
even if the thread is still alive. Communication between the GUI thread and
the service thread is done via simple Python Events and shared primitive
values (protected by a Lock where needed).

Mouse-position tracking algorithm
-----------------------------------
Every _POLL_INTERVAL_S seconds the service reads the cursor position.
It computes the Euclidean distance between the new and last-seen position.
If that distance is less than pixels_threshold the cursor is considered
"still"; otherwise the stillness timer resets. When the cursor has been
still for milliseconds_stopped a single left-click is injected.
A _click_fired flag ensures only ONE click fires per stop.

Why left-click only?
  A left-click is the most common interaction and the safest automatic action.
"""

import math
import threading
import time
import tkinter as tk
from tkinter import ttk

# pynput for mouse control/listening; keyboard lib for exclusive per-key hotkey.
try:
    from pynput.mouse import Button, Controller as MouseController, Listener as MouseListener
    import keyboard as kb_lib
    _DEPS_AVAILABLE = True
except ImportError:
    _DEPS_AVAILABLE = False

try:
    from src.AppLogging import log_info, log_warning, log_error, log_debug
except ImportError:
    from AppLogging import log_info, log_warning, log_error, log_debug

_MOD = "AutoClick"

_POLL_INTERVAL_S = 0.02
_POST_DRAG_COOLDOWN_S = 10.0
_MANUAL_DRAG_THRESHOLD_S = 0.5
_POST_ACTIVATION_COOLDOWN_S = 1.0

# ---------------------------------------------------------------------------
# Module-level timing state
# ---------------------------------------------------------------------------
last_mouse_release_time: float = 0.0
_cooldown_cancel_event: threading.Event = threading.Event()


class AutoClickService:
    """
    Background thread that performs a single automatic left-click when the
    mouse cursor stays within pixels_threshold pixels for milliseconds_stopped
    milliseconds. Only one click fires per stop.
    """

    def __init__(self, config_manager) -> None:
        self._cfg = config_manager
        self._active = config_manager.get_bool("autoClick", "active", False)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._mouse = MouseController() if _DEPS_AVAILABLE else None
        self._hotkey_registered = False
        self._hotkey_key: str = ""

        # Timestamp of last activation for post-activation cooldown.
        self._activation_time: float = 0.0

        # Must be True before the first autoclick is allowed after activation.
        # Reset to False on each activation; set to True once cursor moves >5px.
        # Prevents clicking the UI element (checkbox/hotkey) used to enable the feature.
        self._moved_since_activation: bool = False

        self._press_start_time: float = 0.0
        self._mouse_listener: MouseListener | None = None
        self._on_state_change_cb = None

        log_info(_MOD, "Service instance created.")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_state_change_callback(self, cb) -> None:
        """Register callable(bool) invoked when active state changes via hotkey."""
        self._on_state_change_cb = cb

    def start(self) -> None:
        """Start the monitoring thread, drag listener, and exclusive hotkey."""
        if self._thread and self._thread.is_alive():
            return
        self._unregister_hotkey()
        self._stop_mouse_listener()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop, name="AutoClickMonitor", daemon=True
        )
        self._thread.start()
        self._register_hotkey()
        self._start_mouse_listener()
        log_info(_MOD, "AutoClick service started.")

    def stop(self) -> None:
        """Signal the thread to stop and clean up resources."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self._unregister_hotkey()
        self._stop_mouse_listener()
        log_info(_MOD, "AutoClick service stopped.")

    def toggle(self) -> None:
        """
        Toggle active state (called by hotkey). Thread-safe.
        Resets moved_since_activation so the first click after enabling
        always requires a prior mouse move of >5px.
        """
        with self._lock:
            self._active = not self._active
            new_state = self._active
            self._cfg.set_config("autoClick", "active", str(self._active))
            if self._active:
                self._activation_time = time.monotonic()
                self._moved_since_activation = False  # require move before first click

        log_info(_MOD, "AutoClick toggled via hotkey — now %s.", "ON" if new_state else "OFF")

        if new_state and not (self._thread and self._thread.is_alive()):
            log_warning(_MOD, "Monitor thread dead — restarting on toggle-on.")
            self.start()

        if self._on_state_change_cb is not None:
            try:
                self._on_state_change_cb(new_state)
            except Exception:
                log_error(_MOD, "Error in state-change callback.", exc_info=True)

    def set_active(self, active: bool) -> None:
        """
        Explicitly set active state (called by GUI checkbox).
        Resets moved_since_activation so the first click always requires a move.
        """
        with self._lock:
            self._active = active
            if active:
                self._activation_time = time.monotonic()
                self._moved_since_activation = False  # require move before first click

        if active and not (self._thread and self._thread.is_alive()):
            log_warning(_MOD, "Monitor thread not alive — restarting on set_active(True).")
            self.start()

    def is_active(self) -> bool:
        """Return the current active state (thread-safe)."""
        with self._lock:
            return self._active

    # ------------------------------------------------------------------
    # Hotkey management
    # ------------------------------------------------------------------

    def _register_hotkey(self) -> None:
        """
        Register an exclusive per-key hotkey using keyboard.block_key() and
        keyboard.add_hotkey().

        keyboard.block_key() suppresses only the configured key at the OS
        driver level so it never reaches other applications. No other keys
        are affected and no re-injection feedback loop is created.

        NOTE: The previous approach (pynput Listener with suppress=True and
        re-injecting all other keys via a Controller) caused a full keyboard
        lockup because the re-injected events were intercepted again by the
        same suppressing listener, creating an infinite loop.
        """
        if not _DEPS_AVAILABLE or self._hotkey_registered:
            return
        key = self._cfg.get_config("autoClick", "activate_key", "F6")
        try:
            kb_lib.block_key(key)
            kb_lib.add_hotkey(key, self.toggle, suppress=True)
            self._hotkey_registered = True
            self._hotkey_key = key
            log_info(_MOD, "Exclusive hotkey registered (block_key) for key: %s", key)
        except Exception:
            log_error(_MOD, "Could not register hotkey '%s'.", key, exc_info=True)

    def _unregister_hotkey(self) -> None:
        """Remove the blocked key and hotkey callback."""
        if not self._hotkey_registered:
            return
        try:
            kb_lib.unhook_all_hotkeys()
            if self._hotkey_key:
                try:
                    kb_lib.unblock_key(self._hotkey_key)
                except Exception:
                    pass
        except Exception:
            pass
        self._hotkey_registered = False
        log_info(_MOD, "Hotkey unregistered.")

    # ------------------------------------------------------------------
    # Manual drag listener
    # ------------------------------------------------------------------

    def _start_mouse_listener(self) -> None:
        """Start a pynput listener to detect manual mouse drags."""
        if not _DEPS_AVAILABLE:
            return
        try:
            self._mouse_listener = MouseListener(on_click=self._on_mouse_event)
            self._mouse_listener.daemon = True
            self._mouse_listener.start()
            log_debug(_MOD, "Manual drag listener started.")
        except Exception:
            log_error(_MOD, "Could not start mouse listener.", exc_info=True)

    def _stop_mouse_listener(self) -> None:
        """Stop the pynput mouse listener."""
        if self._mouse_listener is not None:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

    def _on_mouse_event(self, x, y, button, pressed) -> None:
        """
        Track left button press/release to detect manual drag/drop.
        Only holds >= _MANUAL_DRAG_THRESHOLD_S trigger the drag cooldown.
        """
        global last_mouse_release_time, _cooldown_cancel_event

        if button == Button.left:
            if pressed:
                self._press_start_time = time.monotonic()
            else:
                if self._press_start_time > 0:
                    hold_duration = time.monotonic() - self._press_start_time
                    if hold_duration >= _MANUAL_DRAG_THRESHOLD_S:
                        last_mouse_release_time = time.monotonic()
                        _cooldown_cancel_event.clear()
                        log_debug(_MOD,
                                  "Manual drag detected (held %.2fs) — "
                                  "autoclick blocked for %ds.",
                                  hold_duration, _POST_DRAG_COOLDOWN_S)
                self._press_start_time = 0.0
        else:
            if pressed:
                elapsed_since_drag = time.monotonic() - last_mouse_release_time
                if elapsed_since_drag < _POST_DRAG_COOLDOWN_S:
                    _cooldown_cancel_event.set()
                    log_debug(_MOD,
                              "Mouse button press cancelled drag cooldown early "
                              "(%.2fs into %.0fs window).",
                              elapsed_since_drag, _POST_DRAG_COOLDOWN_S)

    # ------------------------------------------------------------------
    # Monitoring loop
    # ------------------------------------------------------------------

    def _monitor_loop(self) -> None:
        """
        Main loop: polls mouse position and fires a single click when still.

        AutoClick is blocked when:
          - cursor has NOT moved >5px since AutoClick was enabled
            (first-move requirement prevents clicking the activating UI element)
          - within _POST_ACTIVATION_COOLDOWN_S after activation (secondary guard)
          - a keyboard-triggered drag is active
          - within _POST_DRAG_COOLDOWN_S after a drag ended
          - within _POST_DRAG_COOLDOWN_S after a manual mouse hold released
        """
        if not _DEPS_AVAILABLE:
            log_error(_MOD, "pynput/keyboard not installed — AutoClick disabled.")
            return

        try:
            import KeyboardActions as _ka
        except ImportError:
            try:
                from src import KeyboardActions as _ka
            except ImportError:
                _ka = None

        last_x, last_y = None, None
        still_since: float | None = None
        _click_fired: bool = False
        _FIRST_MOVE_PX = 5  # pixels required to satisfy first-move requirement

        def _is_blocked() -> bool:
            now = time.monotonic()
            # First-move requirement: cursor must travel >5px after activation.
            if not self._moved_since_activation:
                return True
            # Secondary time-based guard.
            if now - self._activation_time < _POST_ACTIVATION_COOLDOWN_S:
                return True
            if _ka is not None:
                if getattr(_ka, "drag_active", False):
                    return True
                ka_drag_end = getattr(_ka, "last_drag_end_time", 0.0)
                if now - ka_drag_end < _POST_DRAG_COOLDOWN_S:
                    return True
            elapsed = now - last_mouse_release_time
            if elapsed < _POST_DRAG_COOLDOWN_S and not _cooldown_cancel_event.is_set():
                return True
            return False

        try:
            while not self._stop_event.is_set():
                if not self.is_active():
                    last_x, last_y = None, None
                    still_since = None
                    _click_fired = False
                    time.sleep(_POLL_INTERVAL_S)
                    continue

                ms_stopped = self._cfg.get_int("autoClick", "milliseconds_stopped", 200)
                px_threshold = self._cfg.get_int("autoClick", "pixels_threshold", 5)
                seconds_stopped = ms_stopped / 1000.0

                pos = self._mouse.position
                if pos is None:
                    log_debug(_MOD, "Mouse position unavailable — skipping tick.")
                    last_x, last_y = None, None
                    still_since = None
                    _click_fired = False
                    time.sleep(_POLL_INTERVAL_S)
                    continue

                cur_x, cur_y = pos

                if last_x is None:
                    last_x, last_y = cur_x, cur_y
                    still_since = time.monotonic()
                    _click_fired = False
                    time.sleep(_POLL_INTERVAL_S)
                    continue

                distance = math.sqrt((cur_x - last_x) ** 2 + (cur_y - last_y) ** 2)

                if distance > px_threshold:
                    last_x, last_y = cur_x, cur_y
                    still_since = time.monotonic()
                    _click_fired = False
                    # Satisfy the first-move requirement once cursor moves >5px.
                    if not self._moved_since_activation and distance > _FIRST_MOVE_PX:
                        self._moved_since_activation = True
                        log_debug(_MOD, "First move detected after activation — autoclick now permitted.")
                else:
                    elapsed = time.monotonic() - still_since
                    if elapsed >= seconds_stopped and not _click_fired:
                        if _is_blocked():
                            log_debug(_MOD, "AutoClick suppressed — awaiting first move, drag, or cooldown.")
                            still_since = time.monotonic()
                        else:
                            self._perform_click()
                            _click_fired = True

                time.sleep(_POLL_INTERVAL_S)

        except Exception:
            log_error(_MOD, "Exception in monitor loop — recovering.", exc_info=True)
            self._recover()

    def _perform_click(self) -> None:
        """Inject a left mouse button click at the current cursor position."""
        try:
            self._mouse.press(Button.left)
            self._mouse.release(Button.left)
            log_debug(_MOD, "AutoClick fired.")
        except Exception:
            log_error(_MOD, "AutoClick click failed.", exc_info=True)

    def _recover(self) -> None:
        """Failsafe: release mouse and reset state after an unexpected exception."""
        try:
            if self._mouse:
                self._mouse.release(Button.left)
        except Exception:
            pass
        self._active = self._cfg.get_bool("autoClick", "active", False)
        self._stop_event.clear()
        log_info(_MOD, "AutoClick recovered from exception — ready for restart.")


# ---------------------------------------------------------------------------
# GUI Tab
# ---------------------------------------------------------------------------

_service: AutoClickService | None = None


def get_service() -> AutoClickService | None:
    """Return the module-level service instance (may be None if not started)."""
    return _service


def create_tab(parent: tk.Widget, config_manager) -> tk.Frame:
    """
    Build and return the AutoClick settings tab widget.

    Called by GraphicalInterface.py. Renders the UI, wires up the service,
    and registers the hotkey->checkbox sync callback.
    """
    global _service

    if _service is None:
        _service = AutoClickService(config_manager)
        _service.start()

    frame = ttk.Frame(parent, padding=20)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="AutoClick Settings", font=("Segoe UI", 13, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 16)
    )

    def _note(row: int, text: str) -> None:
        ttk.Label(frame, text=text, foreground="#888888", font=("Segoe UI", 8)).grid(
            row=row, column=1, sticky="w", padx=(8, 0)
        )

    # ----------------------------------------------------------------
    # Row 1 - Active / Inactive toggle
    # ----------------------------------------------------------------
    active_var = tk.BooleanVar(value=config_manager.get_bool("autoClick", "active"))

    def _on_active_toggle() -> None:
        new_val = active_var.get()
        config_manager.set_config("autoClick", "active", str(new_val))
        if _service:
            _service.set_active(new_val)

    ttk.Label(frame, text="Enable AutoClick:").grid(row=1, column=0, sticky="w", pady=6)
    ttk.Checkbutton(
        frame, variable=active_var, command=_on_active_toggle, text="Active"
    ).grid(row=1, column=1, sticky="w", padx=(8, 0))
    _note(2, "Toggleable at any time via the hotkey below.")

    # ----------------------------------------------------------------
    # Wire hotkey -> GUI checkbox sync
    # ----------------------------------------------------------------
    def _sync_checkbox_from_hotkey(new_state: bool) -> None:
        """Scheduled from any thread when hotkey fires; updates Tk checkbox safely."""
        try:
            if parent.winfo_exists():
                parent.after(0, lambda s=new_state: _apply_state_to_checkbox(s))
        except Exception:
            log_error(_MOD, "Error scheduling checkbox sync.", exc_info=True)

    def _apply_state_to_checkbox(new_state: bool) -> None:
        """Runs on Tk main thread: sync checkbox to service state."""
        try:
            active_var.set(new_state)
            config_manager.set_config("autoClick", "active", str(new_state))
            log_debug(_MOD, "Checkbox synced from hotkey — active=%s.", new_state)
        except Exception:
            log_error(_MOD, "Error applying state to checkbox.", exc_info=True)

    if _service:
        _service.set_state_change_callback(_sync_checkbox_from_hotkey)

    # ----------------------------------------------------------------
    # Row 3 - Activate key
    # ----------------------------------------------------------------
    ttk.Label(frame, text="Hotkey:").grid(row=3, column=0, sticky="w", pady=6)

    key_var = tk.StringVar(value=config_manager.get_config("autoClick", "activate_key", "F6"))
    key_entry = ttk.Entry(frame, textvariable=key_var, width=10)
    key_entry.grid(row=3, column=1, sticky="w", padx=(8, 0))

    def _on_key_change(*_) -> None:
        new_key = key_var.get().strip()
        if not new_key:
            return
        config_manager.set_config("autoClick", "activate_key", new_key)
        if _service:
            _service._unregister_hotkey()
            _service._register_hotkey()
            log_info(_MOD, "Hotkey updated to: %s", new_key)

    key_entry.bind("<FocusOut>", _on_key_change)
    key_entry.bind("<Return>", _on_key_change)
    _note(4, "Press <Enter> or click away to apply the new hotkey.")

    # ----------------------------------------------------------------
    # Row 5 - Milliseconds stopped before autoclick
    # ----------------------------------------------------------------
    ttk.Label(frame, text="Delay before click (ms):").grid(row=5, column=0, sticky="w", pady=6)

    ms_var = tk.IntVar(value=config_manager.get_int("autoClick", "milliseconds_stopped", 200))
    ms_spin = ttk.Spinbox(frame, from_=50, to=2000, increment=50, textvariable=ms_var, width=8)
    ms_spin.grid(row=5, column=1, sticky="w", padx=(8, 0))

    def _on_ms_change(*_) -> None:
        try:
            val = int(ms_var.get())
            val = max(50, min(2000, val))
            config_manager.set_config("autoClick", "milliseconds_stopped", str(val))
        except (ValueError, tk.TclError):
            pass

    ms_spin.bind("<FocusOut>", _on_ms_change)
    ms_spin.bind("<Return>", _on_ms_change)
    ms_var.trace_add("write", _on_ms_change)
    _note(6, "How long the cursor must be still before a click is triggered (50-2000 ms).")

    # ----------------------------------------------------------------
    # Row 7 - Pixels threshold
    # ----------------------------------------------------------------
    ttk.Label(frame, text="Movement threshold (px):").grid(row=7, column=0, sticky="w", pady=6)

    px_var = tk.IntVar(value=config_manager.get_int("autoClick", "pixels_threshold", 5))
    px_spin = ttk.Spinbox(frame, from_=1, to=50, increment=1, textvariable=px_var, width=8)
    px_spin.grid(row=7, column=1, sticky="w", padx=(8, 0))

    def _on_px_change(*_) -> None:
        try:
            val = int(px_var.get())
            val = max(1, min(50, val))
            config_manager.set_config("autoClick", "pixels_threshold", str(val))
        except (ValueError, tk.TclError):
            pass

    px_spin.bind("<FocusOut>", _on_px_change)
    px_spin.bind("<Return>", _on_px_change)
    px_var.trace_add("write", _on_px_change)
    _note(8, "Cursor movement below this distance (px) counts as 'still' (1-50 px).")

    # ----------------------------------------------------------------
    # Status bar
    # ----------------------------------------------------------------
    ttk.Separator(frame, orient="horizontal").grid(
        row=9, column=0, columnspan=2, sticky="ew", pady=(20, 8)
    )
    status_var = tk.StringVar(
        value="Service running." if _DEPS_AVAILABLE else
              "pynput/keyboard not installed - AutoClick disabled."
    )
    ttk.Label(frame, textvariable=status_var, foreground="#555555",
              font=("Segoe UI", 9)).grid(row=10, column=0, columnspan=2, sticky="w")

    frame.columnconfigure(1, weight=1)
    return frame
