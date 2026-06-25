Modify Python application code attached as app.zip.
use as few AI resources as possible.
don't write text explaining the code. while it is being written.
priority is to generate the code as per requirements below.
Always zip only the files that needed to be modified (keeping the folder structure) to the results.zip file and let me download it.

====================
Requirements:
- recovery time of the function keys (default f6 through f10 ) when mapping is lost is too long. it is way longer than 10 seconds.
- the mapping is usually lost after computer comes back from hybernation or sleep.
- make a new safe and more reliable solution so that these function keys are recovered within 30 seconds. 
- make sure to do logging (as warning level) any time this key mappings is lost and recovered

======================
On every modification also:
- Inside file "GraphicalInterface.py" update the variable "APP_VERSION" so that the Major and minor number stay the same but the patch number is increased by 1. (1.0.7 to 1.0.8)
- also on create file "\src\changelog.md" if not existant. and on the top of the file (to maintain new changes on top) write the new version number and add a description on what was changed (do a summary only and don't be too technical).