## Task Overview
Analyze the existing project files (provided as a `.zip`). Apply the required modifications described in the **“Instructions”** section to the Python code.
Be as efficient as possible writing code to use as few AI resources as possible
After completing the changes, generate a new `.zip` file containing the updated code.

---

## Output Requirements
- The final deliverable must be a `.zip` file.
- do not write steps being done or explanations. just give me the final `.zip` deliverable.
- after the final .zip file is delivered, if there still are resources write a summary of what was changed.
- This `.zip` must include **only the Python (`.py`) files that were modified**.
- Each included file must contain its **full updated code**, not partial snippets.

---

## General Rules

### 1. Modify Only What Is Necessary
- Do not change files unless required by the instructions.
- Do not refactor unrelated code.

### 2. No New Files
- Do not create new files.
- Do not generate documentation files or auxiliary files. Only comment code in-line where needed.

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
- Do avoid bugs and if a bug is found try to correct it. If instructions are unclear or would introduce a bug on the application, stop the code and .zip file generation and warn me about the situation.
- Consider that this is a **healthcare-focused application** aimed at reducing:
  - Repetitive Strain Injury (RSI)
  - Tendinitis
  - Musculoskeletal Disorders (MSD)

---

## Instructions
    
==========================================
Specifications:

Correctionos on the Main Graphical interface "Rest Reminder" tab:
- change code on "RestReminder.py" so that the variable that controls timestamps "Mouse Interaction" and "Keyboard interaction" is never reset". the value is just updated whenever there is any interaction.
- Screen adjustments: 
  - replace the "Activated" button by a toggle checkbox named "Active". maintain functionality disabling this functionality (thread) if un-checked and enabling it if checked.
  - the "work limit (minutes)" should say "Minutes before break:". the text below the input is ok.  
  - after the "Minutes before break" field should be a field named "Rest minutes" that allows changing filed from 2 to 7 minutes. this is initially set to imprted variable "rest_time_seconds" from config.ini.
  - next, "postpone duration" is ok. field description should say: "Delay before re-showing pause screen after delay button is clicked (2-15)".
  - and last text field input is currently named "Idle Reset" and its title and field description are ok.

  - Session timers:
    - all timers should be updated live every 2 seconds even if screen is currently open.
    - General Interaction: Value is ok. just update it every 2 seconds. and if it is bigger than "Work Limit" minutes, change color to blue. once this timer is reset by any action, it returns to its original blue color
    - Mouse Interaction should read "Last Mouse Interaction time: " and the field should contain the timestamp in a human readable format
    - Keyboard Interaction should read "Last Keyboard Interaction time: " and the field should contain the timestamp in a human readable format
    - a field should also contain a human readable timestamp and contain the value of variable "usage_start_timestamp". this field should be updated whenever a new value is set to this variable        
==========================================
