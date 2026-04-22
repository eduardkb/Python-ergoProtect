## Task Overview
Analyze the existing project files (provided as a `.zip`). Apply the required modifications described in the **“Instructions for Bug Fixes”** section to the Python code.

After completing the changes, generate a new `.zip` file containing the updated code.

---

## Output Requirements
- The final deliverable must be a `.zip` file.
- This `.zip` must include **only the Python (`.py`) files that were modified**.
- Each included file must contain its **full updated code**, not partial snippets.

---

## General Rules

### 1. Modify Only What Is Necessary
- Do not change files unless required by the bug fix instructions.
- Do not refactor unrelated code.

### 2. No New Files
- Do not create new files.
- Do not generate documentation or auxiliary files.

### 3. Exclude Non-Code Files
- Do not modify or include files such as `.md`, `README.md`, or any non-Python files.

### 4. Threading Requirement
- Each major feature or UI tab in the application must run in a **separate thread**.

### 5. Dependencies Between Files
- If a bug fix requires changes in multiple files, include all affected `.py` files in the output `.zip`.

### 6. Add Logging where needed
- where it makes sense, add logging messages using functions exported by the AppLogging.py module

### 7. Ambiguity Handling
- If any instruction is unclear or incomplete, implement the **most reasonable and robust solution**.
- Consider that this is a **healthcare-focused application** aimed at reducing:
  - Repetitive Strain Injury (RSI)
  - Tendinitis
  - Musculoskeletal Disorders (MSD)

---

## Bug Fix Instructions
    
==========================================
- using the existing appLogging.py module exported functions write logging code for all python files where it makes sense
- log all exceptions and errors. log other messages where relevant
- for the main functions (tabs on Graphical interface) if a module could not be loaded specifically log the reason. “module file not found” and "module exists but dependency failed” should be threated as different errors
- problems while using pyinstaller to generate .exe file if possible should be clearly written on screen during generation process
==========================================