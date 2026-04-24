# Next ToDo's
- Problems
    

- Bugs:
    - f6 (autoclick activte/deactivte) is not exclusively mapping to the ergoProtect application. it is doing actions on other applications while it should be captured exclusively for this application's functionality.
    - 5 second auto click stop while manual drag is triggering all the time and blocking the auto click function. ignore drag that happens for less than 500 ms.
    - Using available log functions exported by the module AppLogging.py, implement logs on all modules (including main.py, GraphicalInterface.py and ConfigManager.py) that currently do not log exceptions or errors or warings being logged. Do write logs where you think they are necessary and/or helpful.
    - moving mouse is not being considered as interaction.
    - rest_time_seconds = 5 (range = 60 to 300) = CHANGE TO MINUTES TO MAKE A STANDARD
    - after long inactive time, the General Interaction timer does not reset to 0. it starts from when it was last reset. after long inactivity, make this timer reset again.
- Non-Urgent Bugs
    - Double click on ergoProtect icon on tray should show the app's graphical interface. double clicking on tray icon now does nothing.    
    - On interface when "active" is clicked on auto click tab, it immediatelly dismarks the check. If f7 is pressed when mouse is over it, it is also immediatelly unchecked by the autoclick. so, autoclick is the probable culprit.
    - GUI active toggle not updating when F6 is pressed.    
    - 5 seconds cooldown for drag-drop effective even after left mouse button has been released
    - test funcitons (autoclick and keyaction) after locking screen and hybernating. seems that all stops working. restarting threads does not help. only restarting application seems to work.

- Reminders:
    - Update readme.md file with current application state when main functionality is ready.