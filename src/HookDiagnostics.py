"""
HookDiagnostics.py - Keyboard Hook Monitoring and Process Diagnostics
-----------------------------------------------------------------------
Provides tools to detect keyboard hook loss and identify interfering processes.

This module tracks:
  - Hook registration/unregistration events
  - Watchdog health checks
  - Process snapshots before/after hook loss
  - Detailed logging of every hook operation
"""

import threading
import time
import psutil
import sys
from datetime import datetime
from typing import List, Tuple, Optional

try:
    from src.AppLogging import log_info, log_warning, log_error, log_debug
except ImportError:
    from AppLogging import log_info, log_warning, log_error, log_debug

_MOD = "HookDiagnostics"


class HookLossDetector:
    """Track hook registration/loss and record process state at time of loss."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._hook_registered_time: Optional[float] = None
        self._last_loss_time: Optional[float] = None
        self._loss_count = 0
        self._process_snapshot_on_loss: List[Tuple] = []
        
    def hook_registered(self, context: str = ""):
        """Called when keyboard hook is successfully registered."""
        with self._lock:
            self._hook_registered_time = time.monotonic()
        
        log_info(
            _MOD,
            "✓ HOOK REGISTERED - Context: %s - Timestamp: %.3f",
            context or "(unknown)",
            self._hook_registered_time
        )
    
    def hook_lost(self, context: str = ""):
        """Called when hook loss is detected."""
        with self._lock:
            self._last_loss_time = time.monotonic()
            self._loss_count += 1
            uptime = (
                self._last_loss_time - self._hook_registered_time
                if self._hook_registered_time
                else -1
            )
            
            # Capture process snapshot
            self._process_snapshot_on_loss = self._get_process_snapshot()
        
        log_error(
            _MOD,
            "❌ HOOK LOST (occurrence #%d) - Context: %s - Uptime: %.1f seconds",
            self._loss_count,
            context or "(unknown)",
            uptime if uptime >= 0 else -1
        )
        
        # Log process snapshot
        self._log_processes_at_loss()
    
    def hook_recovered(self, context: str = ""):
        """Called when hook is re-registered after loss."""
        log_info(
            _MOD,
            "✓ HOOK RECOVERED - Context: %s - Attempts made: Auto-recovery after loss #%d",
            context or "watchdog",
            self._loss_count
        )
    
    def _get_process_snapshot(self) -> List[Tuple]:
        """Get current list of running processes."""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'username', 'create_time']):
                try:
                    info = proc.info
                    processes.append((
                        info['pid'],
                        info['name'],
                        info['username'] or "SYSTEM",
                        info['create_time'] or 0
                    ))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return sorted(processes, key=lambda x: x[1])
        except Exception as e:
            log_warning(_MOD, "Could not capture process snapshot: %s", str(e))
            return []
    
    def _log_processes_at_loss(self):
        """Log details of all processes running at time of hook loss."""
        if not self._process_snapshot_on_loss:
            log_warning(_MOD, "No process snapshot available for loss event")
            return
        
        log_error(
            _MOD,
            "=== PROCESSES AT HOOK LOSS ===" 
        )
        
        # Log system processes that frequently interfere
        suspicious_patterns = [
            'explorer.exe', 'svchost.exe', 'WmiPrvSE.exe', 'SearchIndexer.exe',
            'WinDefend', 'MsSecurityScanner', 'python', 'discord', 'steam',
            'obs', 'remote', 'teamviewer', 'anydesk', 'onedrive'
        ]
        
        suspicious_found = []
        for pid, name, user, create_time in self._process_snapshot_on_loss:
            if any(pattern.lower() in name.lower() for pattern in suspicious_patterns):
                suspicious_found.append((pid, name, user))
        
        if suspicious_found:
            log_error(
                _MOD,
                "⚠️  SUSPICIOUS PROCESSES FOUND: %d potentially interfering",
                len(suspicious_found)
            )
            for pid, name, user in suspicious_found:
                log_error(
                    _MOD,
                    "  - PID %d: %s (User: %s)",
                    pid, name, user
                )
        else:
            log_warning(_MOD, "No immediately obvious suspicious processes found")
        
        # Log total process count
        log_error(_MOD, "Total processes: %d", len(self._process_snapshot_on_loss))
    
    def get_statistics(self) -> dict:
        """Return statistics about hook loss events."""
        with self._lock:
            return {
                'loss_count': self._loss_count,
                'last_loss_time': self._last_loss_time,
                'hook_uptime': (
                    time.monotonic() - self._hook_registered_time
                    if self._hook_registered_time
                    else 0
                )
            }


class WatchdogHealthMonitor:
    """Track watchdog thread health and recovery attempts."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._check_count = 0
        self._recovery_attempts = 0
        self._successful_recoveries = 0
        self._failed_recoveries = 0
        self._last_check_time: Optional[float] = None
        self._hook_was_alive = True
        
    def check_performed(self, hook_alive: bool, context: str = ""):
        """Log each watchdog check."""
        with self._lock:
            self._check_count += 1
            self._last_check_time = time.monotonic()
            
            # Only log state changes to reduce noise
            if hook_alive != self._hook_was_alive:
                state_str = "ALIVE" if hook_alive else "DEAD"
                log_debug(
                    _MOD,
                    "Watchdog check #%d: Hook is %s - %s",
                    self._check_count,
                    state_str,
                    context or "(routine check)"
                )
                self._hook_was_alive = hook_alive
    
    def recovery_attempted(self, context: str = ""):
        """Log when watchdog attempts to recover the hook."""
        with self._lock:
            self._recovery_attempts += 1
        
        log_warning(
            _MOD,
            "Watchdog attempting recovery #%d - %s",
            self._recovery_attempts,
            context or "(unhook + re-register)"
        )
    
    def recovery_succeeded(self):
        """Log successful hook recovery."""
        with self._lock:
            self._successful_recoveries += 1
        
        log_info(
            _MOD,
            "✓ Recovery succeeded - Success count: %d/%d",
            self._successful_recoveries,
            self._recovery_attempts
        )
    
    def recovery_failed(self, error: str = ""):
        """Log failed recovery attempt."""
        with self._lock:
            self._failed_recoveries += 1
        
        log_error(
            _MOD,
            "❌ Recovery FAILED #%d/%d - Error: %s",
            self._failed_recoveries,
            self._recovery_attempts,
            error or "(no error details)"
        )
    
    def get_statistics(self) -> dict:
        """Return watchdog statistics."""
        with self._lock:
            return {
                'check_count': self._check_count,
                'recovery_attempts': self._recovery_attempts,
                'successful_recoveries': self._successful_recoveries,
                'failed_recoveries': self._failed_recoveries,
                'success_rate': (
                    self._successful_recoveries / self._recovery_attempts * 100
                    if self._recovery_attempts > 0
                    else 0
                )
            }


class HotkeyRegistrationLogger:
    """Track individual hotkey registration/unregistration."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._registered_hotkeys: dict = {}
        self._register_count = 0
        self._unregister_count = 0
        
    def hotkey_registered(self, key: str, action: str):
        """Log when a hotkey is registered."""
        with self._lock:
            self._registered_hotkeys[key] = {
                'action': action,
                'time': time.monotonic()
            }
            self._register_count += 1
        
        log_debug(
            _MOD,
            "Hotkey registered: %s -> %s",
            key, action
        )
    
    def hotkey_unregistered(self, key: str):
        """Log when a hotkey is unregistered."""
        with self._lock:
            if key in self._registered_hotkeys:
                del self._registered_hotkeys[key]
            self._unregister_count += 1
        
        log_debug(
            _MOD,
            "Hotkey unregistered: %s",
            key
        )
    
    def all_unregistered(self, count: int):
        """Log mass unregistration (e.g., unhook_all)."""
        with self._lock:
            self._registered_hotkeys.clear()
            self._unregister_count += count
        
        log_info(
            _MOD,
            "All %d hotkeys unregistered",
            count
        )
    
    def get_active_hotkeys(self) -> List[str]:
        """Return list of currently registered hotkeys."""
        with self._lock:
            return list(self._registered_hotkeys.keys())
    
    def get_statistics(self) -> dict:
        """Return hotkey registration statistics."""
        with self._lock:
            return {
                'active_hotkeys': len(self._registered_hotkeys),
                'total_registered': self._register_count,
                'total_unregistered': self._unregister_count,
            }


# Global instances
hook_loss_detector = HookLossDetector()
watchdog_monitor = WatchdogHealthMonitor()
hotkey_logger = HotkeyRegistrationLogger()


def log_diagnostic_summary():
    """Log a summary of all hook diagnostics."""
    loss_stats = hook_loss_detector.get_statistics()
    watchdog_stats = watchdog_monitor.get_statistics()
    hotkey_stats = hotkey_logger.get_statistics()
    
    log_info(_MOD, "=== HOOK DIAGNOSTICS SUMMARY ===")
    log_info(
        _MOD,
        "Hook losses: %d | Last loss: %s | Uptime: %.1f sec",
        loss_stats['loss_count'],
        datetime.fromtimestamp(loss_stats['last_loss_time']).strftime("%H:%M:%S")
        if loss_stats['last_loss_time'] else "Never",
        loss_stats['hook_uptime']
    )
    log_info(
        _MOD,
        "Watchdog: %d checks | %d recovery attempts | Success rate: %.1f%%",
        watchdog_stats['check_count'],
        watchdog_stats['recovery_attempts'],
        watchdog_stats['success_rate']
    )
    log_info(
        _MOD,
        "Hotkeys: %d active | %d total registered | %d unregistered",
        hotkey_stats['active_hotkeys'],
        hotkey_stats['total_registered'],
        hotkey_stats['total_unregistered']
    )
