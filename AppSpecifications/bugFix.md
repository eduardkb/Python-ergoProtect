## Task Overview
Analyze the existing project files (provided as a `.zip`). Apply the required modifications described in the **“Bug Fix Instructions”** section to the Python code.
Be as efficient as possible writing code to use as few AI resources as possible.
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
- While typing, mouse clicks automatically when mouse hasn't been moved. Messages displayed on log when this happens: "2026-04-30 10:33:15.871,AutoClick,DEBUG,Position tracking stale for 5.0s — resetting state to recover from freeze." Mouse AutoClick should only be fired after the mouse has moved and stopped for x ammount of pixels (x = environment variable defined).
- Log "2026-04-30 10:41:26.922,AutoClick,DEBUG,Position tracking stale for 5.0s — resetting state to recover from freeze." is constantly being written on the log. even after the whole application is freshly restarted. And, AutoClick is being fired all the time even when the application is freshly restarted.
==========================================