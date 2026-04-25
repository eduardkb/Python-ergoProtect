# ErgoProtect – Installation & Startup Guide

---

## Section 1: Creating a Standalone .EXE

Converting ErgoProtect to a single `.exe` means you (and others) can run it
without installing Python at all.

### Prerequisites

```bash
pip install -r requirements.txt
pip install pyinstaller
```

### Build command

Open a PowerShell terminal, navigate to the ErgoProtect project folder, then run:

```sh
pyinstaller `
  --onefile `
  --windowed `
  --icon=assets/icon.ico `
  --add-data "assets/icon.ico;assets" `
  --name ErgoProtect `
  --clean `
  src/main.py
```

### After the build

1. Find your executable inside the `dist/` folder: `dist/ErgoProtect.exe`
2. Copy `dist/ErgoProtect.exe` to wherever you want to store the app.
3. Copy `config.ini` next to the `.exe` (if you want custom defaults baked in).  
   If `config.ini` is absent, ErgoProtect will create one with defaults on first run.

### Troubleshooting

| Problem | Fix |
|---------|-----|
| "Failed to execute script" | Run from a terminal (`ErgoProtect.exe` in cmd) to see the error. |
| Tray icon is missing | Ensure `assets/icon.ico` was included (`--add-data` flag). |
| Windows Defender warning | This is a false-positive common with PyInstaller. Add an exclusion or sign the exe. |
| `ModuleNotFoundError` | Add `--hidden-import <module>` to the PyInstaller command for the missing module. |

---

## Section 2: Auto-Start with Windows

### Method 1 – Startup Folder (simple)

The Startup folder runs every program inside it when you log in to Windows.

1. Press **Win + R**, type `shell:startup`, press **Enter**.  
   Windows Explorer opens the Startup folder.

2. Right-click inside the folder → **New → Shortcut**.

3. Browse to your `ErgoProtect.exe` and click **Next**.

4. Name the shortcut `ErgoProtect`, then click **Finish**.

5. **Test it**: Log out and back in. ErgoProtect should appear in the tray
   within a few seconds of reaching the desktop.

**Pros**: Simple, no admin rights needed.  
**Cons**: Starts slightly later than Task Scheduler; affected by slow-startup policies.

---

### Method 2 – Task Scheduler (more reliable)

Task Scheduler gives you finer control (run as admin, delay start, etc.)
and is more reliable on corporate or heavily-managed machines.

1. Press **Win**, search **Task Scheduler**, open it.

2. In the right panel click **Create Basic Task…**

3. **Name**: `ErgoProtect`  
   **Description**: `Start ErgoProtect ergonomics tray app on login`  
   Click **Next**.

4. **Trigger**: Select **When I log on** → **Next**.

5. **Action**: Select **Start a program** → **Next**.

6. **Program/script**: Click **Browse** and select your `ErgoProtect.exe`.  
   Leave "Add arguments" and "Start in" blank (unless your app needs them).  
   Click **Next**.

7. Review the summary and click **Finish**.

8. **Test it**: In Task Scheduler, find the task in the list, right-click it
   → **Run**. ErgoProtect should appear in the tray immediately.

**Pros**: Starts reliably, survives policy changes, can be configured to
run elevated (admin) if needed.  
**Cons**: Slightly more steps to set up.

---

### Removing Auto-Start

- **Startup Folder**: Delete the shortcut from `shell:startup`.
- **Task Scheduler**: Open Task Scheduler, find `ErgoProtect`, right-click → **Delete**.
