Modify Python application code attached as a project.
use as few AI resources as possible.
don't write text explaining the code. while it is being written.
priority is to generate the code as per requirements below.

====================
Requirements:
- Make "Reset Key Bindings" button actually call UnhookWindowsHookEx and reinstall a fresh SetWindowsHookExW  hook from scratch (bypassing the keyboard library's internal singleton, or forcing it to re-create its _listener), instead of only clearing Python-side handler lists. Make the app create completely new hooks for the function keys (F6 through F10) and cleanup old hooks if needed.  When user un-checks and checks the "Enable Keyboard Actions" checkbox again, it should also call the same function the button above does besides doint what it is normally already doing. 
- Logging: using the logging engine already coded, implement verbose logging of all important events.

======================
On every modification also:
- Inside file "GraphicalInterface.py" update the variable "APP_VERSION" so that the Major and minor number stay the same but the patch number is increased by 1. (1.0.7 to 1.0.8)
- also on create file "\src\changelog.md" if not existant. and on the top of the file (to maintain new changes on top) write the new version number and add a description on what was changed (do a summary only and don't be too technical).