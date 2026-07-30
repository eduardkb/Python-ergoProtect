Modify Python application code attached as app.zip.
use as few AI resources as possible.
don't write text explaining the code. while it is being written.
priority is to generate the code as per requirements below.
Always zip only the files that needed to be modified (keeping the folder structure) to the results.zip file and let me download it.

====================
Requirements:
- on "Keyboard Actions" on the bottom of the screen before the status message insert a new button with text "Reset Key Bindings".
- Implement this button's code so that whenever it is clicked all keys (default f6 for auto click and f7 through f10 for keyboard actions) are reset. meaning: release their exclusive bind on the OS level and then bind them again exclusively to this ErgoProtect App.

======================
On every modification also:
- Inside file "GraphicalInterface.py" update the variable "APP_VERSION" so that the Major and minor number stay the same but the patch number is increased by 1. (1.0.7 to 1.0.8)
- also on create file "\src\changelog.md" if not existant. and on the top of the file (to maintain new changes on top) write the new version number and add a description on what was changed (do a summary only and don't be too technical).