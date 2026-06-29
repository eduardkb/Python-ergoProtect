Modify Python application code attached as app.zip.
use as few AI resources as possible.
don't write text explaining the code. while it is being written.
priority is to generate the code as per requirements below.
Always zip only the files that needed to be modified (keeping the folder structure) to the results.zip file and let me download it.

====================
Requirements:
- I think the application is still loosing the function keys (F6 through F10) from time to time and taking way over 5 minutes to recover them. Make a better logic to recover them as fast as possible.
- on Keyboard Actions tab, there is a checkbox called "Active". Make a logic so that besides activating and deactivating the F7 thourgh F10 keys it also forces re-registering all function keys including the F6 key. Do the same for the toggle on the auto click tab. So, if either of these two toggles are changed to "checked" state, they will re-register all function keys (default f6 through F10)

======================
On every modification also:
- Inside file "GraphicalInterface.py" update the variable "APP_VERSION" so that the Major and minor number stay the same but the patch number is increased by 1. (1.0.7 to 1.0.8)
- also on create file "\src\changelog.md" if not existant. and on the top of the file (to maintain new changes on top) write the new version number and add a description on what was changed (do a summary only and don't be too technical).