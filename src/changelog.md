# Changelog

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
