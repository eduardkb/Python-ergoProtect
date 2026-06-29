Modify Python application code attached as app.zip.
use as few AI resources as possible.
don't write text explaining the code. while it is being written.
priority is to generate the code as per requirements below.
Always zip only the files that needed to be modified (keeping the folder structure) to the results.zip file and let me download it.

====================
Requirements:
- Log "2026-06-29 12:24:31.012,AutoClick,DEBUG,Left button physically pressed — autoclick blocked." being printed constantgly. do not consider autoclick interaction as "left button physically pressed". plus, ignore drag lock if the drag took less than 300 millisseconds.

======================
On every modification also:
- Inside file "GraphicalInterface.py" update the variable "APP_VERSION" so that the Major and minor number stay the same but the patch number is increased by 1. (1.0.7 to 1.0.8)
- also on create file "\src\changelog.md" if not existant. and on the top of the file (to maintain new changes on top) write the new version number and add a description on what was changed (do a summary only and don't be too technical).