Step-by-Step Guide for AI to Write Module 1: Core Application + AutoClick
Overview
This guide will help an AI assistant write the first module of a Windows tray application for preventing computer-related hand injuries. The application will eventually have multiple features, but this module focuses on the core infrastructure and AutoClick functionality.
The name of the application is: ErgoProtect

Step 1: Project Structure Setup
Instructions for AI:
Create the following folder structure:
HealthClickAssistant/
├── src/
│   ├── __init__.py
│   ├── main.py                    # Entry point, tray icon management
│   ├── config_manager.py          # INI file reading/writing
│   ├── GraphicalInterface.py      # Main GUI window with tabs
│   ├── AutoClick.py               # AutoClick tab and functionality
│   ├── KeyboardActions.py         # Placeholder (shows "Module not present")
│   ├── UsageLog.py               # Placeholder (shows "Module not present")
│   ├── UsageGraphics.py          # Placeholder (shows "Module not present")
│   └── RestReminder.py           # Placeholder (shows "Module not present")
├── assets/
│   └── icon.ico                   # Tray icon (health/hand-related)
├── config.ini                     # User configuration file
├── README.md                      # App documentation + disclaimer
├── howToInstall.md               # Installation & startup instructions
└── requirements.txt              # Python dependencies

Step 2: Define Dependencies
Instructions for AI:
Create requirements.txt with these libraries:

pystray - for system tray icon
Pillow - for icon image handling
pynput - for mouse monitoring and clicking
keyboard - for hotkey detection
tkinter - GUI (usually comes with Python, but mention it)


Step 3: Create the Tray Icon
Instructions for AI:

Design a simple health-related icon (hand with a medical cross or similar)
Save it as assets/icon.ico (Windows ICO format, 256x256 or similar)
Include instructions on how this was created or generated


Step 4: Write config_manager.py
Instructions for AI:
This module should:

Use Python's configparser library
Read config.ini file if it exists
Create default config.ini with [autoClick] section if it doesn't exist
Default values:

active = False
activate_key = F6
milliseconds_stopped = 200
pixels_threshold = 5


Provide methods:

get_config(section, key, default) - get a config value
set_config(section, key, value) - set and save a config value
save_config() - write changes to disk



Comments needed:

Explain INI file structure
Explain why defaults are chosen
Explain each method's purpose


Step 5: Write main.py
Instructions for AI:
This is the application entry point. It should:

Initialize the system tray icon using pystray
Create tray menu with:

"Open" - shows the GUI window
"Exit" - closes the application completely


Double-click on tray icon should open the GUI
When GUI is closed (X button), minimize to tray instead of exiting
Initialize GraphicalInterface window
Start background services (AutoClick listener if active)

Comments needed:

Explain tray icon initialization
Explain event loop and threading
Explain how GUI and tray interact
Explain graceful shutdown process


Step 6: Write GraphicalInterface.py
Instructions for AI:
This creates the main window with tabs:

Use tkinter with ttk.Notebook for tabs
Window properties:

Title: "Health Click Assistant"
Icon: load from assets/icon.ico
Size: 600x400 (or appropriate)
Prevent maximization (optional)


Create 5 tabs:

"Auto Click" → load AutoClick module
"Keyboard Actions" → check if module exists, show message if not
"Usage Log" → check if module exists, show message if not
"Usage Graphics" → check if module exists, show message if not
"Rest Reminder" → check if module exists, show message if not


For each tab:

Try to import the module
If import succeeds and module has create_tab() method, call it
If not, show centered label: "Module not present."


Override window close button (X) to minimize to tray instead

Comments needed:

Explain tab creation logic
Explain module detection mechanism
Explain why window hides instead of closes
Explain layout structure


Step 7: Write AutoClick.py
Instructions for AI:
This module has TWO responsibilities:
A) Tab GUI (function: create_tab(parent, config_manager))
Create the tab interface with:

Active/Inactive Toggle:

Use ttk.Checkbutton or custom toggle
Bound to config [autoClick] active
When changed, save to config and start/stop background service


Activate Key:

Label + Entry widget
Shows current key (default: F6)
Allow user to change (validate it's a valid key)
Save to config on change


Milliseconds stopped before autoclick:

Label + Spinbox (range: 50-2000)
Default: 200
Save to config on change


Pixels threshold:

Label + Spinbox (range: 1-50)
Default: 5
Save to config on change


Layout: Use grid or pack for clean organization

B) Background Service (class: AutoClickService)
This runs in a separate thread and:

Listens for the activate key using keyboard library
When active:

Monitor mouse position using pynput.mouse.Listener
Track last position and time
If mouse hasn't moved more than pixels_threshold for milliseconds_stopped:

Perform a left-click at current position
Reset timer




When inactive or activate key toggled off:

Stop monitoring


Provide methods:

start() - begin monitoring
stop() - stop monitoring
toggle() - toggle on/off via hotkey



Comments needed:

Explain threading model
Explain mouse position tracking algorithm
Explain distance calculation (Euclidean or Manhattan)
Explain why left-click
Explain timer logic
Explain hotkey registration
Explain thread-safe operations


Step 8: Write Placeholder Modules
Instructions for AI:
For each of these files: KeyboardActions.py, UsageLog.py, UsageGraphics.py, RestReminder.py
Create a simple structure:
python"""
[Module Name] - Placeholder
This module is not yet implemented.
"""

def create_tab(parent, config_manager):
    """
    Creates a placeholder tab indicating module is not present.
    This function exists so the module can be detected but shows
    a 'not implemented' message.
    """
    import tkinter as tk
    label = tk.Label(parent, text="Module not present.", 
                     font=("Arial", 14), fg="gray")
    label.pack(expand=True)
    return label
Comments needed:

Explain this is a placeholder
Explain it will be replaced in future iterations


Step 9: Write README.md
Instructions for AI:
Structure:

Disclaimer (at top):

   DISCLAIMER: This application is provided free of charge with NO WARRANTY 
   or GUARANTEE of any kind. Use at your own risk. The authors are not 
   responsible for any damages or injuries resulting from use of this software.

What is Health Click Assistant?

Explain it prevents repetitive strain injuries
Explain it's a tray application for Windows


Features:

List current: AutoClick
List planned: Keyboard Actions, Usage Log, Usage Graphics, Rest Reminder


AutoClick Module:

Explain what it does
Explain parameters
Explain use cases


Configuration:

Explain config.ini file
Show example configuration


Requirements:

Python 3.8+ (or whatever version)
List dependencies



Comments needed:

Clear, user-friendly language
No technical jargon


Step 10: Write howToInstall.md
Instructions for AI:
Create two sections:
Section 1: Creating an EXE file

Install PyInstaller: pip install pyinstaller
Navigate to project folder
Run command:

   pyinstaller --onefile --windowed --icon=assets/icon.ico --add-data "assets/icon.ico;assets" src/main.py --name HealthClickAssistant

Explain where to find the .exe (in dist/ folder)
Explain to copy config.ini next to the .exe

Section 2: Auto-start on Windows 10/11
Method 1: Startup Folder

Press Win + R
Type shell:startup and press Enter
Create shortcut to the .exe in this folder
Explain what happens on next login

Method 2: Task Scheduler (more reliable)

Open Task Scheduler
Create Basic Task
Name: "Health Click Assistant"
Trigger: "When I log on"
Action: "Start a program"
Browse to .exe location
Finish and test

Comments needed:

Step-by-step with screenshots descriptions
Explain differences between methods
Troubleshooting common issues


Step 11: Code Quality Requirements
Instructions for AI:
Ensure ALL code includes:

Docstrings for every class and function
Inline comments explaining:

Why something is done (not just what)
Complex logic
Threading decisions
UI layout choices


Error handling:

Try/except blocks for file I/O
Try/except for imports
Graceful degradation if icon missing


Type hints (optional but recommended)
Consistent naming:

snake_case for functions/variables
PascalCase for classes
UPPER_CASE for constants




Step 12: Testing Checklist for AI
Instructions for AI:
Before considering module complete, verify:

 Application starts and tray icon appears
 Double-click tray icon opens window
 Window close button minimizes to tray (doesn't exit)
 "Exit" in tray menu closes app completely
 AutoClick tab loads with all controls
 Other tabs show "Module not present"
 Config.ini is created with defaults if missing
 Changing AutoClick settings updates config.ini
 Hotkey (F6) toggles AutoClick on/off
 When active, mouse stopping triggers left-click
 Parameters (milliseconds, pixels) are respected
 Icon file exists and loads properly
 No crashes or unhandled exceptions


Step 13: Deliverables
Instructions for AI:
Package everything in a ZIP file named HealthClickAssistant_Module1.zip containing:

Complete folder structure as defined in Step 1
All Python files with comprehensive comments
assets/icon.ico file
README.md with disclaimer
howToInstall.md with both sections
requirements.txt
Sample config.ini (optional, will be auto-generated)


Final Notes for AI
Coding Style:

Use clear, readable variable names
Prefer clarity over cleverness
Add comments generously - assume reader is learning Python
Use meaningful commit messages if using git

Focus Areas:

Thread safety between GUI and background service
Clean shutdown (no orphaned threads)
Responsive UI (don't block on long operations)
Config persistence (save immediately on change)

Future Extensibility:

Design config_manager to handle multiple sections
Design GraphicalInterface to easily add new tabs
Keep modules independent (minimal coupling)

This completes the specification for Module 1. Future modules will build on this foundation.