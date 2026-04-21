# ErgoProtect

> **A Windows system-tray application to help prevent repetitive strain injuries.**

---

## ⚠️ Disclaimer

```
DISCLAIMER: This application is provided free of charge with NO WARRANTY
or GUARANTEE of any kind. Use at your own risk. The authors are not
responsible for any damages, injuries, or data loss resulting from the
use of this software. This tool is not a substitute for professional
medical advice. If you experience pain or discomfort, consult a doctor.
```

---

## What is ErgoProtect?

ErgoProtect is a lightweight Windows tray application designed to reduce
the physical strain of repetitive mouse clicking. Instead of pressing the
mouse button hundreds of times per day, ErgoProtect can automatically click
for you when your cursor is still — turning stillness into selection.

The application runs silently in the system tray and can be toggled on/off
via a configurable hotkey at any time.

---

## Features

| Module            | Status      | Description                                              |
|-------------------|-------------|----------------------------------------------------------|
| AutoClick         | ✅ Available | Clicks automatically when the cursor is held still.      |
| Keyboard Actions  | 🔜 Planned  | Remap frequent shortcuts to reduce finger strain.        |
| Usage Log         | 🔜 Planned  | Track daily click and keystroke counts.                  |
| Usage Graphics    | 🔜 Planned  | Visualise usage patterns over time.                      |
| Rest Reminder     | 🔜 Planned  | Alert you to take regular hand-rest breaks.              |

---

## AutoClick Module

### What it does

When enabled, ErgoProtect monitors your mouse cursor position. If the
cursor remains within a configurable distance for a configurable time,
a left mouse-button click is automatically performed at that position.

This removes the need to physically press the mouse button for selections,
links, and UI elements — which can significantly reduce cumulative strain.

### Parameters

| Parameter              | Default | Range      | Description                                      |
|------------------------|---------|------------|--------------------------------------------------|
| Enable AutoClick       | Off     | On / Off   | Master switch. Also togglable via hotkey.        |
| Hotkey                 | F6      | Any key    | Toggles AutoClick on/off from anywhere.          |
| Delay before click     | 200 ms  | 50–2000 ms | How long the cursor must be still before click.  |
| Movement threshold     | 5 px    | 1–50 px    | Max cursor drift that still counts as "still".   |

### Use cases

- Users with carpal tunnel syndrome or tendinitis who cannot click repeatedly.
- Power users who spend hours in forms, IDEs, or creative tools.
- Accessibility use: making computers usable with minimal physical effort.

### Tips

- Start with the default 200 ms delay. Increase it if accidental clicks occur.
- Increase the pixel threshold if you have a tremor or use a trackpad.
- Press F6 (or your configured key) to quickly disable before drag operations.

---

## Configuration

Settings are stored in `config.ini` (created automatically on first run).
You can edit it manually with any text editor.

```ini
[autoClick]
active = False
activate_key = F6
milliseconds_stopped = 200
pixels_threshold = 5
```

The file is saved automatically whenever you change a setting in the GUI.

---

## Requirements

- **OS**: Windows 10 or Windows 11 (tray icon requires Windows)
- **Python**: 3.10 or newer
- **Dependencies** (install via `pip install -r requirements.txt`):
  - `pystray` – system tray icon management
  - `Pillow` – icon image handling
  - `pynput` – mouse monitoring and click injection
  - `keyboard` – global hotkey registration
  - `tkinter` – GUI (bundled with Python on Windows)

---

## Quick Start

```bash
# 1. Clone or unzip the project
# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python src/main.py
```

The ErgoProtect icon will appear in your system tray.  
Double-click it (or right-click → Open) to open the settings window.

---

## Project Structure

```
ErgoProtect/
├── src/
│   ├── main.py              # Entry point & tray icon
│   ├── config_manager.py    # INI config read/write
│   ├── GraphicalInterface.py# Tabbed settings window
│   ├── AutoClick.py         # AutoClick tab + background service
│   ├── KeyboardActions.py   # Placeholder
│   ├── UsageLog.py          # Placeholder
│   ├── UsageGraphics.py     # Placeholder
│   └── RestReminder.py      # Placeholder
├── assets/
│   └── icon.ico             # System tray icon
├── config.ini               # Auto-generated user configuration
├── requirements.txt
├── README.md
└── howToInstall.md
```
