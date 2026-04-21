Analyzing  existant files (.zip attached) make changes below to python code.
As a result let me download a new zip file with the full code on changed files. 
==========================================
Instructions for bug fixes:
    - config.Ini file should never be updated concurrently. Make each modue write it in a logical sequence. and implemnt a failsafe (queue to write or some good solution)
    - if ergoProtect icon on tray is double clicked, it should show the app's graphical interface
    - The mamin graphical interface is not showing any icon. Make it show the same icon that is displayed correclty already on the tray.
    - Applications like MS Excel and VS Code and others are still doing actions on "keyboard press" keyboard shortcuts that belong to their own app. On all applications take over the application specific action and do only the action that should be done by the ergoProtect Application.
    
==========================================
General instructions:
    - include in this zip file any file that needs to be modified because of instructions for bug fixes.
    - do not modify any file that is not needed to be modified. Only modify code files that need to be updated and include only those files on the result_output.zip file.
    - on the output zip file include only the .py files that were modified. include the full code for every modified file.
    - do not update or modify auxiliary files like .md files (README.md) or any other files.

For any situation not clearly specified here or ambiguous descriptions, do the best configuration/implementation you think is possible considering this is a healthcare application designed to reduce RSI — (Repetitive Strain Injury) and/or tendinitis and/or MSD — Musculoskeletal Disorders
