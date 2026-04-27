# Next ToDo's
- Problems
    

- Bugs:
    - 5 second auto click stop while manual drag is triggering all the time and blocking the auto click function. ignore drag that happens for less than 500 ms.
    - moving mouse is not being considered as interaction.

    - F6 (autoclick activte/deactivte) is not exclusively mapping to the ergoProtect application. it is doing actions on other applications while it should be captured exclusively for this application's functionality.
    - after long inactive time, the General Interaction timer does not reset to 0. it starts from when it was last reset. after long inactivity, make this timer reset again.
- Non-Urgent Bugs
    - Double click on ergoProtect icon on tray should show the app's graphical interface. double clicking on tray icon now does nothing.    
    - On interface when "active" is clicked on auto click tab, it immediatelly dismarks the check. If f7 is pressed when mouse is over it, it is also immediatelly unchecked by the autoclick. so, autoclick is the probable culprit.
    - GUI active toggle not updating when F6 is pressed.    
    - 5 seconds cooldown for drag-drop effective even after left mouse button has been released
    - test funcitons (autoclick and keyaction) after locking screen and hybernating. seems that all stops working. restarting threads does not help. only restarting application seems to work.
    - don't let two instance of the applciation get started. if one is running, display a message and stop loading.
    - check if all modules load while executing the applciation through the .exe file
    - Update readme.md file with current application state when main functionality is ready.