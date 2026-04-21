"""
main.py - Application Entry Point for ErgoProtect
--------------------------------------------------
This is the first file executed when ErgoProtect starts. It is responsible for:

  1. Initialising the ConfigManager (reads or creates config.ini).
  2. Initialising AppLogging with the configured log directory and retention.
  3. Running log cleanup (deleting files older than DaysToKeepLog).
  4. Creating the GraphicalInterface (hidden on startup).
  5. Building and starting the system tray icon via pystray.
  6. Running the Tkinter event loop alongside the tray icon in a way that
     allows both to operate concurrently.
  7. Handling graceful shutdown when the user selects "Exit" from the tray.

Threading model
---------------
pystray runs its own internal thread for the tray icon. Tkinter, however,
must only be driven from the *main* thread (this is a hard OS requirement on
Windows and macOS). We solve this by:

  - Running the pystray icon in a daemon thread.
  - Running Tkinter's mainloop() on the main thread.
  - Using root.after() to safely schedule GUI operations from other threads.

Graceful shutdown process
--------------------------
  1. User clicks "Exit" in the tray menu.
  2. _on_exit() is called (from the pystray thread).
  3. _on_exit() schedules _shutdown() on the Tkinter main thread via after(0).
  4. _shutdown() stops the AutoClick service, destroys the GUI, and stops
     the tray icon.
  5. mainloop() returns, and the Python process exits normally.
"""

import sys
import os
import threading
import tkinter as tk

# ---------------------------------------------------------------------------
# Path helpers — must be resolved before any src.* imports
# ---------------------------------------------------------------------------

def _get_root() -> str:
    """
    Return the project root directory.

    When running as a PyInstaller .exe, sys._MEIPASS points to the temporary
    folder where bundled files are extracted. When running as plain Python
    (``python main.py`` or ``python src/main.py``), we walk up from __file__.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # PyInstaller one-file / one-folder bundle
        return sys._MEIPASS  # type: ignore[attr-defined]
    # Normal Python execution: __file__ is src/main.py → go up one level
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


_ROOT = _get_root()

# Ensure the project root is on sys.path so that both ``src.*`` imports (normal
# run) and direct module imports (PyInstaller bundle) can be resolved.
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    import pystray
    from PIL import Image, ImageDraw
    _TRAY_AVAILABLE = True
except ImportError:
    _TRAY_AVAILABLE = False
    print("[main] pystray/Pillow not installed – running without tray icon.")

from src.config_manager import ConfigManager
from src.AppLogging import init_logging, cleanup_old_logs, log_info, log_error, shutdown_logging
from src.GraphicalInterface import GraphicalInterface
from src import AutoClick  # imported to access the module-level service


# ---------------------------------------------------------------------------
# Icon helpers
# ---------------------------------------------------------------------------

def _get_icon_path() -> str:
    """Return the absolute path to assets/icon.ico."""
    return os.path.join(_ROOT, "assets", "icon.ico")


def _generate_and_save_icon(icon_path: str) -> "Image.Image":
    """
    Programmatically draw a green circle with a white cross (health symbol),
    save it as a multi-size .ico file at *icon_path*, and return the PIL Image.

    Saving the file ensures PyInstaller's ``--icon`` flag, the tray icon, and
    ``iconbitmap()`` all point to the same valid source.
    """
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Green circle background
    draw.ellipse([4, 4, size - 4, size - 4], fill=(46, 160, 67, 255))

    # White cross (medical / health symbol)
    bar = 40
    arm = 70
    cx, cy = size // 2, size // 2
    draw.rectangle([cx - bar // 2, cy - arm, cx + bar // 2, cy + arm], fill="white")
    draw.rectangle([cx - arm, cy - bar // 2, cx + arm, cy + bar // 2], fill="white")

    # Persist as a proper multi-resolution ICO.
    try:
        os.makedirs(os.path.dirname(icon_path), exist_ok=True)
        sizes = [(256, 256), (48, 48), (32, 32), (16, 16)]
        imgs = [img.resize(s, Image.LANCZOS) for s in sizes]
        imgs[0].save(
            icon_path,
            format="ICO",
            sizes=sizes,
            append_images=imgs[1:],
        )
        print(f"[main] Generated icon saved to {icon_path}")
    except Exception as exc:
        print(f"[main] Could not save generated icon to {icon_path}: {exc}")

    return img


def _load_or_generate_icon() -> "Image.Image":
    """
    Return a PIL Image for the application icon.

    Preference order:
      1. Load assets/icon.ico if it exists and is a valid .ico image.
      2. Generate a fallback icon, save it as assets/icon.ico (so that the
         same file is used for the tray, the GUI title bar, and the .exe
         file icon when bundled with PyInstaller), and return it.
    """
    icon_path = _get_icon_path()
    if os.path.exists(icon_path):
        try:
            img = Image.open(icon_path)
            img.verify()          # raises on corrupt files
            img = Image.open(icon_path).convert("RGBA")  # re-open after verify
            return img
        except Exception as exc:
            print(f"[main] Could not open icon file: {exc} — regenerating.")

    return _generate_and_save_icon(icon_path)


# ---------------------------------------------------------------------------
# Tray menu callbacks
# ---------------------------------------------------------------------------

def _on_open(icon, item, gui: GraphicalInterface) -> None:
    """
    Callback for the "Open" tray menu item and tray icon double-click.

    Because this runs in pystray's thread, we schedule the show() call on
    the Tkinter main thread using root.after() to avoid cross-thread Tk calls.
    """
    gui.root.after(0, gui.show)


def _on_exit(icon, item, gui: GraphicalInterface) -> None:
    """
    Callback for the "Exit" tray menu item.

    Schedules the full shutdown sequence on the Tkinter thread to ensure
    a clean exit without race conditions.
    """
    gui.root.after(0, lambda: _shutdown(icon, gui))


def _shutdown(icon: "pystray.Icon", gui: GraphicalInterface) -> None:
    """
    Perform a clean application shutdown.

    Steps:
      1. Stop the AutoClick background service (joins its thread).
      2. Stop the pystray tray icon (runs in a thread to avoid deadlock).
      3. Flush and stop the log writer.
      4. Destroy the Tkinter window.

    Tkinter's mainloop() returns automatically once the root window is
    destroyed, which allows the Python process to exit naturally.
    """
    log_info("main", "Shutdown initiated by user.")

    # 1. Stop AutoClick service
    service = AutoClick.get_service()
    if service:
        service.stop()

    # 2. Stop the tray icon (stop() is blocking, so run in a thread)
    threading.Thread(target=icon.stop, daemon=True).start()

    # 3. Flush log writer
    shutdown_logging()

    # 4. Destroy the GUI (this causes mainloop() to return)
    gui.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Application entry point.

    Initialises all components and starts the event loop. The function
    returns (and the process exits) only when the user selects "Exit".
    """
    # --- Config ---------------------------------------------------------
    config_manager = ConfigManager()

    # --- Logging initialisation -----------------------------------------
    # Read log settings from config.ini ([General] section).
    log_dir = config_manager.get_config("General", "logfilePath", None)
    days_to_keep = config_manager.get_int("General", "DaysToKeepLog", 30)

    init_logging(log_dir=log_dir, days_to_keep=days_to_keep)

    # --- Log cleanup (delete old log files) -----------------------------
    # Run on every startup as required by specification.
    try:
        cleanup_old_logs(log_dir=log_dir, days_to_keep=days_to_keep)
    except Exception as exc:
        log_error("main", "Log cleanup failed: %s", exc, exc_info=True)

    log_info("main", "ErgoProtect starting up.")

    # --- Icon image (shared between tray and GUI window) ----------------
    # Load/generate once so both the tray and the GUI window use the same
    # image object. If a fallback was generated it is also saved to
    # assets/icon.ico so GraphicalInterface can use iconbitmap() on the same
    # file, guaranteeing all three icon surfaces (tray, title bar, .exe) match.
    icon_image = _load_or_generate_icon() if _TRAY_AVAILABLE else None
    icon_path = _get_icon_path()  # always valid after _load_or_generate_icon()

    # --- GUI (hidden on startup) ----------------------------------------
    # The window is created but immediately hidden so the app starts in the
    # tray without flashing a window at the user.
    # The icon_image is passed in so the GUI can display it in the title bar.
    try:
        gui = GraphicalInterface(config_manager, icon_image=icon_image, icon_path=icon_path)
        gui.hide()
    except Exception as exc:
        log_error("main", "Failed to create GraphicalInterface: %s", exc, exc_info=True)
        raise

    # --- Tray icon ------------------------------------------------------
    if _TRAY_AVAILABLE:
        menu = pystray.Menu(
            pystray.MenuItem("Open ErgoProtect", lambda i, item: _on_open(i, item, gui)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda i, item: _on_exit(i, item, gui)),
        )

        tray_icon = pystray.Icon(
            name="ErgoProtect",
            icon=icon_image,
            title="ErgoProtect",
            menu=menu,
        )

        # Double-clicking the tray icon opens the GUI.
        # pystray fires the default_action on a double-click on Windows.
        tray_icon.default_action = lambda i, item: _on_open(i, item, gui)

        # Run the tray icon in a daemon thread so it doesn't block mainloop()
        tray_thread = threading.Thread(
            target=tray_icon.run,
            name="TrayIconThread",
            daemon=True,
        )
        tray_thread.start()
        log_info("main", "Tray icon started.")
    else:
        # No tray support – just show the window directly so the app is usable
        tray_icon = None
        gui.show()
        log_info("main", "No tray support — window shown directly.")

    # --- Tkinter event loop (main thread) --------------------------------
    # mainloop() blocks here until the root window is destroyed (by _shutdown).
    gui.root.mainloop()
    log_info("main", "ErgoProtect exited cleanly.")


if __name__ == "__main__":
    main()
