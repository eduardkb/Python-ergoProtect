# Next ToDo's
- Critical:
    - when application is run with "python main.py" on command line, the tab "Keyboard Actions" is built and initialized. But when a .exe is generated with pyinstaller, it still just displays "Module not present".
- Non-Critical-Bugs:
    - Double click on ergoProtect icon on tray should show the app's graphical. double click on tray icon does nothing
    - Applications like MS Excel and VS Code  are still doing actions on "keyboard press" keyboard shortcuts. On all applications take over the application specific action and do only the action that should be done by the ergoProtect Application.
    - Whenever available, use icon available on assets folder named icon.ico. For the .exe file, for the graphical interface icon display and for the tray display. Only use the generated icon if the icon on the assets folder is unavailable or unreadable or not an icon file.
    - On the graphical interface, keyboard actions tab, the first option should be a switch to enable or disable the functionality on this tab (if deactivated, none of the keyboard bindings on the tab work).
    - On interface when "active" is clicked on auto click tab, it immediatelly dismarks the check. If f7 is pressed when mouse is over it, it is also immediatelly unchecked by the autoclick, I believe.
    - Dragdrop F10 not releasing if f10 is pressed again
    - Auto click not writing .ini file if not existant. Also, auto click when the application is initialized, should be enabled or disabeld according to what exists in the .ini file currently. If nothing exists, the default is disabled.
    - Screen (active toggle) not updating when F6 is pressed.
    - Implement app logs on autoClick module
    - Implement logs on the main and graphical interface modules
    - Change icon generating logic to generate a hand with a finger clicking a button. Theme should be light blue colored.
Update readme.md file with current application state