Analyzing  existant files (.zip attached) write files below in python language and let me download them in .zip format
- File_1: AppLogging.py
- include in this zip file any file that needs to be modified because of instructions provided below.
- do not modify any file that is not needed to be modified. Only modify code files that need to be updated because of logic described below
- on the output zip file include only the .py files that were modified. include the full code for every file that was modified.
- do not update or modify auxiliary files like .md files (README.md). only modify code files for the aplication functionality.

AppLoggin.py File Description:
    - in python code write a AppLogging.py file that exposes logging funcitons for all other python modules that will be able to use them. 
    - Log file will be written in standard .csv format and one new log file is created every day. Logfile name should be of format: yyyy-mm-dd_appLog.csv.
    - the log will contain date/time as timestamp, from what module the log came, the log level(  DEBUG,  INFO,  WARNING,  ERROR,  CRITICAL) and the message.
    - Implement a basic queuing system so that when logs arrive at the same time they wait to be written on the log file. use best judgment to define queue size and processing type.
    - log cleanup: every time app is started, check if there are logs older than "DaysToKeepLog" on the config.ini file. if there are files older than this amount of days, delete them.    

Graphical Interface:
    - modify graphical interface to include a "General" tab in front of all other tabs.
    - this tab will have a section for the Log configurations (one filed that has the path for the application log file, and a second field with days to keep the log)
    - by default, log file is saved on the same folder where the .exe application file is.
    - if .ini file does not exist or does not contain a [General] section with the parameter "logfilePath" or "DaysToKeepLog", write it to the config.ini file. if the path is changed on the General tab of the graphical interface, the path is validated and saved to the ini file.

For any situation not clearly specified here or ambiguous descriptions, do the best configuration/implementation you think is possible considering this is a healthcare application designed to reduce RSI — (Repetitive Strain Injury) and/or tendinitis and/or MSD — Musculoskeletal Disorders
