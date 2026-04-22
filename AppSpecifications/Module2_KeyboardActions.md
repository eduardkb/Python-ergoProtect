## Task Overview
Analyze the existing project files (provided as a `.zip`). Apply the required modifications described in the **“Instructions”** section to the Python code.

After completing the changes, generate a new `.zip` file containing the updated code.

---

## Output Requirements
- The final deliverable must be a `.zip` file.
- This `.zip` must include **only the Python (`.py`) files that were modified**.
- Each included file must contain its **full updated code**, not partial snippets.

---

## General Rules

### 1. Modify Only What Is Necessary
- Do not change files unless required by the instructions.
- Do not refactor unrelated code.

### 2. No New Files
- Do not create new files.
- Do not generate documentation or auxiliary files.

### 3. Exclude Non-Code Files
- Do not modify or include files such as `.md`, `README.md`, or any non-Python files.

### 4. Threading Requirement
- Each major feature or UI tab in the application must run in a **separate thread**.

### 5. Dependencies Between Files
- If instructions requires changes in multiple files, include all affected `.py` files in the output `.zip`.

### 6. Add Logging where needed
- where it makes sense, add logging messages using functions exported by the AppLogging.py module

### 7. Ambiguity Handling
- If any instruction is unclear or incomplete, implement the **most reasonable and robust solution**.
- Consider that this is a **healthcare-focused application** aimed at reducing:
  - Repetitive Strain Injury (RSI)
  - Tendinitis
  - Musculoskeletal Disorders (MSD)

---

## Instructions
    
==========================================
Specifications:
KeyboardActions.py
    - logging
        * any error, exception or important information this module generates must be logged using the AppLogging.py module exposed functions.
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
        
==========================================