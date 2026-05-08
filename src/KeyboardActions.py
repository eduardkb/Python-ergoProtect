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
    from pynput.mouse import Button, Controller as MouseController, Listener as MouseListener
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
# Watchdog configuration
# ---------------------------------------------------------------------------
# How often (seconds) the watchdog checks whether the keyboard hook is alive.
_WATCHDOG_INTERVAL_S: float = 8.0
# Maximum seconds of silence before the hook is considered stale (when no
# keypresses have been seen and the listener thread appears unhealthy).
_HOOK_STALE_THRESHOLD_S: float = 20.0

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
        service.start()    # register hotkeys, start watchdog, begin listening
        service.stop()     # unregister hotkeys, stop watchdog, exit cleanly

    Watchdog
    --------
    The ``keyboard`` library sets up a low-level OS hook on its own internal
    thread. That internal thread can silently die (e.g. after a UAC prompt,
    fast-user-switch, screen-lock, or certain system events) without raising
    any exception — causing all hotkeys to stop working with no visible error.

    To detect and recover from this, a separate watchdog daemon thread runs
    alongside the service loop. It periodically calls
    ``_is_keyboard_hook_alive()`` and, if the hook is found to be dead,
    performs a clean unhook + re-register cycle without requiring any user
    action. The watchdog checks every ``_WATCHDOG_INTERVAL_S`` seconds.

    Hook liveness is tested by inspecting the ``keyboard`` library's internal
    ``_listener`` object. If that object is absent, not started, or its
    underlying OS thread is no longer alive, the hook is considered dead.
    As a belt-and-suspenders measure a heartbeat timestamp is also maintained:
    a lightweight ``on_press`` hook updates it on every keypress. If no
    keypress has been seen for longer than ``_HOOK_STALE_THRESHOLD_S`` *and*
    the listener appears dead, a restart is triggered.
    """

    def __init__(self, config_manager) -> None:
        self._cfg = config_manager
        self._mouse = MouseController() if _DEPS_AVAILABLE else None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._hotkeys_registered = False
        self._drag_lock = threading.Lock()
        # Heartbeat: updated by the _heartbeat_hook on every keypress.
        self._last_heartbeat: float = time.monotonic()
        self._hooks_lock = threading.Lock()  # serialises register/unregister

        # Individual handler references returned by add_hotkey() / on_press().
        # Stored so we can remove each one selectively with remove_hotkey() /
        # unhook(), instead of calling unhook_all() which would also remove the
        # AutoClick module's F6 hotkey as an unintended side effect.
        self._hotkey_handlers: list = []
        self._heartbeat_hook_ref = None

        # pynput mouse listener that intercepts any mouse press during an active
        # drag-drop to release the held button and restore hook state cleanly.
        self._drag_mouse_listener: MouseListener | None = None

        # keyboard on_press hook that stops an active drag when any non-drag key
        # is pressed (e.g. F7/F8/F9 or any other key). Stored so it can be
        # removed selectively without touching other modules' hooks.
        self._drag_stop_key_hook_ref = None

        log_info(_MOD, "Service instance created.")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the service thread, watchdog thread, and register all hotkeys.

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
        self._last_heartbeat = time.monotonic()

        self._thread = threading.Thread(
            target=self._service_loop,
            name="KeyboardActionsMonitor",
            daemon=True,
        )
        self._thread.start()

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="KeyboardActionsWatchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

        log_info(_MOD, "Service thread and watchdog started.")

    def stop(self) -> None:
        """
        Signal the service to stop, release any active drag, unregister hotkeys.
        Waits briefly for both threads to exit cleanly.
        """
        log_info(_MOD, "stop() requested.")
        self._stop_event.set()
        self._release_drag_if_active("application stop")
        self._stop_drag_mouse_listener()

        if self._thread:
            self._thread.join(timeout=2.0)
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=3.0)
        self._unregister_hotkeys()
        log_info(_MOD, "Service stopped.")

    def reload_hotkeys(self) -> None:
        """
        Unregister all current hotkeys and re-register them from config.
        Called by the GUI when the user changes a key assignment.
        """
        log_info(_MOD, "Reloading hotkeys from config.")
        with self._hooks_lock:
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
            with self._hooks_lock:
                self._register_hotkeys()
            # Block until stop() sets the event.
            self._stop_event.wait()
        except Exception:
            log_error(_MOD, "Unhandled exception in service loop — recovering.", exc_info=True)
            self._release_drag_if_active("service loop exception")
            # Clear stop_event so a subsequent start() is not immediately cancelled.
            self._stop_event.clear()
        finally:
            with self._hooks_lock:
                self._unregister_hotkeys()

    # ------------------------------------------------------------------
    # Internal: watchdog loop
    # ------------------------------------------------------------------

    def _watchdog_loop(self) -> None:
        """
        Watchdog thread body: periodically checks if the keyboard hook is still
        alive and performs a clean restart of the hooks if it is not.

        This is the primary fix for the silent-freeze bug: the ``keyboard``
        library's internal OS hook thread can die without raising any exception,
        causing all hotkeys to stop working silently.  The watchdog detects
        this condition and re-registers the hooks automatically.
        """
        log_debug(_MOD, "Watchdog thread started (interval=%.0fs, stale=%.0fs).",
                  _WATCHDOG_INTERVAL_S, _HOOK_STALE_THRESHOLD_S)

        while not self._stop_event.wait(timeout=_WATCHDOG_INTERVAL_S):
            if self._stop_event.is_set():
                break
            try:
                if not self._hotkeys_registered:
                    # Hooks were intentionally unregistered; nothing to watch.
                    continue

                hook_alive = self._is_keyboard_hook_alive()
                heartbeat_age = time.monotonic() - self._last_heartbeat

                # Also check that our registered handler count matches what we expect
                # (4 action hotkeys + 1 heartbeat). If handlers were silently lost,
                # re-register even if the listener appears alive.
                expected_action_handlers = 4
                handlers_lost = (
                    len(self._hotkey_handlers) < expected_action_handlers
                    or self._heartbeat_hook_ref is None
                )

                # Trigger recovery when:
                #   1. The internal OS listener thread is dead, OR
                #   2. Handlers have been silently lost.
                # NOTE: heartbeat_age alone is NOT a restart trigger — the user may
                # simply be idle (not pressing keys) which is normal behaviour and
                # must never cause a spurious hook restart.
                restart_reason = None
                if not hook_alive:
                    restart_reason = (
                        f"OS keyboard listener thread is dead "
                        f"(heartbeat_age={heartbeat_age:.1f}s, "
                        f"handlers_registered={len(self._hotkey_handlers)})"
                    )
                elif handlers_lost:
                    restart_reason = (
                        f"Hotkey handler count mismatch: expected {expected_action_handlers} "
                        f"action handlers + heartbeat, found {len(self._hotkey_handlers)} "
                        f"action handlers, heartbeat_ref={'set' if self._heartbeat_hook_ref else 'MISSING'}"
                    )

                if restart_reason:
                    log_warning(
                        _MOD,
                        "Keyboard hooks restarted by watchdog — %s.",
                        restart_reason,
                    )
                    self._restart_hooks()
            except Exception:
                log_error(_MOD, "Watchdog loop encountered an unexpected error.", exc_info=True)

        log_debug(_MOD, "Watchdog thread exiting.")

    def _is_keyboard_hook_alive(self) -> bool:
        """
        Return True if the ``keyboard`` library's internal listener thread
        appears to be running, False otherwise.

        Inspects ``keyboard._listener`` (a private attribute). If the attribute
        does not exist the library version does not expose it; in that case we
        fall back to True (optimistic) to avoid spurious restarts.
        """
        if not _DEPS_AVAILABLE:
            return False
        try:
            listener = getattr(kb_lib, "_listener", None)
            if listener is None:
                # Attribute absent → can't determine; assume OK.
                return True
            # The listener has a ``listening`` boolean and/or a ``_thread``
            # attribute depending on the keyboard library version.
            listening = getattr(listener, "listening", None)
            if listening is False:
                return False
            internal_thread = getattr(listener, "_thread", None)
            if internal_thread is not None and not internal_thread.is_alive():
                return False
            return True
        except Exception:
            # Any introspection error → assume alive to avoid restart storms.
            return True

    def _restart_hooks(self) -> None:
        """
        Safely unregister and re-register all hotkeys.
        Called by the watchdog to recover from a dead hook (e.g. after hibernation,
        screen lock, UAC prompt, or post-drag binding corruption).

        Re-creates the MouseController to recover from any pynput state that
        became invalid while the OS was suspended during hibernation.
        Also releases any active drag to prevent a stuck mouse button.
        """
        try:
            # Release any active drag first — the hook restart will press/release
            # nothing, so if a drag is active it must be cleaned up explicitly.
            self._release_drag_if_active("watchdog hook restart")
            # Stop drag-stop listeners before re-registering to avoid stale refs.
            self._stop_drag_stop_listeners()

            with self._hooks_lock:
                self._unregister_hotkeys()
                self._last_heartbeat = time.monotonic()  # reset before re-hook
                # Re-create mouse controller: pynput state can become invalid
                # after the OS resumes from hibernation or a fast-user-switch.
                try:
                    if _DEPS_AVAILABLE:
                        self._mouse = MouseController()
                except Exception:
                    log_error(_MOD, "Could not re-create MouseController in watchdog restart.", exc_info=True)
                self._register_hotkeys()
            log_info(_MOD, "Keyboard hooks successfully restarted by watchdog.")
        except Exception:
            log_error(_MOD, "Failed to restart keyboard hooks in watchdog.", exc_info=True)

    # ------------------------------------------------------------------
    # Hotkey registration
    # ------------------------------------------------------------------

    def _key_for(self, param: str, default: str) -> str:
        """Read a key name from config, stripping whitespace."""
        return self._cfg.get_config("keyboardActions", param, default).strip()

    def _register_hotkeys(self) -> None:
        """
        Register all four action hotkeys from the current config, plus a
        lightweight heartbeat hook used by the watchdog to verify liveness.

        Each hotkey handler reference is stored in self._hotkey_handlers so
        that _unregister_hotkeys() can remove them individually via
        remove_hotkey(). This avoids calling unhook_all() which would also
        remove the AutoClick module's F6 hotkey as a destructive side effect.

        Must be called with ``self._hooks_lock`` held (enforced by callers).
        """
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
                handler = kb_lib.add_hotkey(key, callback, suppress=True)
                self._hotkey_handlers.append(handler)
                log_info(_MOD, "Hotkey registered: %s → %s()", key, callback.__name__)
            except Exception:
                log_error(_MOD, "Could not register hotkey '%s' for %s.", key, param, exc_info=True)

        # Heartbeat hook: updates _last_heartbeat on every keypress so the
        # watchdog can confirm the keyboard library's internal hook is alive.
        # suppress=False so the event still reaches other hooks and apps.
        try:
            self._heartbeat_hook_ref = kb_lib.on_press(self._heartbeat_hook, suppress=False)
            log_debug(_MOD, "Heartbeat hook registered.")
        except Exception:
            log_error(_MOD, "Could not register heartbeat hook.", exc_info=True)

        self._hotkeys_registered = True

    def _unregister_hotkeys(self) -> None:
        """
        Remove all hotkeys and hooks registered by this module.

        Uses targeted remove_hotkey() / unhook() calls on the stored handler
        references instead of unhook_all(). This is critical: unhook_all()
        would also remove the AutoClick module's F6 hotkey and any other hooks
        registered by other parts of the application, causing them to silently
        stop working.

        Must be called with ``self._hooks_lock`` held (enforced by callers).
        """
        if not _DEPS_AVAILABLE:
            return

        # Remove each action hotkey individually.
        for handler in self._hotkey_handlers:
            try:
                kb_lib.remove_hotkey(handler)
            except Exception:
                pass  # Already removed (e.g. after hibernation hook reset).
        self._hotkey_handlers.clear()

        # Remove the heartbeat on_press hook.
        if self._heartbeat_hook_ref is not None:
            try:
                kb_lib.unhook(self._heartbeat_hook_ref)
            except Exception:
                pass
            self._heartbeat_hook_ref = None

        self._hotkeys_registered = False
        log_info(_MOD, "All hotkeys unregistered.")

    def _heartbeat_hook(self, _event) -> None:
        """
        Called by ``keyboard.on_press`` on every keypress.
        Updates the heartbeat timestamp so the watchdog knows the hook is live.
        """
        self._last_heartbeat = time.monotonic()

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

        First F10 press:  Press and HOLD left mouse button → drag_active = True.
                          Installs a pynput mouse listener and a keyboard on_press
                          hook so that ANY mouse button press or ANY keyboard key
                          press (including F7/F8/F9) immediately releases the drag
                          and restores the hotkeys cleanly.
        Second F10 press: Release left mouse button → drag_active = False.
                          Removes the drag-stop listeners.

        This prevents the bug where pressing a key or mouse button while a drag
        is active would leave the left button held and corrupt the hook state.
        """
        global drag_active, last_drag_end_time

        with self._drag_lock:
            if drag_active:
                # Explicit F10 toggle-off: release the drag and clean up listeners.
                self._end_drag_locked("F10 toggle off")
            else:
                # First press: start the drag.
                try:
                    self._mouse.press(Button.left)
                    drag_active = True
                    log_info(_MOD, "Drag-drop started (F10 toggle on) — holding left button.")
                except Exception:
                    drag_active = False
                    log_error(_MOD, "Failed to press left button for drag-drop.", exc_info=True)
                    return

                # Install listeners AFTER drag_active is True so their callbacks
                # don't race with this assignment.
                self._start_drag_stop_listeners()

    def _end_drag_locked(self, reason: str) -> None:
        """
        Release the held left mouse button and update drag state.

        MUST be called with self._drag_lock already held (or from a context
        where no concurrent drag state mutation is possible).

        After releasing the button the drag-stop listeners are removed (they
        are no longer needed) and hotkeys are immediately re-verified so that
        any binding corruption caused by key presses during the drag is repaired
        before the user notices.
        """
        global drag_active, last_drag_end_time
        drag_active = False
        last_drag_end_time = time.monotonic()
        try:
            if self._mouse:
                self._mouse.release(Button.left)
        except Exception:
            log_error(_MOD, "Failed to release left button during drag end.", exc_info=True)
        log_info(_MOD, "Drag-drop ended. Reason: %s", reason)

        # Remove drag-stop listeners in a separate thread to avoid deadlock:
        # both listeners call back into this code path, so we can't stop them
        # from within their own callbacks without risking a join deadlock.
        t = threading.Thread(
            target=self._stop_drag_stop_listeners_and_reverify,
            name="DragStopCleanup",
            daemon=True,
        )
        t.start()

    def _start_drag_stop_listeners(self) -> None:
        """
        Install a pynput mouse listener and a keyboard on_press hook that each
        call _on_drag_interrupted() when any mouse button or keyboard key is
        pressed during an active drag. These ensure the drag is released cleanly
        regardless of which input device the user uses to stop it.
        """
        if not _DEPS_AVAILABLE:
            return

        # Mouse listener: stops drag on any mouse button press.
        try:
            def _mouse_stop(x, y, button, pressed):
                if pressed and drag_active:
                    log_info(
                        _MOD,
                        "Drag-drop interrupted by mouse button press (%s) — releasing drag.",
                        button,
                    )
                    self._on_drag_interrupted("mouse button press: " + str(button))
                # Returning False stops the pynput listener.
                return not drag_active

            self._drag_mouse_listener = MouseListener(on_click=_mouse_stop)
            self._drag_mouse_listener.daemon = True
            self._drag_mouse_listener.start()
            log_debug(_MOD, "Drag-stop mouse listener started.")
        except Exception:
            log_error(_MOD, "Could not start drag-stop mouse listener.", exc_info=True)

        # Keyboard hook: stops drag on any key press (suppress=False so the
        # key event still reaches other hooks — we only want to detect it, not
        # consume it, and the other hotkeys will handle it normally).
        try:
            def _key_stop(event):
                if drag_active:
                    # Ignore F10 itself — that is handled by _do_drag_drop toggle.
                    drag_key = self._key_for("leftDragDrop", "F10").lower()
                    if event.name and event.name.lower() == drag_key:
                        return
                    log_info(
                        _MOD,
                        "Drag-drop interrupted by key press (%s) — releasing drag.",
                        event.name,
                    )
                    self._on_drag_interrupted("key press: " + str(event.name))

            self._drag_stop_key_hook_ref = kb_lib.on_press(_key_stop, suppress=False)
            log_debug(_MOD, "Drag-stop keyboard hook registered.")
        except Exception:
            log_error(_MOD, "Could not register drag-stop keyboard hook.", exc_info=True)

    def _on_drag_interrupted(self, reason: str) -> None:
        """
        Called by the drag-stop mouse listener or keyboard hook when a button/key
        press is detected while a drag is active.  Releases the drag and schedules
        hotkey re-verification.
        """
        with self._drag_lock:
            if not drag_active:
                return  # Already released (race between mouse and key callbacks).
            self._end_drag_locked(reason)

    def _stop_drag_stop_listeners(self) -> None:
        """Stop and discard the drag-stop mouse listener (safe to call any time)."""
        if self._drag_mouse_listener is not None:
            try:
                self._drag_mouse_listener.stop()
            except Exception:
                pass
            self._drag_mouse_listener = None

        if self._drag_stop_key_hook_ref is not None:
            try:
                kb_lib.unhook(self._drag_stop_key_hook_ref)
            except Exception:
                pass
            self._drag_stop_key_hook_ref = None

    def _stop_drag_stop_listeners_and_reverify(self) -> None:
        """
        Remove drag-stop listeners then immediately verify that all action hotkeys
        are still correctly registered.  Runs in its own daemon thread to avoid
        deadlock when called from inside a listener callback.

        This is the second half of the fix for the hotkey-loss-after-drag bug:
        pressing a key during a drag can disrupt the keyboard library's internal
        hook state, so we proactively re-register after every drag end to ensure
        exclusive bindings are intact.
        """
        # Small delay so pynput/keyboard can finish processing the event that
        # triggered the drag stop before we begin re-registration.
        time.sleep(0.05)
        self._stop_drag_stop_listeners()

        # Re-verify hotkeys: unregister and re-register to ensure the OS-level
        # hook is still correctly bound after the key/button that stopped the drag.
        try:
            with self._hooks_lock:
                if self._hotkeys_registered:
                    registered_count = len(self._hotkey_handlers)
                    expected = 4
                    if registered_count < expected or self._heartbeat_hook_ref is None:
                        log_error(
                            _MOD,
                            "EXCLUSIVE KEY BINDING LOST after drag-drop end — "
                            "only %d of %d action handlers registered, heartbeat=%s. "
                            "Re-registering all hotkeys now.",
                            registered_count, expected,
                            "set" if self._heartbeat_hook_ref else "MISSING",
                        )
                        self._unregister_hotkeys()
                        self._register_hotkeys()
                    else:
                        log_debug(
                            _MOD,
                            "Post-drag hotkey verification OK (%d handlers registered).",
                            registered_count,
                        )
        except Exception:
            log_error(_MOD, "Post-drag hotkey re-verification failed.", exc_info=True)

    def _release_drag_if_active(self, reason: str) -> None:
        """
        Safety helper: release the mouse button if a drag is currently active.
        Called from stop() and exception handlers to ensure the button is never
        left permanently pressed when the application exits or crashes.
        """
        with self._drag_lock:
            if not drag_active:
                return
            self._end_drag_locked(reason)


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
                    # If the service thread or watchdog died (e.g. after an exception),
                    # stop() cleans up residual state before start() spawns fresh threads.
                    service_dead = _service._thread and not _service._thread.is_alive()
                    watchdog_dead = _service._watchdog_thread and not _service._watchdog_thread.is_alive()
                    if service_dead or watchdog_dead:
                        log_warning(_MOD, "Service thread was dead — performing clean restart. Find out why and correct.")
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
