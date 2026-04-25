## Task Overview
Analyze the existing project files (provided as a `.zip`). Apply the required modifications described in the **“Bug Fix Instructions”** section to the Python code.
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
- Do not change files unless required by the Bug Fix Instructions.
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

## Bug Fix Instructions
    
==========================================
On Module RestReminder.py
- Change all instances names of variable "continuous_work_minutes" to "continuous_work_limit_minutes" including writing it to the config.ini file.
- Change all instances names of variable "rest_time_seconds" to "pause_time_minutes" including writing it to the config.ini file. and change all logic from seconds to minutes including inside variable "_RANGES"
- Change all instances names of variable "delay_pause_minutes" to "pause_delay_minutes" including writing it to the config.ini file.
- Change all instances names of variable "reset_of_work_time_minutes" to "clear_continuous_work_minutes" including writing it to the config.ini file.

- considering variables on _RANGES after change above, do validations on the Rest Reminder tab so that user can't change the value on the text boxes out of the range (if a number is inserted out of range, a number in the range is automatically inserted after user leaves the field)
==========================================