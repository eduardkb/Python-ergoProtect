# Changelog

## [1.0.26] - 2026-09-19

### Fixed
- **Application Exit – Tray menu exception**: Fixed AttributeError when exiting through tray icon by calling the correct mouse listener cleanup method during shutdown.

## [1.0.25] - 2026-09-19

### Fixed
- **Application Exit – Reliable close controls**: Fixed tray-menu exit handling and added an Exit button in General settings for immediate application close.

## [1.0.24] - 2026-09-19

### Improved
- **Logging – Configurable log output**: Added a saved log-level setting, reliable default log-folder setup, and startup cleanup using the configured folder and retention period.

## [1.0.23] - 2026-09-18

### Improved
- **Function Keys – Safer recovery checks**: Recovery now reports failure instead of silently completing if every required keyboard binding was not restored.

## [1.0.22] - 2026-09-18

### Fixed
- **Function Keys – Permanent assignments**: F6 through F10 are now kept active with their required assignments for the full time ErgoProtect is running.

## [1.0.21] - 2026-09-18

### Improved
- **Function Keys – More resilient recovery**: F6–F10 now rebuild together through one protected recovery process, stale queued actions are ignored, and all keyboard services close cleanly with the app.

## [1.0.20] - 2026-09-18

### Improved
- **Keyboard Actions – Faster hook handling**: Function-key actions are now processed away from the Windows hook callback, helping keep the bindings responsive during logging and mouse actions.

## [1.0.19] - 2026-09-18

### Fixed
- **Keyboard Actions – Windows warning cleanup**: Fixed a 64-bit Windows message-handling error and removed a harmless heartbeat cleanup warning, while keeping function-key recovery available.

## [1.0.18] - 2026-09-18

### Fixed
- **Keyboard Actions – False hook-loss errors**: The app no longer treats an internal simulated key test as a failed key binding, preventing repeated recovery errors when the function keys are working normally.

## [1.0.17] - 2026-09-18

### Fixed
- **Keyboard Actions – Full key-binding reset**: Resetting key bindings now replaces the underlying Windows keyboard hook and restores fresh function-key shortcuts. Turning Keyboard Actions back on uses the same recovery process, with detailed event logging for troubleshooting.

## [1.0.16] - 2026-09-18

### Enhanced
- **Keyboard Actions – Real end-to-end watchdog probe**: Replaced theoretical hook liveness checks with actual synthetic keypress simulation. The watchdog now sends a test key event and verifies the callback fires, providing definitive proof that keybindings are working end-to-end.
- **Keyboard Actions – Detailed keybinding loss diagnostics**: When a keybinding is lost, the log now records detailed error context including hook listener status, handler count, last heartbeat timestamp, and probable cause (screen lock, hibernation, UAC prompt, driver crash, etc.). This makes troubleshooting keybinding failures much faster.

## [1.0.15] - 2026-09-18

### Fix
- **Identation bug

## [1.0.14] - 2026-09-18

### Adding logging
- **"Key Bindings" Added logging

## [1.0.13] - 2026-07-31

### Fixed
- **Keyboard Actions – "Reset Key Bindings" now properly restores exclusive bindings**: The reset button now explicitly clears the keyboard library's entire hook state via `unhook_all()` before re-registering hotkeys, ensuring the `suppress=True` flag (exclusive binding) is properly applied when the library is in a corrupted state after system events like hibernation, screen lock, or UAC prompts.

## [1.0.12] - 2026-07-30

### Fixed
- **Keyboard Actions – "Reset Key Bindings" no longer bypasses the disable toggle**: The button now only resets F7–F10 when "Enable Keyboard Actions" is on; while disabled it resets just F6, avoiding a state where hotkeys were silently reactivated with no service supervising them.
- **AutoClick – Hotkey registration race fixed**: Registering/unregistering the F6 hotkey is now protected by a lock, preventing a rare race if two things (e.g. the watchdog and a manual reset) tried to change it at the same moment.

## [1.0.11] - 2026-07-30

### Added
- **Keyboard Actions – "Reset Key Bindings" button**: Added a new button on the Keyboard Actions tab that lets you instantly release and re-bind all of ErgoProtect's function-key shortcuts (F6 for AutoClick, F7–F10 for Keyboard Actions) with a single click, useful if a key stops responding.

## [1.0.10] - 2026-06-29

### Fixed
- **AutoClick – Eliminated spurious "Left button physically pressed" log spam**: Fixed a thread race condition where the autoclick guard flag (`_is_auto_clicking`) was not safely visible to the mouse listener thread, causing synthetic clicks to be misidentified as physical presses. A dedicated lock now protects the flag, ensuring the log only fires for genuine user input.
- **AutoClick – Drag lock threshold reduced to 300 ms**: Drag/selection cooldown is now only applied when the left button is held for at least 300 ms (previously 500 ms). Shorter clicks are ignored, preventing unnecessary autoclick delays after quick taps.

## [1.0.8] - 2026-06-29

### Fixed
- **KeyboardActions – Eliminated spurious watchdog warnings**: The watchdog no longer treats an idle heartbeat (no keypresses from the user) as a sign of a broken hook. A stale heartbeat alone is not meaningful — hooks only fire on actual key presses. Recovery is now triggered only when the OS hook thread is genuinely dead or hotkey handlers are found to be missing.
- **KeyboardActions – Reduced log noise during recovery**: Per-key registration and unregistration log lines are now DEBUG-level so they don't appear in normal INFO logs. The "hotkeys recovered" warning is emitted exactly once per loss/recovery cycle.
- **KeyboardActions – Accurate recovery warning**: The warning "Hotkeys have been recovered" is now only written when hotkeys were actually lost and successfully restored, never during normal operation.

## [1.0.7] - 2026-06-29

### Fixed
- **KeyboardActions – Faster hook recovery**: Reduced watchdog check interval from 5 s to 2 s and stale threshold from 15 s to 8 s, so lost function key hooks are detected and recovered much faster (within a few seconds instead of potentially minutes).
- **KeyboardActions – Zombie hook detection**: Watchdog now also triggers re-registration when the heartbeat has been stale beyond the threshold even if the OS listener appears alive, catching "frozen" hook states that previously went undetected.
- **KeyboardActions – New `force_reregister_all()` method**: Added a public method to unconditionally unregister and re-register all F7–F10 hooks, used by the Active toggle and by AutoClick to ensure clean hook state.
- **KeyboardActions Active checkbox – Re-registers all function keys**: Toggling the "Active" checkbox to checked now forces immediate re-registration of F7–F10 (KeyboardActions) and also re-registers F6 (AutoClick hotkey), restoring all function keys at once.
- **AutoClick Active checkbox – Re-registers all function keys**: Toggling the AutoClick "Active" checkbox to checked now forces immediate re-registration of F6 (AutoClick) and F7–F10 (KeyboardActions), restoring all function keys at once.

## [1.0.6] - 2026-06-25

### Fixed
- **KeyboardActions – PowerEventWatcher persistent OverflowError on 64-bit Windows**: The previous fix (`c_void_p(-3)`) still overflowed because ctypes was guessing 32-bit int for every argument of `CreateWindowExW`. Fixed by explicitly declaring `argtypes`, using `ctypes.c_size_t` for the parent-HWND parameter so `HWND_MESSAGE = -3` is correctly pointer-sized on 64-bit Windows. Also hardened `PostMessageW` in `stop()` by wrapping the stored HWND in `ctypes.wintypes.HWND()`.

## [1.0.5] - 2026-06-25

### Fixed
- **KeyboardActions – PowerEventWatcher crash on 64-bit Windows**: `HWND_MESSAGE` was incorrectly wrapped in `ctypes.wintypes.HWND(-3)`, causing an `OverflowError` when passed as argument 11 to `CreateWindowExW` on 64-bit Windows. Fixed by passing it as `ctypes.c_void_p(-3)` instead, which correctly handles the pointer-sized value on both 32-bit and 64-bit targets.

## [1.0.4] - 2026-06-25

### Fixed
- **KeyboardActions – Fast recovery after hibernation/sleep**: Reduced `_WATCHDOG_INTERVAL_S` from 8 s to 5 s and `_HOOK_STALE_THRESHOLD_S` from 20 s to 15 s so the watchdog catches dead hooks sooner. Added a Windows power-event watcher (`_PowerEventWatcher`) that listens for `WM_POWERBROADCAST / PBT_APMRESUMESUSPEND` and `PBT_APMRESUMEAUTOMATIC` messages via a hidden message-only window and triggers an immediate hook restart the moment the OS wakes from hibernation or sleep — restoring F6–F10 key mappings within a few seconds (well under the 30-second requirement) instead of waiting for the next watchdog poll. On non-Windows platforms the watcher is a safe no-op.
- **KeyboardActions – Mapping lost/recovered warning logs**: The watchdog and power-event resume path now emit a `WARNING` log when key mappings are detected as lost and a matching `WARNING` when they are successfully restored, making both events clearly visible in the application log.

## [1.0.3] - 2026-06-25

### Fixed
- **AutoClick – Reduced log spam**: The debug message `"Drag/selection released — stillness timer reset"` was being written hundreds of times per day (once every 20ms while the mouse was still near the drag-release point). It is now logged only once per drag-release event instead of on every poll tick.
- **AutoClick – Recovery warning logs**: When the monitor thread is restarted by the watchdog after hibernation/sleep, the log now emits a `WARNING` level message confirming recovery is complete (previously only `INFO`). The `_recover()` method also now logs at `WARNING` instead of `INFO` since it is triggered by an unexpected exception.
- **KeyboardActions – Recovery warning logs**: When the watchdog restarts keyboard hooks after hibernation, sleep, UAC prompt, or screen lock, a `WARNING` level message is now logged on successful restart so the event is visible in the log. Added `WARNING` in `_service_loop` exception handler confirming service recovered. Added `WARNING` after post-drag hotkey re-registration completes so binding restoration is visible.

### Notes on hibernation/sleep recovery
- `AutoClick` watchdog interval: **10 seconds** (`_WATCHDOG_INTERVAL_S` in `AutoClick.py` line 46)
- `KeyboardActions` watchdog interval: **8 seconds** (`_WATCHDOG_INTERVAL_S` in `KeyboardActions.py` line 37)
- Maximum time to recover key bindings after wake from sleep: ~10 seconds
- Recovery is fully automated — no user action required
