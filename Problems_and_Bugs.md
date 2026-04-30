# Next ToDo's
- Problems
    

- Bugs:
    - Autoclick sometimes stops working (and ressetting the autoclick thread does not restore it to work). On log, I see lots of messages "2026-04-30 09:10:25.228,AutoClick,DEBUG,"AutoClick suppressed — awaiting first move, drag, or cooldown." when it stops working. It is possible that after some Keyboard Actions module interactions, the auto click module does not identify mouse movement anymore.
- Non-Urgent Bugs
    - disable autoclick debug log. it is too verbose
    - F6 (autoclick activte/deactivte) is not exclusively mapping to the ergoProtect application. it is doing actions on other applications while it should be captured exclusively for this application's functionality.
    - test funcitons (autoclick and keyaction) after locking screen and hybernating. seems that all stops working. restarting threads does not help. only restarting application seems to work.
    - Update readme.md file with current application state when main functionality is ready.