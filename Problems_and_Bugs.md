# Next ToDo's

- Problems                
    - Although when the app is initialized the .ini file contains parameter "log_level=3", the log level reported by the log itself is 1. I presume this is the log level used by the app. When the app is initialized, make it read this paramter (log_level inside [Global]) and make the app consider that as the log level. Also make sure the app on initialization does not write this parameter to 1 if the parameter already exists in the file. It should be written only if it does not exist.

- Bugs:
    
- Non-Urgent Bugs
    - Update readme.md file with current application state when main functionality is ready.

Fixed:
    - "Keyboard Actinos" tab has all its options grayed out. un-do this. the options should be available and work for the user to change or disable the function if he needs/wants to.
     

