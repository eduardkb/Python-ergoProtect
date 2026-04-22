# Next ToDo's
- Problems
    

- Bugs:   
    - Double click on ergoProtect icon on tray should show the app's graphical interface. double clicking on tray icon now does nothing.    
    - On interface when "active" is clicked on auto click tab, it immediatelly dismarks the check. If f7 is pressed when mouse is over it, it is also immediatelly unchecked by the autoclick, I believe.
    - Auto click not writing .ini file if not existant. Also, auto click when the application is initialized, should be enabled or disabeld according to what exists in the .ini file currently. If nothing exists, the default is disabled.
    - GUI active toggle not updating when F6 is pressed.    
    
    - when application is run with "python main.py" on command line, the tab "Keyboard Actions" is built and initialized. But when a .exe is generated with pyinstaller, it still displays "Module not present". dependancy import error? Line 184 (loaded.create_tab(tab_frame, self._cfg)) on file GraphicInterface.py to load module is never executed when building .exe with pyinstaller because the log to record failure reasin is never written on line 186 (log_error(_MOD, "Error in %s.create_tab(): %s", module_name, exc, exc_info=True)).

    - Update readme.md file with current application state