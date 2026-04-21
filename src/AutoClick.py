"""
AutoClick.py - AutoClick Tab UI and Background Service for ErgoProtect
-----------------------------------------------------------------------
This module has two responsibilities:

  1. create_tab()       – builds the Tkinter settings panel shown in the GUI.
  2. AutoClickService   – a background thread that monitors the mouse and
                          performs a left-click when the cursor stays still
                          for the configured duration.

Threading model
---------------
The service runs in a daemon thread so Python's interpreter can exit cleanly
even if the thread is still alive. Communication between the GUI thread and
the service thread is done via simple Python Events and shared primitive
values (protected by a Lock where needed). We deliberately avoid queues here
to keep the code readable.

Mouse-position tracking algorithm
-----------------------------------
Every _POLL_INTERVAL_S seconds the service reads the cursor position.
It computes the Euclidean distance between the new and last-seen position.
If that distance is less than `pixels_threshold` the cursor is considered
"still"; otherwise the stillness timer resets. When the cursor has been
still for `milliseconds_stopped` a single left-click is injected.
A _click_fired flag ensures only ONE click fires per stop — it is cleared
only when the cursor moves again beyond the threshold.

Why Euclidean distance?
  √(Δx² + Δy²) is slightly more expensive than Manhattan distance (|Δx|+|Δy|)
  but behaves like a true circle, which matches how humans perceive "not moved".

Why left-click only?
  A left-click is the most common interaction and the safest automatic action.
  Right-click or double-click could trigger unexpected context menus or actions.
"""

import math
import threading
import time
import tkinter as tk
from tkinter import ttk

# pynput is used for reading cursor position and injecting clicks
# keyboard is used for registering the global hotkey
try:
    from pynput.mouse import Button, Controller as MouseController
    import keyboard as kb_lib
    _DEPS_AVAILABLE = True
except ImportError:
    _DEPS_AVAILABLE = False

# How often (in seconds) the background thread polls mouse position.
# 20ms gives smooth tracking without hammering the CPU.
_POLL_INTERVAL_S = 0.02


# ---------------------------------------------------------------------------
# Background Service
# ---------------------------------------------------------------------------

class AutoClickService:
    """
    Background thread that performs a single automatic left-click when the
    mouse cursor stays within `pixels_threshold` pixels for
    `milliseconds_stopped` milliseconds. Only one click fires per stop —
    the cursor must move again before another click can be triggered.

    Typical usage:
        service = AutoClickService(config_manager)
        service.start()   # launch the monitoring thread
        service.stop()    # stop cleanly
        service.toggle()  # flip active state (used by hotkey)
    """

    def __init__(self, config_manager) -> None:
        """
        Args:
            config_manager: A ConfigManager instance for reading settings.
        """
        self._cfg = config_manager
        self._active = config_manager.get_bool("autoClick", "active", False)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()      # guards _active flag
        self._mouse = MouseController() if _DEPS_AVAILABLE else None
        self._hotkey_registered = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the monitoring thread and register the global hotkey.

        Guards against double-starting: if a thread is already running this
        is a no-op.
        """
        if self._thread and self._thread.is_alive():
            return  # already running

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="AutoClickMonitor",
            daemon=True,           # daemon → won't block Python exit
        )
        self._thread.start()
        self._register_hotkey()

    def stop(self) -> None:
        """
        Signal the monitoring thread to stop and wait for it to exit.

        Sets the stop Event (which the loop checks on every iteration)
        and joins with a short timeout to avoid blocking the GUI thread.
        """
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self._unregister_hotkey()

    def toggle(self) -> None:
        """
        Toggle the active state on/off (called by the hotkey handler).

        Thread-safe: uses a Lock so the GUI thread and hotkey thread cannot
        race on the _active flag.
        """
        with self._lock:
            self._active = not self._active
            self._cfg.set_config("autoClick", "active", str(self._active))

    def set_active(self, active: bool) -> None:
        """
        Explicitly set active state (called by the GUI checkbox).

        Args:
            active: True to enable auto-clicking, False to disable.
        """
        with self._lock:
            self._active = active

    def is_active(self) -> bool:
        """Return the current active state (thread-safe read)."""
        with self._lock:
            return self._active

    # ------------------------------------------------------------------
    # Hotkey management
    # ------------------------------------------------------------------

    def _register_hotkey(self) -> None:
        """
        Register the global activation hotkey from config.

        keyboard.add_hotkey works system-wide (even when the app is in the
        tray), which is exactly what we want so the user can toggle
        AutoClick without opening the window.
        """
        if not _DEPS_AVAILABLE or self._hotkey_registered:
            return
        key = self._cfg.get_config("autoClick", "activate_key", "F6")
        try:
            kb_lib.add_hotkey(key, self.toggle)
            self._hotkey_registered = True
        except Exception as e:
            print(f"[AutoClickService] Could not register hotkey '{key}': {e}")

    def _unregister_hotkey(self) -> None:
        """Remove all registered hotkeys when the service stops."""
        if not _DEPS_AVAILABLE or not self._hotkey_registered:
            return
        try:
            kb_lib.unhook_all_hotkeys()
            self._hotkey_registered = False
        except Exception as e:
            print(f"[AutoClickService] Could not unregister hotkeys: {e}")

    # ------------------------------------------------------------------
    # Monitoring loop (runs in background thread)
    # ------------------------------------------------------------------

    def _monitor_loop(self) -> None:
        """
        Main loop: polls mouse position and fires a single click when still.

        _click_fired ensures exactly one click per stop. It is set to True
        after a click and only reset to False when the cursor moves beyond
        pixels_threshold again — preventing the click-spam bug that occurs
        when still_since keeps accumulating elapsed time after a click.
        """
        if not _DEPS_AVAILABLE:
            print("[AutoClickService] pynput/keyboard not installed – service disabled.")
            return

        last_x, last_y = None, None
        still_since: float | None = None  # timestamp when cursor last settled
        _click_fired: bool = False        # True after click; cleared on movement

        while not self._stop_event.is_set():
            if not self.is_active():
                # Not active → reset all tracking state and sleep briefly
                last_x, last_y = None, None
                still_since = None
                _click_fired = False
                time.sleep(_POLL_INTERVAL_S)
                continue

            # Read fresh thresholds on every pass (respects live GUI edits)
            ms_stopped = self._cfg.get_int("autoClick", "milliseconds_stopped", 200)
            px_threshold = self._cfg.get_int("autoClick", "pixels_threshold", 5)
            seconds_stopped = ms_stopped / 1000.0

            # Sample current cursor position
            pos = self._mouse.position
            cur_x, cur_y = pos

            if last_x is None:
                # First sample after becoming active — initialise tracking state
                last_x, last_y = cur_x, cur_y
                still_since = time.monotonic()
                _click_fired = False
                time.sleep(_POLL_INTERVAL_S)
                continue

            # Euclidean distance from last recorded position
            distance = math.sqrt((cur_x - last_x) ** 2 + (cur_y - last_y) ** 2)

            if distance > px_threshold:
                # Cursor moved beyond threshold → update position, restart
                # the stillness timer, and clear the fired flag so the next
                # stop can trigger a fresh click.
                last_x, last_y = cur_x, cur_y
                still_since = time.monotonic()
                _click_fired = False
            else:
                # Cursor is still (within threshold)
                elapsed = time.monotonic() - still_since
                if elapsed >= seconds_stopped and not _click_fired:
                    # Cursor has been still long enough and no click has fired
                    # yet for this stop → perform exactly one left-click.
                    self._perform_click()
                    _click_fired = True   # block any further clicks until cursor moves

            time.sleep(_POLL_INTERVAL_S)

    def _perform_click(self) -> None:
        """
        Inject a left mouse button click at the current cursor position.

        We press and release rather than using .click() to be explicit about
        what is happening and to make it easier to swap for other button types
        in the future.
        """
        try:
            self._mouse.press(Button.left)
            self._mouse.release(Button.left)
        except Exception as e:
            print(f"[AutoClickService] Click failed: {e}")


# ---------------------------------------------------------------------------
# GUI Tab
# ---------------------------------------------------------------------------

# Module-level reference to the running service (shared with main.py)
_service: AutoClickService | None = None


def get_service() -> AutoClickService | None:
    """Return the module-level service instance (may be None if not started)."""
    return _service


def create_tab(parent: tk.Widget, config_manager) -> tk.Frame:
    """
    Build and return the AutoClick settings tab widget.

    This function is called by GraphicalInterface.py when constructing
    the notebook tabs. It both renders the UI and wires up the service.

    Args:
        parent:         The ttk.Notebook tab frame to populate.
        config_manager: Shared ConfigManager instance.

    Returns:
        The populated Frame widget (not strictly needed but useful for tests).
    """
    global _service

    # --- Initialise service (if not already running) --------------------
    if _service is None:
        _service = AutoClickService(config_manager)
        _service.start()

    # --- Root frame for this tab ----------------------------------------
    frame = ttk.Frame(parent, padding=20)
    frame.pack(fill="both", expand=True)

    # Title label
    title = ttk.Label(frame, text="AutoClick Settings", font=("Segoe UI", 13, "bold"))
    title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))

    # Helper: a small description label rendered in gray below each control
    def _note(row: int, text: str) -> None:
        ttk.Label(
            frame,
            text=text,
            foreground="#888888",
            font=("Segoe UI", 8),
        ).grid(row=row, column=1, sticky="w", padx=(8, 0))

    # ----------------------------------------------------------------
    # Row 1 – Active / Inactive toggle
    # ----------------------------------------------------------------
    active_var = tk.BooleanVar(value=config_manager.get_bool("autoClick", "active"))

    def _on_active_toggle() -> None:
        """
        Called whenever the checkbox changes. Persists the new state to
        config and updates the service without requiring a restart.
        """
        new_val = active_var.get()
        config_manager.set_config("autoClick", "active", str(new_val))
        if _service:
            _service.set_active(new_val)

    ttk.Label(frame, text="Enable AutoClick:").grid(row=1, column=0, sticky="w", pady=6)
    ttk.Checkbutton(
        frame,
        variable=active_var,
        command=_on_active_toggle,
        text="Active",
    ).grid(row=1, column=1, sticky="w", padx=(8, 0))
    _note(2, "Toggleable at any time via the hotkey below.")

    # ----------------------------------------------------------------
    # Row 3 – Activate key
    # ----------------------------------------------------------------
    ttk.Label(frame, text="Hotkey:").grid(row=3, column=0, sticky="w", pady=6)

    key_var = tk.StringVar(value=config_manager.get_config("autoClick", "activate_key", "F6"))
    key_entry = ttk.Entry(frame, textvariable=key_var, width=10)
    key_entry.grid(row=3, column=1, sticky="w", padx=(8, 0))

    def _on_key_change(*_) -> None:
        """
        Save the hotkey to config when the Entry loses focus or user presses
        Enter, then re-register the hotkey with the service.
        """
        new_key = key_var.get().strip()
        if not new_key:
            return
        config_manager.set_config("autoClick", "activate_key", new_key)
        if _service:
            # Re-register by stopping and starting the service
            _service._unregister_hotkey()
            _service._register_hotkey()

    key_entry.bind("<FocusOut>", _on_key_change)
    key_entry.bind("<Return>", _on_key_change)
    _note(4, "Press <Enter> or click away to apply the new hotkey.")

    # ----------------------------------------------------------------
    # Row 5 – Milliseconds stopped before autoclick
    # ----------------------------------------------------------------
    ttk.Label(frame, text="Delay before click (ms):").grid(row=5, column=0, sticky="w", pady=6)

    ms_var = tk.IntVar(value=config_manager.get_int("autoClick", "milliseconds_stopped", 200))
    ms_spin = ttk.Spinbox(frame, from_=50, to=2000, increment=50, textvariable=ms_var, width=8)
    ms_spin.grid(row=5, column=1, sticky="w", padx=(8, 0))

    def _on_ms_change(*_) -> None:
        """Persist the delay value whenever the spinbox changes."""
        try:
            val = int(ms_var.get())
            val = max(50, min(2000, val))   # clamp to valid range
            config_manager.set_config("autoClick", "milliseconds_stopped", str(val))
        except (ValueError, tk.TclError):
            pass  # ignore transient invalid states during typing

    ms_spin.bind("<FocusOut>", _on_ms_change)
    ms_spin.bind("<Return>", _on_ms_change)
    ms_var.trace_add("write", _on_ms_change)
    _note(6, "How long the cursor must be still before a click is triggered (50–2000 ms).")

    # ----------------------------------------------------------------
    # Row 7 – Pixels threshold
    # ----------------------------------------------------------------
    ttk.Label(frame, text="Movement threshold (px):").grid(row=7, column=0, sticky="w", pady=6)

    px_var = tk.IntVar(value=config_manager.get_int("autoClick", "pixels_threshold", 5))
    px_spin = ttk.Spinbox(frame, from_=1, to=50, increment=1, textvariable=px_var, width=8)
    px_spin.grid(row=7, column=1, sticky="w", padx=(8, 0))

    def _on_px_change(*_) -> None:
        """Persist the pixel threshold whenever the spinbox changes."""
        try:
            val = int(px_var.get())
            val = max(1, min(50, val))
            config_manager.set_config("autoClick", "pixels_threshold", str(val))
        except (ValueError, tk.TclError):
            pass

    px_spin.bind("<FocusOut>", _on_px_change)
    px_spin.bind("<Return>", _on_px_change)
    px_var.trace_add("write", _on_px_change)
    _note(8, "Cursor movement below this distance (px) counts as 'still' (1–50 px).")

    # ----------------------------------------------------------------
    # Status bar at the bottom
    # ----------------------------------------------------------------
    separator = ttk.Separator(frame, orient="horizontal")
    separator.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(20, 8))

    status_var = tk.StringVar(value="Service running." if _DEPS_AVAILABLE else
                              "⚠ pynput/keyboard not installed – AutoClick disabled.")
    ttk.Label(frame, textvariable=status_var, foreground="#555555",
              font=("Segoe UI", 9)).grid(row=10, column=0, columnspan=2, sticky="w")

    # Make column 1 stretch so layout is tidy on resize
    frame.columnconfigure(1, weight=1)

    return frame