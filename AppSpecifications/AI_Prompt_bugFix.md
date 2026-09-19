Modify Python application code attached as a project.
use as few AI resources as possible.
don't write text explaining the code. while it is being written.
priority is to generate the code as per requirements below.

====================
Requirements:
 - make a logging overhaul. the app reads parameters from a .ini file in the root directory where the app is located. make it read a parameter called log_level inside [GENERAL]. The default (if nothing present, is 1). 1 = only information. 2 = information + waring. 3 = all (info, warn, error). plus insert logging where needed and where appropriate if missing. Give a special attention to error logs writing them whenever anything happens that could indicate a problem with the app. As it is done already with other parameters, write this parameter as well to the .ini file on app startup if the parameter is not already there.
    - make sure the log file location is always the same (read from the .ini file). if the .ini file "logfilepath" parameter inside [GENERAL] does not exist, write it as well as being "<Current location where python files or executable is being executed>/app_logs". The log files that are older than 30 days (parameter on .ini file) are not being deleted. make sure that on app launch, it consults the correct folder and then searches for old files inside this correct folder.
======================
On every modification also:
- Inside file "GraphicalInterface.py" update the variable "APP_VERSION" so that the Major and minor number stay the same but the patch number is increased by 1. (1.0.7 to 1.0.8)
- also on create file "\src\changelog.md" if not existant. and on the top of the file (to maintain new changes on top) write the new version number and add a description on what was changed (do a summary only and don't be too technical).