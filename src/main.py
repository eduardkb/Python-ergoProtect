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

# Ensure the project root is on the path when running as "python src/main.py"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
# Icon generation
# ---------------------------------------------------------------------------

def _load_or_generate_icon() -> "Image.Image":
    """
    Return a PIL Image to use as the tray icon.

    Preference order:
      1. Load assets/icon.ico if it exists (allows custom branding).
      2. Programmatically draw a simple green circle with a white cross.

    The programmatic fallback means the app always has a visible tray icon
    even if the assets folder is missing – important for first-run and
    portable installs.
    """
    icon_path = os.path.join(_ROOT, "assets", "icon.ico")
    if os.path.exists(icon_path):
        try:
            return Image.open(icon_path).convert("RGBA")
        except Exception as exc:
            print(f"[main] Could not open icon file: {exc}")

    # --- Fallback: draw a green circle with a white cross ---------------
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Green circle background
    draw.ellipse([2, 2, size - 2, size - 2], fill=(46, 160, 67, 255))

    # White cross (medical / health symbol)
    bar = 10          # thickness of each arm
    arm = 14          # length of each arm from centre
    cx, cy = size // 2, size // 2
    draw.rectangle([cx - bar // 2, cy - arm, cx + bar // 2, cy + arm], fill="white")
    draw.rectangle([cx - arm, cy - bar // 2, cx + arm, cy + bar // 2], fill="white")

    return img


# ---------------------------------------------------------------------------
# Tray menu callbacks
# ---------------------------------------------------------------------------

def _on_open(icon, item, gui: GraphicalInterface) -> None:
    """
    Callback for the "Open" tray menu item.

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

    # --- GUI (hidden on startup) ----------------------------------------
    # The window is created but immediately hidden so the app starts in the
    # tray without flashing a window at the user.
    try:
        gui = GraphicalInterface(config_manager)
        gui.hide()
    except Exception as exc:
        log_error("main", "Failed to create GraphicalInterface: %s", exc, exc_info=True)
        raise

    # --- Tray icon ------------------------------------------------------
    if _TRAY_AVAILABLE:
        icon_image = _load_or_generate_icon()

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
