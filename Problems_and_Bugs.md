# Next ToDo's
- Problems    
    Noted:        
        - "Keyboard Actinos" tab has all its options grayed out. un-do this. the options should be available and work for the user to change or disable the function if he needs/wants to.


    Fixed:
        - Tray icon of the application, if left clicked, a menu appears with one of the option being "exit". clicking it does not closes the app anymore. fix this. and, on the app's screen, "general" tab, add a "Exit" button on the bottom right of the tab. if clicked, the app should exit immediatelly.
        - make a logging overhaul. the app reads parameters from a .ini file in the root directory where the app is located. make it read a parameter called log_level inside [GENERAL]. The default (if nothing present, is 1). 1 = only information. 2 = information + waring. 3 = all (info, warn, error). plus insert logging where needed and where appropriate if missing. Give a special attention to error logs writing them whenever anything happens that could indicate a problem with the app. As it is done already with other parameters, write this parameter as well to the .ini file on app startup if the parameter is not already there.
        - make sure the log file location is always the same (read from the .ini file). if the .ini file "logfilepath" parameter inside [GENERAL] does not exist, write it as well as being "<Current location where python files or executable is being executed>/app_logs". The log files that are older than 30 days (parameter on .ini file) are not being deleted. make sure that on app launch, it consults the correct folder and then searches for old files inside this correct folder.

- Bugs:
    
- Non-Urgent Bugs
    - after manual or Keyboard Actions initiated drag-drop action, when the left mouse button is released after 1 second the auto click function clicks the left mouse button. This is a problem because when selecting text, it auto-clicks the left button 1 second after selecting the text making the text un-selected. When releasing the left mouse button auto-click should ignore the click right after the left mouse button was released if the mouse cursor hasn't moved for more than 10 pixels.
    - test funcitons (autoclick and keyaction) after locking screen and hybernating. seems that all stops working. restarting threads does not help. only restarting application seems to work.
    - Update readme.md file with current application state when main functionality is ready.