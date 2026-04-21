# Next ToDo's
- Fixing Bugs:
    

- Bugs:
    - when application is run with "python main.py" on command line, the tab "Keyboard Actions" is built and initialized. But when a .exe is generated with pyinstaller, it still just displays "Module not present". also, sometimes different icons are used for tray icon, .exe icon and graphical interface icon. make sure all 3 places have same icon. preferably the icon inside assets folder named icon.ico. just generate a icon if the file on this folder is not readable or not an .ico file. if this happens, use the generated icon everywhere.
    
    - bug when using F10 (left click drag-drop). it seems to mess up other commands (like left click when auto click is active) and all other keyboard clicks (F7, F8 and F9). make sure all these functaionalities work independent from eachother and if any exception/error happens, the original state is recovered where the config.ini file is read and all functionality is restored. after this bug happens, the f6 press to activate autoc-click also stops working. Also, Autoclick is interfering with the drag/drop action. while drag/drop button is held, deactiveate auto-clidk buttons.
    - also, besides all programmed ways to release f10 hold click, pressing f10 should also release the left click hold.
    - when doing drag drop actions manually, after the action, the auto-click cancels the action when mouse stops. when autoclick is active, do not autoclick during 5 seconds after the mouse key was released nor doing the drag action. make failsafe for other actions that you believe can cause other prblems
    
    - Double click on ergoProtect icon on tray should show the app's graphical interface. double clicking on tray icon now does nothing.    
    - Applications like MS Excel and VS Code  are still doing actions on "keyboard press" keyboard shortcuts. On all applications take over the application specific action and do only the action that should be done by the ergoProtect Application.
    - Whenever available, use icon available on assets folder named icon.ico. For the .exe file, for the graphical interface icon display and for the tray display. Only use the generated icon if the icon on the assets folder is unavailable or unreadable or not an icon file.
    - On the graphical interface, keyboard actions tab, the first option should be a switch to enable or disable the functionality on this tab (if deactivated, none of the keyboard bindings on the tab work).
    - On interface when "active" is clicked on auto click tab, it immediatelly dismarks the check. If f7 is pressed when mouse is over it, it is also immediatelly unchecked by the autoclick, I believe.
    - Auto click not writing .ini file if not existant. Also, auto click when the application is initialized, should be enabled or disabeld according to what exists in the .ini file currently. If nothing exists, the default is disabled.
    - Screen (active toggle) not updating when F6 is pressed.
    - Implement app logs on autoClick module
    - Implement logs on the main and graphical interface modules    
    - Change icon generating logic to generate a hand with a finger clicking a button. Theme should be light blue colored.
    

    - Update readme.md file with current application state