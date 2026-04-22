# Next ToDo's
- Fixing Bugs:
    

- Bugs:
    - besides all programmed ways to release f10 hold click, pressing f10 should also release the left click hold.

    - when doing drag drop actions manually (not using f10), after the action, the auto-click cancels the action when mouse stops. when autoclick is active, do not autoclick during 5 seconds after the mouse key was released nor doing the drag action. make failsafe for other actions that you believe can cause other prblems. do not make this 5 seconds count on normal actions like one left-clicd, one right click or a double-left-click
    - bug when using F10 (left click drag-drop). it seems to mess up other commands (like left click when auto click is active) and all other keyboard clicks (F7, F8 and F9). make sure all these functaionalities work independent from eachother and if any exception/error happens, the original state is recovered where the config.ini file is read and all functionality is restored. after this bug happens, the f6 press to activate autoc-click also stops working. Also, Autoclick is interfering with the drag/drop action. while drag/drop button is held, deactiveate auto-clidk buttons.
    
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
    
    - when application is run with "python main.py" on command line, the tab "Keyboard Actions" is built and initialized. But when a .exe is generated with pyinstaller, it still displays "Module not present". dependancy import error? Line 184 (loaded.create_tab(tab_frame, self._cfg)) on file GraphicInterface.py to load module is never executed when building .exe with pyinstaller because the log to record failure reasin is never written on line 186 (log_error(_MOD, "Error in %s.create_tab(): %s", module_name, exc, exc_info=True)).

    - Update readme.md file with current application state