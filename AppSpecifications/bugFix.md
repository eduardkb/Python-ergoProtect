## Task Overview
Analyze the existing project files (provided as a `.zip`). Apply the required modifications described in the **“Bug Fix Instructions”** section to the Python code.
Be as efficient as possible. Write as few output lines as possible. Priority is generating the .zip output file.
If you need more than 2 tries to identify the problem, stop the reasoning to solve the problem.
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
Fix issues:
- fix 1 = every 30 seconds I get the logs below very consistently. Is the applciation expected to forcefully restart the hooks every 30 seconds? if not, fix the code. if yes, remove the  error and only leave a warning saying that these have been restarted.
2026-05-08 13:33:40.775,KeyboardActions,ERROR,EXCLUSIVE KEY BINDING LOST — No keypress heartbeat for 24.0s (threshold=20.0s) — hook appears frozen. Performing automatic hook restart.
2026-05-08 13:33:40.775,KeyboardActions,INFO,All hotkeys unregistered.
2026-05-08 13:33:40.776,KeyboardActions,INFO,Hotkey registered: F7 → _do_left_click()
2026-05-08 13:33:40.776,KeyboardActions,INFO,Hotkey registered: F8 → _do_right_click()
2026-05-08 13:33:40.776,KeyboardActions,INFO,Hotkey registered: F9 → _do_double_click()
2026-05-08 13:33:40.776,KeyboardActions,INFO,Hotkey registered: F10 → _do_drag_drop()
2026-05-08 13:33:40.776,KeyboardActions,DEBUG,Heartbeat hook registered.
2026-05-08 13:33:40.776,KeyboardActions,INFO,Keyboard hooks successfully restarted by watchdog.

- Fix 2 = In General tab, when initializing the app and no log path exists as default, the default should be the same location where the .exe file is located or where the application is being executed from. This location should have a folder named "app_logs". if it doesn't, create it. and logs should be stored inside this folder. Save this default path to the config.ini file wherever it is not present and also save new log path configuration whenever changed
==========================================