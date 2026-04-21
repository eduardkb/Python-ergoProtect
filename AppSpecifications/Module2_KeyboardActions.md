Analyzing  existant files (.zip attached) write files below in python language and let me download them in .zip format
- File_1: KeyboardActions.py
- File_2: AppLogging.py
- include in this zip file any file that needs to be modified because of instructions provided below.
- do not modify any file that is not needed to be modified. Only modify code files that need to be updated.
- on the output zip file include only the .py files that were modified. include the full code for every modified file.
- do not update or modify auxiliary files like .md files (README.md)


Specifications:
KeyboardActions.py
    - write config.ini file
        * the file is always located in the same folder where the .exe file is.
        * if it does not exist, create a new one when app is launched.
        * if it exist, verify if there exist a section called [keyboardActions]
        * parameteres to write (default parameters):
            + leftClickKey = F7
            + rightClickKey = F8
            + doubleClickKey = F9
            + leftDragDrop = F10
    - using file "AutoClick.py" as model, write the python code for the file "KeyboardActions.py" that does:
        * buld and populate the "Keyboard Actions" tab on the graphical interface
        * the graphical interface will have the option to change all the parameters above written to the .ini file            
        * when any of this options are changed, the config.ini file is updated with the new value
        * logic for this functionality:
            + leftClick = if the key configured on the "leftClickKey" field is pressed, the left mouse button is clicked immeditelly.
            + rightClick = if the key configured on the "rightClickKey" field is pressed, the right mouse button is clicked immeditelly. 
            + doubleClick = if the key configured on the "doubleClickKey" field is pressed, the left bouse button is double-clicked immediatelly
            + leftDragDrop = if the key configured on the "leftDragDrop" field is pressed, the left mouse button is pressed and hold to drag-and-drop the item. The left  mouse press is released on all this situations: -15 seconds elapsed; -any mouse button (even this functionality keys) are pressed; -any keyboard key is pressed; -Any application execption occours; -Application is closed by error or user interaction.    
        * any error, exception or important information this module generates must be logged using the AppLogging.py module exposed functions.

For any situation not clearly specified here or ambiguous descriptions, do the best configuration/implementation you think is possible considering this is a healthcare application designed to reduce RSI — (Repetitive Strain Injury) and/or tendinitis and/or MSD — Musculoskeletal Disorders
