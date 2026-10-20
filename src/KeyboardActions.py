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

import importlib
import sys
import threading
import time
import tkinter as tk
import queue
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

try:
    from src.HookDiagnostics import (
        hook_loss_detector, watchdog_monitor, hotkey_logger, log_diagnostic_summary
    )
except ImportError:
    from HookDiagnostics import (
        hook_loss_detector, watchdog_monitor, hotkey_logger, log_diagnostic_summary
    )

# Module identifier used in all log calls.
_MOD = "KeyboardActions"


class _FunctionKeyCoordinator:
    """Serialize all public keyboard-library binding changes on one worker."""

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._run,
            name="FunctionKeyBindingCoordinator",
            daemon=True,
        )
        self._thread.start()

    def run(self, operation):
        if threading.current_thread() is self._thread:
            return operation()

        completed = threading.Event()
        result: dict = {}
        self._queue.put((operation, completed, result))
        completed.wait()
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def _run(self) -> None:
        while True:
            operation, completed, result = self._queue.get()
            try:
                result["value"] = operation()
            except BaseException as error:
                result["error"] = error
            finally:
                completed.set()


_function_key_coordinator: _FunctionKeyCoordinator | None = None
_function_key_coordinator_lock = threading.Lock()
_delivery_status_lock = threading.Lock()
_delivery_observed_keys: set[str] = set()


def run_function_key_operation(operation):
    """Run a binding mutation on the shared keyboard owner thread."""
    global _function_key_coordinator
    if _function_key_coordinator is None:
        with _function_key_coordinator_lock:
            if _function_key_coordinator is None:
                _function_key_coordinator = _FunctionKeyCoordinator()
    return _function_key_coordinator.run(operation)


def _record_function_key_delivery(key: str) -> None:
    normalized_key = key.upper()
    with _delivery_status_lock:
        first_observation = normalized_key not in _delivery_observed_keys
        _delivery_observed_keys.add(normalized_key)
    if first_observation:
        log_info(_MOD, "Function-key callback observed for %s.", normalized_key)


def get_function_key_delivery_status() -> str:
    with _delivery_status_lock:
        observed = sorted(_delivery_observed_keys)
    if not observed:
        return "Bindings registered; delivery unverified until a function key is pressed."
    return "Callback observed for: " + ", ".join(observed) + ". Other bindings remain unverified."

_binding_status = "Bindings not checked."
_binding_status_callback = None
_binding_status_lock = threading.Lock()


def set_function_key_status_callback(callback) -> None:
    global _binding_status_callback
    _binding_status_callback = callback


def _set_binding_status(status: str) -> None:
    global _binding_status
    with _binding_status_lock:
        _binding_status = status
        callback = _binding_status_callback
    if callback is not None:
        try:
            callback(
                status,
                status.startswith("Callback observed for all configured keys"),
                status.startswith("Bindings unavailable"),
            )
        except Exception:
            log_error(_MOD, "Could not notify the binding-status view.", exc_info=True)


def get_function_key_binding_status() -> str:
    with _binding_status_lock:
        return _binding_status


def report_function_key_delivery(key: str) -> None:
    """Mark delivery verified only after the library invokes a real callback."""
    _record_function_key_delivery(key)
    service = _service
    if service is not None:
        service._reset_delivery_backoff(key)
    _set_binding_status(get_function_key_delivery_status())

# ---------------------------------------------------------------------------
# Watchdog configuration
# ---------------------------------------------------------------------------
# How often (seconds) the watchdog checks whether the keyboard hook is alive.
# 2 s ensures recovery within a few seconds of any hook failure.
_WATCHDOG_INTERVAL_S: float = 2.0
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
        self._hooks_lock = threading.RLock()  # serialises register/unregister
        # Suppressed hotkeys execute in keyboard's low-level Windows callback.
        # Queue all action work so that callback only performs put_nowait().
        self._hook_action_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._binding_generation = 0
        self._actions_enabled = False
        self._last_f10_dispatch = 0.0
        self._hook_action_thread = threading.Thread(
            target=self._hook_action_loop,
            name="KeyboardActionsHookWorker",
            daemon=True,
        )
        self._hook_action_thread.start()
        self._delivery_observation_queue: queue.Queue = queue.Queue()
        self._delivery_monitor_thread: threading.Thread | None = None
        self._delivery_recovery_attempts: dict[str, int] = {}
        self._delivery_recovery_after: dict[str, float] = {}

        # Individual handler references returned by add_hotkey() / on_press().
        # Stored so we can remove each one selectively with remove_hotkey() /
        # unhook(), instead of calling unhook_all() which would also remove the
        # AutoClick module's F6 hotkey as an unintended side effect.
        self._hotkey_handlers: list = []
        self._heartbeat_hook_ref = None
        self._check_count = 0  # Watchdog cycle counter for logging

        # pynput mouse listener that intercepts any mouse press during an active
        # drag-drop to release the held button and restore hook state cleanly.
        self._drag_mouse_listener: MouseListener | None = None

        # keyboard on_press hook that stops an active drag when any non-drag key
        # is pressed (e.g. F7/F8/F9 or any other key). Stored so it can be
        # removed selectively without touching other modules' hooks.
        self._drag_stop_key_hook_ref = None

        # Track whether we have already emitted a "mapping lost" warning so we
        # can pair it with exactly one "mapping recovered" warning per event.
        self._mapping_lost: bool = False

        log_info(_MOD, "Service instance created.")

    def _enqueue_hook_action(self, action, generation: int, key: str) -> None:
        """Minimal low-level-hook callback: queue work without logging or I/O."""
        hotkey_logger.hotkey_dispatched(key)
        self._hook_action_queue.put_nowait((action, generation, key))

    def _hook_action_loop(self) -> None:
        """Run mouse actions and their logging away from the Windows hook."""
        while True:
            action, generation, key = self._hook_action_queue.get()
            try:
                # Never run input captured before a disable/reset.  F10 is
                # debounced so keyboard autorepeat cannot create a stale drag.
                if not self._actions_enabled or generation != self._binding_generation:
                    continue
                report_function_key_delivery(key)
                if key == "F10":
                    now = time.monotonic()
                    if now - self._last_f10_dispatch < 0.25:
                        continue
                    self._last_f10_dispatch = now
                action()
            except Exception:
                log_error(_MOD, "Queued keyboard action failed.", exc_info=True)

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
            log_debug(_MOD, "start() called but service is already running — ignored.")
            return

        log_info(_MOD, "=== KeyboardActions.start() BEGIN ===")
        
        # Always unhook before re-registering to prevent ghost hooks on restart.
        log_debug(_MOD, "  Cleaning up any previous hooks...")
        self._unregister_hotkeys()
        self._stop_event.clear()
        self._last_heartbeat = time.monotonic()
        log_debug(_MOD, "  ✓ Cleanup complete, heartbeat reset")

        log_debug(_MOD, "  Starting service loop thread...")
        self._thread = threading.Thread(
            target=self._service_loop,
            name="KeyboardActionsMonitor",
            daemon=True,
        )
        self._thread.start()
        log_debug(_MOD, "  ✓ Service thread started")

        log_debug(_MOD, "  Starting watchdog thread...")
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="KeyboardActionsWatchdog",
            daemon=True,
        )
        self._watchdog_thread.start()
        log_debug(_MOD, "  ✓ Watchdog thread started")

        self._delivery_monitor_thread = threading.Thread(
            target=self._delivery_monitor_loop,
            name="FunctionKeyDeliveryMonitor",
            daemon=True,
        )
        self._delivery_monitor_thread.start()
        log_debug(_MOD, "  ✓ Function-key delivery monitor started")

        log_info(_MOD, "=== KeyboardActions.start() COMPLETE ===")
        log_info(_MOD, "✓ Service thread and registration telemetry started successfully.")

    def stop(self) -> None:
        """
        Signal the service to stop, release any active drag, unregister hotkeys.
        Waits briefly for both threads to exit cleanly.
        """
        log_info(_MOD, ">>> KeyboardActions.stop() requested - shutting down...")
        self._stop_event.set()
        log_debug(_MOD, "  Stop event set")
        
        self._release_drag_if_active("application stop")
        log_debug(_MOD, "  ✓ Drag released if active")
        
        self._stop_drag_stop_listeners()
        log_debug(_MOD, "  ✓ Drag mouse listener stopped")
        
        log_info(_MOD, ">>> KeyboardActions.stop() complete")

        if self._thread:
            self._thread.join(timeout=2.0)
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=3.0)
        if self._delivery_monitor_thread:
            self._delivery_monitor_thread.join(timeout=1.0)
        run_function_key_operation(self._unregister_hotkeys)
        log_info(_MOD, "Service stopped.")

    def reload_hotkeys(self) -> None:
        """
        Unregister all current hotkeys and re-register them from config.
        Called by the GUI when the user changes a key assignment.
        """
        log_info(_MOD, "=== reload_hotkeys() REQUESTED (user changed key assignment) ===")
        try:
            def _reload():
                with self._hooks_lock:
                    self._unregister_hotkeys()
                    self._register_hotkeys()
            run_function_key_operation(_reload)
            log_info(_MOD, "✓ Hotkeys reloaded successfully from config")
        except Exception as e:
            log_error(_MOD, "❌ reload_hotkeys() FAILED: %s", str(e), exc_info=True)

    def _rebuild_keyboard_actions_native(self) -> None:
        """Refresh Keyboard Actions registrations through the shared coordinator."""
        log_info(_MOD, "=== Keyboard Actions binding refresh requested ===")
        try:
            log_debug(_MOD, "  Step 1: Releasing any active drag...")
            self._release_drag_if_active("force re-register")
            log_debug(_MOD, "  ✓ Drag released if active")
            
            log_debug(_MOD, "  Step 2: Stopping drag-stop listeners...")
            self._stop_drag_stop_listeners()
            log_debug(_MOD, "  ✓ Drag-stop listeners stopped")
            
            with self._hooks_lock:
                log_debug(_MOD, "  Step 3: Removing this service's registered handlers...")
                self._unregister_hotkeys()

                log_debug(_MOD, "  Step 4: Resetting registration heartbeat...")
                self._last_heartbeat = time.monotonic()

                log_debug(_MOD, "  Step 6: Recreating MouseController...")
                try:
                    if _DEPS_AVAILABLE:
                        self._mouse = MouseController()
                        log_info(_MOD, "  ✓ MouseController recreated")
                except Exception as e:
                    log_error(_MOD, "  ❌ Could not re-create MouseController: %s", str(e), exc_info=True)
                    raise
                
                log_debug(_MOD, "  Step 7: Re-registering hotkeys...")
                self._register_hotkeys()
                if len(self._hotkey_handlers) != 4 or self._heartbeat_hook_ref is None:
                    raise RuntimeError(
                        "Keyboard package did not register every F7-F10 handler and heartbeat."
                    )
                log_info(_MOD, "  ✓ Hotkeys re-registered")
            
            self._mapping_lost = False
            _set_binding_status("Bindings registered; delivery unverified until a function key is pressed.")
            log_info(_MOD, "Keyboard Actions handlers registered; physical delivery is unverified.")
        except Exception as e:
            _set_binding_status(f"Bindings unavailable; refresh failed: {e}")
            log_error(_MOD, "Keyboard Actions binding refresh failed: %s", str(e), exc_info=True)
            raise

    def force_reregister_all(self) -> None:
        """Rebuild the complete shared F6-F10 hook set transactionally."""
        reset_function_key_bindings(include_keyboard_actions=True, reason="service request")


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
            log_warning(_MOD, "Service loop recovered from exception — service will need to be re-enabled or watchdog will restart hooks.")
        finally:
            self._unregister_hotkeys()

    # ------------------------------------------------------------------
    # Internal: watchdog loop
    # ------------------------------------------------------------------

    def _watchdog_loop(self) -> None:
        """Log registration and heartbeat telemetry without claiming delivery."""
        log_debug(_MOD, "Watchdog thread started (interval=%.0fs).",
                  _WATCHDOG_INTERVAL_S)

        while not self._stop_event.wait(timeout=_WATCHDOG_INTERVAL_S):
            if self._stop_event.is_set():
                break
            try:
                if not self._hotkeys_registered:
                    # Hooks were intentionally unregistered; nothing to watch.
                    continue

                if self._check_count % 10 == 0:
                    log_debug(
                        _MOD,
                        "Watchdog telemetry #%d: registered_handlers=%d, heartbeat=%.1fs ago; "
                        "physical key delivery is verified only by a real key callback.",
                        self._check_count,
                        len(self._hotkey_handlers),
                        time.monotonic() - self._last_heartbeat,
                    )
                self._check_count += 1
            except Exception:
                log_error(_MOD, "Watchdog loop encountered an unexpected error.", exc_info=True)

        log_debug(_MOD, "Watchdog thread exiting.")

    def _delivery_monitor_loop(self) -> None:
        """Recover missed callbacks when keyboard's observer still sees a key event."""
        pending: dict[str, tuple[float, float]] = {}
        while not self._stop_event.is_set():
            try:
                key, observed_at, _dispatch_before = self._delivery_observation_queue.get(timeout=0.1)
                key = key.upper()
                active_keys = {item.upper() for item in hotkey_logger.get_active_hotkeys()}
                if key in {"F6", "F7", "F8", "F9", "F10"} and key in active_keys:
                    pending[key] = (observed_at + 0.25, observed_at)
            except queue.Empty:
                pass

            now = time.monotonic()
            for key, (deadline, observed_at) in tuple(pending.items()):
                if now < deadline:
                    continue
                pending.pop(key, None)
                dispatched_at = hotkey_logger.get_last_dispatch(key)
                if dispatched_at is not None and dispatched_at >= observed_at - 0.15:
                    continue
                retry_at = self._delivery_recovery_after.get(key, 0.0)
                if now < retry_at:
                    continue

                attempts = self._delivery_recovery_attempts.get(key, 0) + 1
                self._delivery_recovery_attempts[key] = attempts
                delay = min(60.0, 2.0 ** min(attempts, 6))
                self._delivery_recovery_after[key] = now + delay
                reason = f"{key} observer event had no registered callback"
                log_warning(
                    _MOD,
                    "Delivery monitor missed %s callback; refreshing bindings (attempt=%d, next retry in %.0fs).",
                    key,
                    attempts,
                    delay,
                )
                try:
                    reset_function_key_bindings(
                        include_keyboard_actions=True,
                        reason=reason,
                    )
                except Exception:
                    log_error(_MOD, "Automatic recovery failed for %s.", key, exc_info=True)

    def _reset_delivery_backoff(self, key: str) -> None:
        normalized = key.upper()
        self._delivery_recovery_attempts.pop(normalized, None)
        self._delivery_recovery_after.pop(normalized, None)

    # ------------------------------------------------------------------
    # Hotkey registration
    # ------------------------------------------------------------------

    def _key_for(self, param: str, default: str) -> str:
        """Read a key name from config, stripping whitespace."""
        return self._cfg.get_config("keyboardActions", param, default).strip()

    def _register_hotkeys(self) -> None:
        def _register_owned():
            with self._hooks_lock:
                return self._register_hotkeys_owned()
        return run_function_key_operation(_register_owned)

    def _register_hotkeys_owned(self) -> None:
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
            log_debug(_MOD, "_register_hotkeys called but already registered (skipping)")
            return

        log_info(_MOD, ">>> REGISTERING ALL HOTKEYS START")
        self._binding_generation += 1
        generation = self._binding_generation
        self._actions_enabled = False
        
        keys = {
            "leftClickKey":   (self._do_left_click,   "F7"),
            "rightClickKey":  (self._do_right_click,  "F8"),
            "doubleClickKey": (self._do_double_click, "F9"),
            "leftDragDrop":   (self._do_drag_drop,    "F10"),
        }

        registered_count = 0
        for param, (callback, default) in keys.items():
            # F7-F10 are fixed safety bindings while ErgoProtect is running.
            key = default
            try:
                # suppress=True ensures the key event is consumed by ErgoProtect
                # and is NOT passed through to the currently focused application.
                # This prevents apps like MS Excel (F7=spell check), VS Code
                # (F8=next error), etc. from also acting on the same keystroke.
                log_debug(_MOD, "  Registering hotkey: %s (param=%s)", key, param)
                # ``callback`` must not run in the low-level Windows hook;
                # logging and mouse I/O are handled by the worker thread.
                handler = kb_lib.add_hotkey(
                    key,
                    lambda action=callback, binding=generation, hotkey=key: self._enqueue_hook_action(
                        action, binding, hotkey.upper()
                    ),
                    suppress=True,
                )
                self._hotkey_handlers.append((key, handler))
                hotkey_logger.hotkey_registered(key, callback.__name__)
                log_info(_MOD, "  ✓ Hotkey registered: %s → %s()", key, callback.__name__)
                registered_count += 1
            except Exception as e:
                log_error(_MOD, "  ❌ FAILED to register hotkey '%s' for %s: %s", key, param, str(e), exc_info=True)

        # Heartbeat hook: updates _last_heartbeat on every keypress so the
        # watchdog can confirm the keyboard library's internal hook is alive.
        # suppress=False so the event still reaches other hooks and apps.
        try:
            log_debug(_MOD, "  Registering heartbeat hook...")
            self._heartbeat_hook_ref = kb_lib.on_press(self._heartbeat_hook, suppress=False)
            log_info(_MOD, "  ✓ Heartbeat hook registered")
        except Exception as e:
            log_error(_MOD, "  ❌ FAILED to register heartbeat hook: %s", str(e), exc_info=True)

        self._hotkeys_registered = registered_count > 0 or self._heartbeat_hook_ref is not None
        self._actions_enabled = registered_count == len(keys)
        if registered_count != len(keys) or self._heartbeat_hook_ref is None:
            _set_binding_status(
                f"Bindings unavailable; registered {registered_count}/4 Keyboard Actions keys."
            )
        else:
            _set_binding_status("Bindings registered; delivery unverified until a function key is pressed.")
        log_info(
            _MOD,
            ">>> REGISTERING ALL HOTKEYS COMPLETE - Registered %d/%d action hotkeys, heartbeat %s",
            registered_count,
            len(keys),
            "OK" if self._heartbeat_hook_ref else "FAILED"
        )
        hook_loss_detector.hook_registered(context="_register_hotkeys()")

    def _unregister_hotkeys(self) -> None:
        def _unregister_owned():
            with self._hooks_lock:
                return self._unregister_hotkeys_owned()
        return run_function_key_operation(_unregister_owned)

    def _unregister_hotkeys_owned(self) -> None:
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

        log_info(_MOD, ">>> UNREGISTERING ALL HOTKEYS START")
        # Invalidate queued callbacks before touching keyboard's registrations.
        self._actions_enabled = False
        self._binding_generation += 1
        
        # Remove each action hotkey individually.
        removed_count = 0
        for i, (key, handler) in enumerate(self._hotkey_handlers):
            try:
                log_debug(_MOD, "  Removing action hotkey #%d...", i + 1)
                kb_lib.remove_hotkey(handler)
                hotkey_logger.hotkey_unregistered(key)
                log_debug(_MOD, "  ✓ Action hotkey #%d removed", i + 1)
                removed_count += 1
            except Exception as e:
                log_error(_MOD, "Action hotkey removal failed for %s at stage unregister: %s", key, str(e), exc_info=True)
                raise RuntimeError(f"Could not unregister {key} during binding refresh") from e
        
        self._hotkey_handlers.clear()
        # Remove the heartbeat on_press hook.
        if self._heartbeat_hook_ref is not None:
            try:
                log_debug(_MOD, "  Removing heartbeat hook...")
                kb_lib.unhook(self._heartbeat_hook_ref)
                log_info(_MOD, "  ✓ Heartbeat hook removed")
            except Exception as e:
                log_error(_MOD, "Heartbeat hook removal failed at stage unregister: %s", str(e), exc_info=True)
                raise RuntimeError("Could not unregister keyboard heartbeat") from e
        else:
            log_debug(_MOD, "  Heartbeat hook ref is already clear.")
        
        log_info(
            _MOD,
            ">>> UNREGISTERING ALL HOTKEYS COMPLETE - Removed %d action hotkeys",
            removed_count
        )
        self._heartbeat_hook_ref = None

        self._hotkeys_registered = False
        log_debug(_MOD, "All hotkeys unregistered.")

    def _heartbeat_hook(self, _event) -> None:
        """
        Called by ``keyboard.on_press`` on every keypress.
        Updates the heartbeat timestamp so the watchdog knows the hook is live.
        """
        self._last_heartbeat = time.monotonic()
        key_name = getattr(_event, "name", "")
        if key_name:
            normalized_key = key_name.upper()
            observed_at = time.monotonic()
            self._delivery_observation_queue.put(
                (normalized_key, observed_at, hotkey_logger.get_last_dispatch(normalized_key))
            )

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
        return run_function_key_operation(self._start_drag_stop_listeners_owned)

    def _start_drag_stop_listeners_owned(self) -> None:
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
        return run_function_key_operation(self._stop_drag_stop_listeners_owned)

    def _stop_drag_stop_listeners_owned(self) -> None:
        """Stop and discard the drag-stop mouse listener (safe to call any time)."""
        if self._drag_mouse_listener is not None:
            try:
                self._drag_mouse_listener.stop()
            except Exception:
                log_error(_MOD, "Could not stop the drag-stop mouse listener.", exc_info=True)
            self._drag_mouse_listener = None

        if self._drag_stop_key_hook_ref is not None:
            try:
                kb_lib.unhook(self._drag_stop_key_hook_ref)
            except Exception:
                log_error(_MOD, "Could not remove the drag-stop keyboard hook.", exc_info=True)
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

        try:
            def _verify_owned() -> None:
                with self._hooks_lock:
                    if not self._hotkeys_registered:
                        return
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
                        self._unregister_hotkeys_owned()
                        self._register_hotkeys_owned()
                        log_warning(_MOD, "Post-drag handler refresh completed; delivery remains unverified.")
                    else:
                        log_debug(
                            _MOD,
                            "Post-drag hotkey verification OK (%d handlers registered).",
                            registered_count,
                        )
            run_function_key_operation(_verify_owned)
        except Exception:
            log_error(_MOD, "Post-drag handler verification failed.", exc_info=True)

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


def _get_enabled_state(config_manager) -> bool:
    """Return the persisted Keyboard Actions enabled state, defaulting to True."""
    return config_manager.get_bool("keyboardActions", "enabled", True)


def _get_autoclick_service():
    """Return the running AutoClick service (owner of the F6 hook) or None.

    The running app loads the module as ``src.AutoClick``; a plain
    ``import AutoClick`` can create a second, empty copy, so already-loaded
    modules are checked first.
    """
    names = ("src.AutoClick", "AutoClick")
    for name in names:
        module = sys.modules.get(name)
        service = module.get_service() if module is not None else None
        if service is not None:
            return service
    for name in names:
        try:
            service = importlib.import_module(name).get_service()
        except ImportError:
            continue
        except Exception:
            log_error(_MOD, "Could not load %s to find the F6 service.", name, exc_info=True)
            continue
        if service is not None:
            return service
    log_error(_MOD, "AutoClick service not found - F6 hook cannot be reset.")
    return None


def reset_function_key_bindings(
    include_keyboard_actions: bool = True, reason: str = "manual reset"
) -> None:
    """Refresh the enabled bindings as one serialized coordinator operation."""
    def _reset_owned() -> None:
        with _delivery_status_lock:
            _delivery_observed_keys.clear()
        log_info(_MOD, "Function-key binding refresh started (reason=%s).", reason)
        auto_click_service = _get_autoclick_service()
        if auto_click_service is None:
            raise RuntimeError("AutoClick service is unavailable; F6 cannot be refreshed.")

        actions_active = bool(
            include_keyboard_actions
            and _service is not None
            and _service._thread is not None
            and _service._thread.is_alive()
            and not _service._stop_event.is_set()
        )
        auto_click_service._unregister_hotkey()
        try:
            if actions_active:
                _service._rebuild_keyboard_actions_native()
            elif include_keyboard_actions:
                log_warning(_MOD, "F7-F10 refresh skipped because Keyboard Actions is disabled.")
        finally:
            auto_click_service._register_hotkey()

        if auto_click_service._hotkey_handler is None:
            raise RuntimeError("F6 AutoClick hotkey registration failed.")
        if actions_active and (
            len(_service._hotkey_handlers) != 4
            or _service._heartbeat_hook_ref is None
        ):
            raise RuntimeError("F7-F10 handlers or heartbeat were not registered.")

        _set_binding_status(get_function_key_delivery_status())
        log_info(_MOD, "Function-key bindings registered; physical delivery remains unverified.")

    try:
        return run_function_key_operation(_reset_owned)
    except Exception as exc:
        _set_binding_status(f"Bindings unavailable; refresh failed: {exc}")
        raise


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
    # Respect the saved config state instead of forcing Keyboard Actions on.
    enabled_default = _get_enabled_state(config_manager)
    enabled_var = tk.BooleanVar(value=enabled_default)
    ui_status_queue: queue.SimpleQueue = queue.SimpleQueue()

    toggle_frame = ttk.Frame(frame)
    toggle_frame.grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 14))

    ttk.Label(
        toggle_frame,
        text="Enable Keyboard Actions:",
        font=("Segoe UI", 10, "bold"),
    ).pack(side="left", padx=(0, 8))

    def _on_toggle(*_):
        """Start or stop services off the Tk thread."""
        enabled = enabled_var.get()
        config_manager.set_config("keyboardActions", "enabled", str(enabled))
        ui_status_queue.put(("Starting function-key bindings..." if enabled else
                             "Stopping function-key bindings...", False, False, False))

        def _apply_toggle() -> None:
            try:
                if enabled:
                    log_info(_MOD, "Keyboard Actions enabled by user — starting service.")
                    if _service:
                    # If the service thread or watchdog died (e.g. after an exception),
                    # stop() cleans up residual state before start() spawns fresh threads.
                        service_dead = _service._thread and not _service._thread.is_alive()
                        watchdog_dead = _service._watchdog_thread and not _service._watchdog_thread.is_alive()
                        intentionally_stopped = _service._stop_event.is_set()
                        if (service_dead or watchdog_dead) and not intentionally_stopped:
                            log_warning(_MOD, "Service thread was dead — performing clean restart.")
                            _service.stop()
                        _service.start()
                    reset_function_key_bindings(include_keyboard_actions=True, reason="Keyboard Actions enabled")
                    ui_status_queue.put((get_function_key_binding_status(), False, False, True))
                else:
                    log_info(_MOD, "User disabled Keyboard Actions.")
                    if _service:
                        _service.stop()
                    auto_click = _get_autoclick_service()
                    if auto_click is not None:
                        auto_click._unregister_hotkey()
                    ui_status_queue.put(("Service stopped. Hotkeys are inactive.", False, True, True))
            except Exception as exc:
                log_error(_MOD, "Failed to apply Keyboard Actions toggle.", exc_info=True)
                _set_binding_status(f"Bindings unavailable; toggle failed: {exc}")

        threading.Thread(
            target=_apply_toggle,
            name="FunctionKeyToggle",
            daemon=True,
        ).start()

    toggle_cb = ttk.Checkbutton(
        toggle_frame,
        variable=enabled_var,
        command=_on_toggle,
        text="Active",
        state="normal",
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
            value=default
        )
        entry = ttk.Entry(frame, textvariable=key_var, width=10, state="normal")
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

    def _on_reset_key_bindings() -> None:
        was_enabled = enabled_var.get()
        enabled_var.set(True)
        config_manager.set_config("keyboardActions", "enabled", "True")
        reset_button.config(state="disabled")
        status_label.config(text="Refreshing F6-F10 bindings...", foreground="#9a6700")

        def _refresh_bindings() -> None:
            try:
                if _service is None:
                    raise RuntimeError("Keyboard Actions service is unavailable.")
                if not was_enabled and _service is not None:
                    _service.start()
                if _service._thread is None or not _service._thread.is_alive():
                    raise RuntimeError("Keyboard Actions service did not start.")
                reset_function_key_bindings(
                    include_keyboard_actions=True,
                    reason="Reset Key Bindings button",
                )
                status = get_function_key_delivery_status()
                error = None
            except Exception as exc:
                log_error(_MOD, "Failed to reset function-key bindings.", exc_info=True)
                status = f"Bindings unavailable; refresh failed: {exc}"
                error = exc

            ui_status_queue.put((status, False, error is not None, True))

        threading.Thread(
            target=_refresh_bindings,
            name="FunctionKeyManualRefresh",
            daemon=True,
        ).start()

    reset_button = ttk.Button(
        frame, text="Reset Key Bindings", command=_on_reset_key_bindings
    )
    reset_button.grid(row=last_row + 1, column=0, columnspan=3, sticky="w", pady=(0, 8))

    if not _DEPS_AVAILABLE:
        status_text = "⚠  pynput / keyboard not installed — Keyboard Actions disabled."
        status_color = "#cc4444"
    elif enabled_default:
        status_text = "Bindings starting; delivery unverified."
        status_color = "#9a6700"
    else:
        status_text = "Service stopped. Hotkeys are inactive."
        status_color = "#cc4444"

    status_label = ttk.Label(
        frame,
        text=status_text,
        foreground=status_color,
        font=("Segoe UI", 9),
    )
    status_label.grid(row=last_row + 2, column=0, columnspan=3, sticky="w")

    def _update_binding_status(
        status: str, verified: bool = False, unavailable: bool = False
    ) -> None:
        try:
            if status_label.winfo_exists():
                color = "#cc4444" if unavailable else ("#228822" if verified else "#9a6700")
                status_label.config(text=status, foreground=color)
        except tk.TclError:
            pass

    set_function_key_status_callback(
        lambda status, verified=False, unavailable=False: ui_status_queue.put(
            (status, verified, unavailable, False)
        )
    )

    def _drain_ui_status_queue() -> None:
        try:
            if not parent.winfo_exists():
                return
            while True:
                try:
                    status, verified, unavailable, operation_finished = ui_status_queue.get_nowait()
                except queue.Empty:
                    break
                _update_binding_status(status, verified, unavailable)
                if operation_finished:
                    reset_button.config(state="normal")
            parent.after(100, _drain_ui_status_queue)
        except tk.TclError:
            pass

    parent.after(100, _drain_ui_status_queue)

    # Column weights so the description column stretches on resize.
    frame.columnconfigure(2, weight=1)

    # --- Start service thread only if enabled ----------------------------
    if enabled_default and _service:
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
