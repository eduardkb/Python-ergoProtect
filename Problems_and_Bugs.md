# Next ToDo's
- Problems
    

- Bugs:
    
- Non-Urgent Bugs
    - Autoclick is being supressed whenever a drag-drop action is initiated for 10 secoonds. This was done so that autoclick does not cancel the manual or even KeyboadActions started drag-drop action. is there a better solution for this? because if I initiate a manual drag-drop (which can vary in time taken) I have to wait for 10 seconds to elapse before the auto-click starts working again. is there a better solutino for that "issue"?
    - disable autoclick debug log. it is too verbose
    - F6 (autoclick activte/deactivte) is not exclusively mapping to the ergoProtect application. it is doing actions on other applications while it should be captured exclusively for this application's functionality.
    - test funcitons (autoclick and keyaction) after locking screen and hybernating. seems that all stops working. restarting threads does not help. only restarting application seems to work.
    - Update readme.md file with current application state when main functionality is ready.