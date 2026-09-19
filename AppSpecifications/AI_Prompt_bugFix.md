Modify Python application code attached as a project.
use as few AI resources as possible.
don't write text explaining the code. while it is being written.
priority is to generate the code as per requirements below.

====================
Requirements:
- When Checkbox with text "Active" named "Enable Keyboard Actions" in tab "Keyboard Actions" is pressed, it correctly removes the exclusive hook bound to the app of all function keys (F6 through F10). however, when clicked again to re-create the hooks, it re-creates just the hooks for F7 through F6. make it reset the F6 hook as well.
    - Make sure that when this checkbox gets checked, all hooks are removed and completely new ones on a operating system level are re-created from scratch. Do the exact same when the button "Reset Key Bindings" is pressed. If this button is pressed, besides creating completely new handles for F6 through F10, check the "Enable Keyboard Actuions" checkbox if it is un-checked.
    - F6 hotkey box is grayed out. Make it editable again.

======================
On every modification also:
- Inside file "GraphicalInterface.py" update the variable "APP_VERSION" so that the Major and minor number stay the same but the patch number is increased by 1. (1.0.7 to 1.0.8)
- also on create file "\src\changelog.md" if not existant. and on the top of the file (to maintain new changes on top) write the new version number and add a description on what was changed (do a summary only and don't be too technical).