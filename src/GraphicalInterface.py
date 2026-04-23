"""
GraphicalInterface.py - Main Application Window for ErgoProtect
----------------------------------------------------------------
Creates a Tkinter window with a ttk.Notebook (tabbed layout).
Each tab corresponds to a feature module. Modules are loaded dynamically:
if a module exists and exposes a create_tab() function, it is called;
otherwise a "Module not present." placeholder is shown.

A "General" tab is always shown first. It contains application-wide
settings such as log file path and log retention period.

Why hide instead of close?
  The application lives in the system tray. Closing the window with the X
  button should NOT exit the program — it should just hide the window.
  The user can re-open it via the tray icon. The only way to truly exit is
  via the "Exit" option in the tray menu.

Layout structure
  ┌────────────────────────────────────────────────────┐
  │  [General] [Auto Click] [Keyboard] [Log] ...       │  ← ttk.Notebook tabs
  ├────────────────────────────────────────────────────┤
  │                                                    │
  │   Tab content (varies per module)                  │
  │                                                    │
  └────────────────────────────────────────────────────┘
"""

import importlib
import io
import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from src.AppLogging import (
    log_debug,
    log_error,
    log_info,
    log_warning,
    get_log_dir,
    get_days_to_keep,
    update_log_dir,
    update_days_to_keep,
    cleanup_old_logs,
)

_MOD = "GraphicalInterface"

# Tab definitions: (display_name, module_name_in_src_package)
# The module_name is imported relative to the src/ package.
# "General" is always inserted first programmatically; it does not appear here.
_TABS = [
    ("Rest Reminder",     "RestReminder"),
    ("Auto Click",        "AutoClick"),    
    ("Keyboard Actions",  "KeyboardActions"),
    ("Usage Log",         "UsageLog"),
    ("Usage Graphics",    "UsageGraphics"),    
    ("Help",              "Help"),
]


class GraphicalInterface:
    """
    Main application window containing all feature tabs.

    Responsibilities:
      - Create and configure the Tkinter root window.
      - Apply the application icon to the window title bar (same icon as tray).
      - Build the General tab first (log settings).
      - Build the remaining module-driven notebook tabs.
      - Override the close button to hide (not destroy) the window.
      - Provide show() and hide() methods for the tray icon to call.
    """

    def __init__(self, config_manager, icon_image=None, icon_path: str = None) -> None:
        """
        Build the window. Does NOT call mainloop() – that is the caller's
        responsibility (see main.py).

        Args:
            config_manager: Shared ConfigManager instance passed into each
                            module's create_tab() so they can read/write config.
            icon_image:     Optional PIL Image object (already loaded in main.py
                            for the tray icon). When provided it is also applied
                            to the window's title-bar icon, ensuring both the tray
                            and the GUI show the same image.
            icon_path:      Optional path to the .ico file on disk. When provided,
                            used for iconbitmap() (Windows title bar / taskbar) so
                            the GUI, tray, and .exe file icon all share the same
                            source file. Falls back to assets/icon.ico if omitted.
        """
        self._cfg = config_manager
        self._icon_image = icon_image  # PIL Image or None
        self._icon_path = icon_path    # str path to .ico or None
        self._root = tk.Tk()
        self._configure_window()
        self._build_tabs()
        log_info(_MOD, "GraphicalInterface initialised.")

    # ------------------------------------------------------------------
    # Window configuration
    # ------------------------------------------------------------------

    def _configure_window(self) -> None:
        """Set title, size, icon and other window-manager properties."""
        self._root.title("ErgoProtect")
        self._root.geometry("640x480")
        self._root.minsize(480, 380)
        self._root.resizable(True, False)

        # Apply the window icon. We try multiple strategies so the title bar
        # always shows the correct icon, matching the tray:
        #
        #   1. If a PIL Image was passed in (loaded by main.py for the tray),
        #      convert it to a Tkinter-compatible PhotoImage and use wm_iconphoto.
        #      This guarantees the GUI and tray show exactly the same icon.
        #
        #   2. Fall back to iconbitmap() using the .ico file on disk (Windows).
        #
        #   3. Degrade gracefully with a warning if neither works.
        icon_set = False

        # Strategy 1: PIL Image → PhotoImage (works on all platforms)
        if self._icon_image is not None:
            try:
                from PIL import ImageTk
                photo = ImageTk.PhotoImage(self._icon_image)
                # Keep a reference so it isn't garbage-collected
                self._root._ergo_icon_photo = photo  # type: ignore[attr-defined]
                self._root.wm_iconphoto(True, photo)
                icon_set = True
                log_debug(_MOD, "Window icon set from PIL image via wm_iconphoto.")
            except Exception as exc:
                log_warning(_MOD, "Could not set icon via wm_iconphoto (PIL): %s", exc)

        # Strategy 2: .ico file on disk (Windows iconbitmap)
        if not icon_set:
            # Use the icon_path passed in from main.py (which is always valid
            # after _load_or_generate_icon runs). Fall back to a local search
            # when GraphicalInterface is instantiated standalone (e.g. tests).
            icon_path = self._icon_path
            if not icon_path:
                icon_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "assets", "icon.ico"
                )
            if icon_path and os.path.exists(icon_path):
                try:
                    self._root.iconbitmap(icon_path)
                    icon_set = True
                    log_debug(_MOD, "Window icon set from .ico file: %s", icon_path)
                except Exception as exc:
                    log_warning(_MOD, "Could not load icon from .ico file: %s", exc)

        if not icon_set:
            log_warning(_MOD, "No window icon could be applied.")

        # Override the window close (X) button to hide rather than destroy.
        self._root.protocol("WM_DELETE_WINDOW", self.hide)

    # ------------------------------------------------------------------
    # Tab construction
    # ------------------------------------------------------------------

    def _build_tabs(self) -> None:
        """
        Create the ttk.Notebook, insert the General tab first, then
        populate each module tab.
        """
        notebook = ttk.Notebook(self._root)
        notebook.pack(fill="both", expand=True, padx=4, pady=4)

        # --- General tab (always first) ---------------------------------
        general_frame = ttk.Frame(notebook)
        notebook.add(general_frame, text="  General  ")
        self._build_general_tab(general_frame)

        # --- Module tabs ------------------------------------------------
        for display_name, module_name in _TABS:
            tab_frame = ttk.Frame(notebook)
            notebook.add(tab_frame, text=f"  {display_name}  ")

            loaded = self._try_load_module(module_name)
            if loaded is not None and hasattr(loaded, "create_tab"):
                try:
                    loaded.create_tab(tab_frame, self._cfg)
                except Exception as exc:
                    log_error(_MOD, "Error in %s.create_tab(): %s", module_name, exc, exc_info=True)
                    self._show_placeholder(tab_frame)
            else:
                self._show_placeholder(tab_frame)

    # ------------------------------------------------------------------
    # General tab
    # ------------------------------------------------------------------

    def _build_general_tab(self, parent: tk.Widget) -> None:
        """
        Build the General settings tab.

        Contains:
          - Log File Path: editable field + Browse button (validates on save).
          - Days to Keep Log: numeric spinbox.

        Both fields are pre-populated from config.ini and persist changes
        back to config.ini immediately.
        """
        frame = ttk.Frame(parent, padding=20)
        frame.pack(fill="both", expand=True)

        # --- Title ------------------------------------------------------
        ttk.Label(
            frame,
            text="General Settings",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 16))

        # --- Log Configuration section header ---------------------------
        ttk.Label(
            frame,
            text="Log Configuration",
            font=("Segoe UI", 11, "bold"),
            foreground="#333333",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        ttk.Separator(frame, orient="horizontal").grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=(0, 12)
        )

        # --- Log file path field ----------------------------------------
        ttk.Label(frame, text="Log File Path:").grid(
            row=3, column=0, sticky="w", pady=6, padx=(0, 12)
        )

        log_dir_var = tk.StringVar(
            value=self._cfg.get_config("General", "logfilePath", get_log_dir())
        )
        path_entry = ttk.Entry(frame, textvariable=log_dir_var, width=45)
        path_entry.grid(row=3, column=1, sticky="ew", pady=6)

        def _browse_log_dir() -> None:
            """Open a folder-chooser dialog and update the path field."""
            try:
                from tkinter import filedialog
                chosen = filedialog.askdirectory(
                    title="Select Log File Folder",
                    initialdir=log_dir_var.get() or get_log_dir(),
                )
                if chosen:
                    log_dir_var.set(chosen)
                    _save_log_dir()
            except Exception as exc:
                log_error(_MOD, "Error in Browse dialog: %s", exc, exc_info=True)

        ttk.Button(frame, text="Browse…", command=_browse_log_dir).grid(
            row=3, column=2, sticky="w", padx=(8, 0), pady=6
        )

        def _save_log_dir(*_) -> None:
            """Validate and persist the log directory path."""
            new_path = log_dir_var.get().strip()
            if not new_path:
                log_warning(_MOD, "Empty log path entered — ignored.")
                return

            new_path = os.path.abspath(new_path)

            # Validate: try to create the directory
            try:
                os.makedirs(new_path, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(
                    "Invalid Path",
                    f"Cannot create or access the folder:\n{new_path}\n\n{exc}",
                )
                log_warning(_MOD, "Invalid log path entered: %s — %s", new_path, exc)
                return

            # Persist to config and update the runtime logger
            self._cfg.set_config("General", "logfilePath", new_path)
            update_log_dir(new_path)
            log_dir_var.set(new_path)   # normalise displayed path
            log_info(_MOD, "Log file path updated to: %s", new_path)

        path_entry.bind("<FocusOut>", _save_log_dir)
        path_entry.bind("<Return>", _save_log_dir)

        # Description
        ttk.Label(
            frame,
            text="Folder where daily log files (yyyy-mm-dd_appLog.csv) are stored.",
            foreground="#888888",
            font=("Segoe UI", 8),
        ).grid(row=4, column=1, columnspan=2, sticky="w", padx=(0, 0))

        # --- Days to keep log -------------------------------------------
        ttk.Label(frame, text="Days to Keep Log:").grid(
            row=5, column=0, sticky="w", pady=(16, 6), padx=(0, 12)
        )

        days_var = tk.IntVar(
            value=self._cfg.get_int("General", "DaysToKeepLog", get_days_to_keep())
        )
        days_spin = ttk.Spinbox(frame, from_=1, to=365, increment=1, textvariable=days_var, width=8)
        days_spin.grid(row=5, column=1, sticky="w", pady=(16, 6))

        def _save_days(*_) -> None:
            """Persist and apply the log retention period."""
            try:
                val = int(days_var.get())
                val = max(1, min(365, val))
                self._cfg.set_config("General", "DaysToKeepLog", str(val))
                update_days_to_keep(val)
                log_info(_MOD, "DaysToKeepLog updated to %d.", val)
            except (ValueError, tk.TclError):
                pass

        days_spin.bind("<FocusOut>", _save_days)
        days_spin.bind("<Return>", _save_days)
        days_var.trace_add("write", _save_days)

        ttk.Label(
            frame,
            text="Log files older than this many days are deleted on startup (1–365).",
            foreground="#888888",
            font=("Segoe UI", 8),
        ).grid(row=6, column=1, columnspan=2, sticky="w")

        # --- Separator + info footer ------------------------------------
        ttk.Separator(frame, orient="horizontal").grid(
            row=7, column=0, columnspan=3, sticky="ew", pady=(20, 8)
        )

        ttk.Label(
            frame,
            text=(
                "ErgoProtect — Ergonomic mouse assistance application.\n"
                "Designed to reduce RSI, tendinitis, and Musculoskeletal Disorders."
            ),
            foreground="#666666",
            font=("Segoe UI", 8),
            justify="left",
        ).grid(row=8, column=0, columnspan=3, sticky="w")

        # Column weights
        frame.columnconfigure(1, weight=1)

        log_debug(_MOD, "_build_general_tab() completed.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _try_load_module(module_name: str):
        """
        Attempt to import the feature module.

        Import strategy (tried in order):
          1. ``src.<module_name>``  — standard layout when running with
             ``python main.py`` from the project root.
          2. ``<module_name>``      — direct (flat) import used by PyInstaller
             bundles, where all modules are packed into the top-level namespace
             and the ``src`` sub-package no longer exists.

        Returns the module object on success, or None if all strategies fail.
        Failures are expected and non-fatal (e.g. placeholder modules that
        haven't been written yet, or optional dependencies missing).
        """
        # Strategy 1: src.<module_name> (normal Python execution)
        try:
            return importlib.import_module(f"src.{module_name}")
        except ImportError:
            pass
        except Exception as exc:
            log_error(_MOD, "Unexpected error importing src.%s: %s", module_name, exc, exc_info=True)
            return None

        # Strategy 2: <module_name> directly (PyInstaller bundle / flat layout)
        try:
            return importlib.import_module(module_name)
        except ImportError:
            return None
        except Exception as exc:
            log_error(_MOD, "Unexpected error importing %s: %s", module_name, exc, exc_info=True)
            return None

    @staticmethod
    def _show_placeholder(parent: tk.Widget) -> None:
        """Render the standard 'Module not present.' placeholder."""
        tk.Label(
            parent,
            text="Module not present.",
            font=("Segoe UI", 13),
            foreground="#aaaaaa",
        ).pack(expand=True)

    # ------------------------------------------------------------------
    # Public interface (called by main.py / tray icon)
    # ------------------------------------------------------------------

    def show(self) -> None:
        """Make the window visible and bring it to the foreground."""
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def hide(self) -> None:
        """Hide the window (minimise to tray) without destroying it."""
        self._root.withdraw()

    def destroy(self) -> None:
        """Fully destroy the window (called on application exit)."""
        try:
            self._root.destroy()
        except tk.TclError:
            pass  # already destroyed

    @property
    def root(self) -> tk.Tk:
        """Expose the root Tk widget (needed by main.py for mainloop)."""
        return self._root
