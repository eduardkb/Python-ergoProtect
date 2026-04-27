# Next ToDo's
- Problems
    

- Bugs:
    - F6 (autoclick activte/deactivte) is not exclusively mapping to the ergoProtect application. it is doing actions on other applications while it should be captured exclusively for this application's functionality.
    - after long inactive time, the General Interaction timer does not reset to 0. it starts from when it was last reset. after long inactivity, make this timer reset again.
- Non-Urgent Bugs
    - Double click on ergoProtect icon on tray should show the app's graphical interface. double clicking on tray icon now does nothing.        
    - test funcitons (autoclick and keyaction) after locking screen and hybernating. seems that all stops working. restarting threads does not help. only restarting application seems to work.
    - don't let two instance of the applciation get started. if one is running, display a message and stop loading.
    - check if all modules load while executing the applciation through the .exe file
    - Update readme.md file with current application state when main functionality is ready.