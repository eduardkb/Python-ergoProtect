# Next ToDo's

- Problems                
    - F6 hotkey box is grayed out. Make it editable again.

- Bugs:
    
- Non-Urgent Bugs
    - Update readme.md file with current application state when main functionality is ready.

Fixed:
    - "Keyboard Actinos" tab has all its options grayed out. un-do this. the options should be available and work for the user to change or disable the function if he needs/wants to.
    - when exiting through the tray icon exit option I get exeption below although the app exits. ( the exit button on the general tab works and does not display this error)
        PS C:\Users\eduard\dev\Python-ergoProtect\src> python .\main.py
        Exception in Tkinter callback
        Traceback (most recent call last):
        File "C:\Python314\Lib\tkinter\__init__.py", line 2093, in __call__
            return self.func(*args)
                ~~~~~~~~~^^^^^^^
        File "C:\Python314\Lib\tkinter\__init__.py", line 876, in callit
            func(*args, **kw)
            ~~~~^^^^^^^^^^^^^
        File "C:\Users\eduard\dev\Python-ergoProtect\src\main.py", line 217, in <lambda>
            gui.root.after(0, lambda: _shutdown(icon, gui))
                                    ~~~~~~~~~^^^^^^^^^^^
        File "C:\Users\eduard\dev\Python-ergoProtect\src\main.py", line 249, in _shutdown
            keyboard_service.stop()
            ~~~~~~~~~~~~~~~~~~~~~^^
        File "C:\Users\eduard\dev\Python-ergoProtect\src\KeyboardActions.py", line 554, in stop
            self._stop_drag_mouse_listener()
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        AttributeError: 'KeyboardActionsService' object has no attribute '_stop_drag_mouse_listener'. Did you mean: '_drag_mouse_listener'?
    - Tray icon of the application, if left clicked, a menu appears with one of the option being "exit". clicking it does not closes the app anymore. fix this. and, on the app's screen, "general" tab, add a "Exit" button on the bottom right of the tab. if clicked, the app should exit immediatelly.
    - make a logging overhaul. the app reads parameters from a .ini file in the root directory where the app is located. make it read a parameter called log_level inside [GENERAL]. The default (if nothing present, is 1). 1 = only information. 2 = information + waring. 3 = all (info, warn, error). plus insert logging where needed and where appropriate if missing. Give a special attention to error logs writing them whenever anything happens that could indicate a problem with the app. As it is done already with other parameters, write this parameter as well to the .ini file on app startup if the parameter is not already there.
    - make sure the log file location is always the same (read from the .ini file). if the .ini file "logfilepath" parameter inside [GENERAL] does not exist, write it as well as being "<Current location where python files or executable is being executed>/app_logs". The log files that are older than 30 days (parameter on .ini file) are not being deleted. make sure that on app launch, it consults the correct folder and then searches for old files inside this correct folder.

