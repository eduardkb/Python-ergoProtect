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
_POST_DRAG_COOLDOWN_S = 1.0
_MANUAL_DRAG_THRESHOLD_S = 0.5
_POST_ACTIVATION_COOLDOWN_S = 1.0

# Watchdog: how often to check if the monitor thread is alive after hibernation.
_WATCHDOG_INTERVAL_S: float = 10.0

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
        self._watchdog_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._mouse = MouseController() if _DEPS_AVAILABLE else None

        # Each start() registers exactly one hotkey callback stored here so we
        # can remove it selectively via keyboard.remove_hotkey() without calling
        # unhook_all_hotkeys(), which would wipe KeyboardActions hooks too.
        self._hotkey_handler = None
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

        # True while the physical left mouse button is held by the user (or F10 drag).
        # Blocks autoclick in real time instead of relying solely on a fixed post-release cooldown.
        self._left_button_held: bool = False
        # Set to True during _perform_click so the listener ignores our own synthetic press/release.
        self._is_auto_clicking: bool = False
        # Set to True when a drag/selection is released; causes the monitor loop to reset
        # still_since so the user must be still for a full delay period AFTER the release
        # before autoclick fires — preventing immediate deselection of selected text.
        self._drag_just_released: bool = False
        # Cursor position when drag was released; used to enforce 10px movement minimum
        # before autoclick is allowed after a drag/selection release.
        self._drag_release_x: float = 0.0
        self._drag_release_y: float = 0.0
        # Throttle flag: ensures the drag-release stillness log is only written once per drag.
        self._drag_release_logged: bool = False

        log_info(_MOD, "Service instance created.")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_state_change_callback(self, cb) -> None:
        """Register callable(bool) invoked when active state changes via hotkey."""
        self._on_state_change_cb = cb

    def start(self) -> None:
        """Start the monitoring thread, watchdog, drag listener, and exclusive hotkey."""
        if self._thread and self._thread.is_alive():
            return
        # Clean up any previous resources before re-starting.
        self._unregister_hotkey()
        self._stop_mouse_listener()
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._monitor_loop, name="AutoClickMonitor", daemon=True
        )
        self._thread.start()

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name="AutoClickWatchdog", daemon=True
        )
        self._watchdog_thread.start()

        self._register_hotkey()
        self._start_mouse_listener()
        log_info(_MOD, "AutoClick service started.")

    def stop(self) -> None:
        """Signal the thread to stop and clean up resources."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=2.0)
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
        Register an exclusive suppressed hotkey for the activate/deactivate key.

        Uses keyboard.add_hotkey() with suppress=True so the key event is fully
        consumed by ErgoProtect and never forwarded to the currently focused
        application or Windows itself. This makes F6 (default) exclusive to
        ErgoProtect regardless of what other application is in the foreground.

        We do NOT use block_key() because it interacts poorly with the hotkey
        re-registration cycle after hibernation. suppress=True on add_hotkey()
        is the correct and sufficient mechanism for exclusive key capture.

        The handler reference is stored so it can be removed selectively via
        keyboard.remove_hotkey(), avoiding any impact on KeyboardActions hooks.
        """
        if not _DEPS_AVAILABLE or self._hotkey_handler is not None:
            return
        key = self._cfg.get_config("autoClick", "activate_key", "F6")
        try:
            # suppress=True: the keystroke is consumed exclusively by ErgoProtect
            # and is NOT passed to any other window, application, or Windows itself.
            self._hotkey_handler = kb_lib.add_hotkey(key, self.toggle, suppress=True)
            self._hotkey_key = key
            log_info(_MOD, "Exclusive hotkey registered (suppress=True) for key: %s", key)
        except Exception:
            self._hotkey_handler = None
            log_error(_MOD, "Could not register hotkey '%s'.", key, exc_info=True)

    def _unregister_hotkey(self) -> None:
        """
        Remove only this module's hotkey callback, leaving all other hooks intact.

        Uses keyboard.remove_hotkey() with the stored handler reference instead
        of unhook_all_hotkeys(), which would incorrectly remove the hotkeys
        registered by the KeyboardActions module as a side effect.
        """
        if self._hotkey_handler is None:
            return
        try:
            kb_lib.remove_hotkey(self._hotkey_handler)
            log_info(_MOD, "Hotkey '%s' unregistered.", self._hotkey_key)
        except Exception:
            # Handler may already be gone (e.g. after hibernation hook reset).
            log_debug(_MOD, "remove_hotkey() failed (may already be removed): %s", self._hotkey_key)
        finally:
            self._hotkey_handler = None
            self._hotkey_key = ""

    # ------------------------------------------------------------------
    # Watchdog loop — detects dead monitor thread (e.g. after hibernation)
    # ------------------------------------------------------------------

    def _watchdog_loop(self) -> None:
        """
        Periodically checks whether the monitor thread is alive.

        After the PC resumes from hibernation, the keyboard library's internal
        OS hook thread can die silently, and the pynput mouse controller may
        become unusable. This watchdog detects a dead monitor thread and
        performs a clean restart: re-creates the mouse controller (to recover
        from the hibernation-induced pynput failure), and re-registers everything.

        The watchdog only attempts recovery when stop_event is not set (i.e.
        when the service has not been intentionally stopped by the user).
        """
        log_debug(_MOD, "Watchdog thread started (interval=%.0fs).", _WATCHDOG_INTERVAL_S)

        while not self._stop_event.wait(timeout=_WATCHDOG_INTERVAL_S):
            if self._stop_event.is_set():
                break
            try:
                thread_dead = self._thread is None or not self._thread.is_alive()
                if not thread_dead:
                    continue  # monitor thread is healthy

                log_warning(
                    _MOD,
                    "Monitor thread found dead by watchdog (post-hibernation?) — restarting.",
                )
                # Re-create the mouse controller: after hibernation pynput's
                # internal state can be invalid; a fresh instance recovers it.
                try:
                    self._mouse = MouseController()
                except Exception:
                    log_error(_MOD, "Could not re-create MouseController in watchdog.", exc_info=True)

                # Full restart: clean unregister + fresh thread + re-register.
                self._unregister_hotkey()
                self._stop_mouse_listener()
                self._stop_event.clear()

                self._thread = threading.Thread(
                    target=self._monitor_loop, name="AutoClickMonitor", daemon=True
                )
                self._thread.start()

                self._register_hotkey()
                self._start_mouse_listener()
                log_warning(_MOD, "Monitor thread successfully restarted by watchdog after failure (post-hibernation/sleep recovery complete).")

            except Exception:
                log_error(_MOD, "Watchdog encountered an unexpected error.", exc_info=True)

        log_debug(_MOD, "Watchdog thread exiting.")

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

        _left_button_held is set True on any physical left press and cleared on
        release, giving _is_blocked() a real-time signal.  Synthetic clicks fired
        by _perform_click() are ignored via _is_auto_clicking so they do not
        accidentally arm the held-flag or reset the cooldown.

        A short post-release cooldown (_POST_DRAG_COOLDOWN_S, now 1 s) is still
        applied after a drag (hold >= _MANUAL_DRAG_THRESHOLD_S) to let the user
        settle before autoclick resumes — but it no longer applies to quick clicks.
        """
        global last_mouse_release_time, _cooldown_cancel_event

        if button == Button.left:
            if pressed:
                if self._is_auto_clicking:
                    # Ignore synthetic press generated by _perform_click.
                    return
                self._press_start_time = time.monotonic()
                self._left_button_held = True
                log_debug(_MOD, "Left button physically pressed — autoclick blocked.")
            else:
                if self._is_auto_clicking:
                    # Ignore synthetic release generated by _perform_click.
                    return
                self._left_button_held = False
                if self._press_start_time > 0:
                    hold_duration = time.monotonic() - self._press_start_time
                    if hold_duration >= _MANUAL_DRAG_THRESHOLD_S:
                        last_mouse_release_time = time.monotonic()
                        _cooldown_cancel_event.clear()
                        # Capture cursor position at release; monitor loop will enforce
                        # 10px minimum movement before autoclick is allowed.
                        self._drag_release_x = x
                        self._drag_release_y = y
                        # Signal the monitor loop to reset the stillness timer so the user
                        # must be still for a full delay period after releasing a drag/selection
                        # before autoclick fires — prevents immediate deselection of selected text.
                        self._drag_just_released = True
                        self._drag_release_logged = False
                        log_debug(_MOD,
                                  "Manual drag released (held %.2fs) at (%d, %d) — "
                                  "autoclick cooldown %.1fs.",
                                  hold_duration, x, y, _POST_DRAG_COOLDOWN_S)
                    else:
                        log_debug(_MOD,
                                  "Left button released (held %.2fs, below drag threshold) — "
                                  "no cooldown applied.",
                                  hold_duration)
                self._press_start_time = 0.0
        else:
            if pressed:
                elapsed_since_drag = time.monotonic() - last_mouse_release_time
                if elapsed_since_drag < _POST_DRAG_COOLDOWN_S:
                    _cooldown_cancel_event.set()
                    log_debug(_MOD,
                              "Mouse button press cancelled drag cooldown early "
                              "(%.2fs into %.1fs window).",
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
        _last_successful_update: float = 0.0  # timestamp of last position read (for logging only)
        _ka_drag_was_active: bool = False  # tracks previous F10 drag state to detect release

        def _is_blocked() -> bool:
            now = time.monotonic()
            # First-move requirement: cursor must travel >5px after activation.
            if not self._moved_since_activation:
                return True
            # Secondary time-based guard.
            if now - self._activation_time < _POST_ACTIVATION_COOLDOWN_S:
                return True
            # Block in real time while the physical left button is held by the user.
            if self._left_button_held:
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
            # If a drag was just released, enforce 10px minimum movement from release point
            # before autoclick is allowed — prevents accidental clicks during text deselection.
            if hasattr(self, '_drag_just_released') and self._drag_just_released:
                return True
            return False

        try:
            while not self._stop_event.is_set():
                if not self.is_active():
                    last_x, last_y = None, None
                    still_since = None
                    _click_fired = False
                    _last_successful_update = 0.0
                    time.sleep(_POLL_INTERVAL_S)
                    continue

                ms_stopped = self._cfg.get_int("autoClick", "milliseconds_stopped", 200)
                px_threshold = self._cfg.get_int("autoClick", "pixels_threshold", 5)
                seconds_stopped = ms_stopped / 1000.0

                try:
                    pos = self._mouse.position
                except Exception:
                    # pynput mouse controller can fail after hibernation; exit
                    # so the watchdog detects a dead thread and restarts cleanly.
                    log_warning(_MOD, "Mouse position read failed — exiting monitor loop for watchdog restart.")
                    return

                if pos is None:
                    # Position transiently unavailable (e.g. during display switch).
                    # Reset tracking state silently; do not log on every tick.
                    last_x, last_y = None, None
                    still_since = None
                    _click_fired = False
                    time.sleep(_POLL_INTERVAL_S)
                    continue

                cur_x, cur_y = pos
                now = time.monotonic()

                if last_x is None:
                    last_x, last_y = cur_x, cur_y
                    still_since = now
                    _click_fired = False
                    _last_successful_update = now
                    time.sleep(_POLL_INTERVAL_S)
                    continue

                distance = math.sqrt((cur_x - last_x) ** 2 + (cur_y - last_y) ** 2)

                # Always update the successful-update timestamp on every valid position read.
                # This prevents the stale-state watchdog from triggering when the mouse
                # is genuinely still and blocked (e.g. awaiting first-move after activation).
                _last_successful_update = now

                # If a drag or text-selection was just released, reset the stillness timer
                # immediately so the user must hold still for a full delay period from this
                # point — preventing autoclick from firing into an active text selection.
                # Only clear the flag if cursor has moved 10+ pixels from release point.
                if self._drag_just_released:
                    drag_distance = math.sqrt(
                        (cur_x - self._drag_release_x) ** 2 + 
                        (cur_y - self._drag_release_y) ** 2
                    )
                    if drag_distance >= 10.0:
                        self._drag_just_released = False
                        log_debug(_MOD, 
                                  "Drag release flag cleared — cursor moved %.1fpx from release point.",
                                  drag_distance)
                    else:
                        still_since = now
                        _click_fired = False
                        if not self._drag_release_logged:
                            log_debug(_MOD,
                                      "Drag/selection released — stillness timer reset (moved %.1fpx). "
                                      "Waiting for 10px movement to clear drag state.",
                                      drag_distance)
                            self._drag_release_logged = True

                # Detect F10 keyboard drag end: when drag_active transitions True→False,
                # reset the stillness timer for the same reason as a manual drag release.
                if _ka is not None:
                    ka_drag_now = getattr(_ka, "drag_active", False)
                    if _ka_drag_was_active and not ka_drag_now:
                        still_since = now
                        _click_fired = False
                        log_debug(_MOD, "F10 drag ended — stillness timer reset.")
                    _ka_drag_was_active = ka_drag_now

                if distance > px_threshold:
                    last_x, last_y = cur_x, cur_y
                    still_since = now
                    _click_fired = False
                    # Satisfy the first-move requirement once cursor moves enough pixels.
                    if not self._moved_since_activation and distance > _FIRST_MOVE_PX:
                        self._moved_since_activation = True
                        log_debug(_MOD, "First move detected after activation — autoclick now permitted.")
                else:
                    elapsed = time.monotonic() - still_since
                    if elapsed >= seconds_stopped and not _click_fired:
                        if _is_blocked():
                            # log_debug(_MOD, "AutoClick suppressed — awaiting first move, drag, or cooldown.")
                            # Reset still_since so we don't spam this log on every poll tick.
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
            # Guard: prevent the mouse listener from treating our synthetic
            # press/release as a physical user action (which would arm
            # _left_button_held and potentially trigger a post-drag cooldown).
            self._is_auto_clicking = True
            self._mouse.press(Button.left)
            self._mouse.release(Button.left)
            # log_debug(_MOD, "AutoClick fired.")
        except Exception:
            log_error(_MOD, "AutoClick click failed.", exc_info=True)
        finally:
            self._is_auto_clicking = False

    def _recover(self) -> None:
        """Failsafe: release mouse and reset state after an unexpected exception."""
        try:
            if self._mouse:
                self._mouse.release(Button.left)
        except Exception:
            pass
        self._active = self._cfg.get_bool("autoClick", "active", False)
        # Do NOT clear stop_event here — the watchdog will detect the dead
        # thread and perform a full restart including clearing stop_event.
        log_warning(_MOD, "AutoClick recovered from unexpected exception — watchdog will restart thread.")


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
        # When toggled ON, force re-register ALL function keys (F6 via AutoClick,
        # F7–F10 via KeyboardActions) to recover any lost hooks immediately.
        if new_val:
            log_info(_MOD, "AutoClick Active toggled ON — forcing re-registration of all function key hooks.")
            # Re-register F6 (this service's hotkey).
            if _service:
                try:
                    _service._unregister_hotkey()
                    _service._register_hotkey()
                    log_info(_MOD, "AutoClick F6 hotkey re-registered from Active toggle.")
                except Exception:
                    log_error(_MOD, "Failed to re-register AutoClick hotkey on Active toggle.", exc_info=True)
            # Re-register F7–F10 via KeyboardActions service.
            try:
                import KeyboardActions as _ka_mod
            except ImportError:
                try:
                    from src import KeyboardActions as _ka_mod
                except ImportError:
                    _ka_mod = None
            if _ka_mod is not None:
                _ka_svc = _ka_mod.get_service()
                if _ka_svc is not None:
                    try:
                        _ka_svc.force_reregister_all()
                        log_info(_MOD, "KeyboardActions F7–F10 hotkeys re-registered from AutoClick Active toggle.")
                    except Exception:
                        log_error(_MOD, "Failed to re-register KeyboardActions hotkeys from AutoClick toggle.", exc_info=True)

    ttk.Label(frame, text="Enable AutoClick:").grid(row=1, column=0, sticky="w", pady=6)
    ttk.Checkbutton(
        frame, variable=active_var, command=_on_active_toggle, text="Active"
    ).grid(row=1, column=1, sticky="w", padx=(8, 0))
    _note(2, "Toggleable at any time via the hotkey below.")

    # ----------------------------------------------------------------
    # Wire hotkey -> GUI checkbox sync
    # ----------------------------------------------------------------
    def _sync_checkbox_from_hotkey(new_state: bool) -> None:
        """
        Called from the keyboard lib's internal thread when the hotkey fires.
        Marshals the state update safely onto the Tkinter main thread via after().
        The winfo_exists() check is deferred to the Tk thread — calling it from
        a non-Tk thread is a race condition that can crash Tk on some platforms.
        """
        try:
            # after() is thread-safe in Tkinter and posts the callback to the
            # main event loop without touching any Tk widget from this thread.
            parent.after(0, lambda s=new_state: _apply_state_to_checkbox(s))
        except Exception:
            log_error(_MOD, "Error scheduling checkbox sync.", exc_info=True)

    def _apply_state_to_checkbox(new_state: bool) -> None:
        """Runs on Tk main thread: sync checkbox to service state."""
        try:
            if not parent.winfo_exists():
                return
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
