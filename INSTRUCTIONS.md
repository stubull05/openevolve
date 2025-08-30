# Instructions for Applying the OpenEvolve Patch

This patch set contains two items:

1. **openevolve/openevolve/utils/patch_sanitizer.py**

   A complete replacement for the `patch_sanitizer.py` module.  It improves
   handling of model‑generated diffs by stripping code fences and Git
   headers, repairing malformed hunk lines, and coercing stray lines
   inside hunks to proper context lines.  File names referenced in
   diff headers are retargeted based on environment variables.  The
   sanitizer determines the target file as follows:

   1. If you set `OE_TARGET_FILE` in your environment, that file will be
      used as the target.
   2. Otherwise, if you set `OE_ALLOWED_FILES` to a comma‑separated list
      of permitted files, the **first** file in that list becomes the
      default target.
   3. If neither variable is set, the sanitizer falls back to `api.py`
      for compatibility with older setups.

   You can also override the allow‑list via `OE_ALLOWED_FILES`; if not
   provided, it defaults to the target file plus a conventional
   secondary module (`data_layer.py`).  These variables let you evolve
   JavaScript, TypeScript or other files without hard‑coding `api.py`.

   The sanitizer also prints a short preview of the cleaned diff for
   debugging.  Drop this file into your repository at the path shown.

2. **Manual change for openevolve/openevolve/process_parallel.py**

   In `process_parallel.py`, the `_run_iteration_worker` function calls
   `extract_raw_patch(raw)` but then discards the sanitized diff and
   continues using the original `llm_response`.  To fix the issue, find
   the following code (around line 190 in the original file):

   ```python
       raw = llm_response
       try:
           resp_text = extract_raw_patch(raw)
       except Exception:
           llm_response = raw
       # ... later, diff_blocks = extract_diffs(llm_response)
   ```

   Replace it with:

   ```python
       raw = llm_response
       try:
           sanitized = extract_raw_patch(raw)
           # Use the sanitized diff if present, otherwise fall back to raw
           if sanitized:
               llm_response = sanitized
           else:
               llm_response = raw
       except Exception:
           # If sanitization fails, fall back to the raw response
           llm_response = raw
       # Now extract diffs from the (potentially sanitized) response
       diff_blocks = extract_diffs(llm_response)
       if not diff_blocks:
           return SerializableResult(error="No valid diffs found in response", iteration=iteration)
       child_code = apply_diff(parent.code, llm_response)
   ```

   This change ensures that the sanitized diff is used for diff extraction and
   application, preventing the "No valid diffs found" error when the
   sanitizer successfully produces a patch.

3. (Optional) **Restore file safety**

   Occasionally a failed patch attempt can cause the runtime to write a
   temporary filename (for example `/tmp/tmpXXXXX.ts`) into the file being
   evolved, resulting in a `SyntaxError` on the next import.  To guard
   against this for **any type of source file**, add a simple check in
   your entrypoint or runner that backs up **whatever file is being
   evolved**.  This check relies on the environment variables
   ``OE_TARGET_FILE`` and/or ``OE_ALLOWED_FILES`` to determine the
   current file.  You should set ``OE_TARGET_FILE`` before running
   OpenEvolve to the name of the file under evolution (for example
   ``main.js`` or ``main.ts``).  If ``OE_TARGET_FILE`` is not set
   but ``OE_ALLOWED_FILES`` is, the first entry in the allow‑list will
   be used as the target.  Avoid leaving these unset when evolving
   non‑Python files.

   ```python
   import os, shutil

   # The file currently under evolution must be provided via the
   # OE_TARGET_FILE environment variable.  There is no default hard‑coded
   # file name – if OE_TARGET_FILE is not set, this will raise KeyError.
   target_file = os.environ['OE_TARGET_FILE']
   backup = f"{target_file}.bak"

   # Make a one‑time backup of the target file.  This ensures that we
   # can restore the original contents if a patch attempt goes wrong.
   if os.path.exists(target_file) and not os.path.exists(backup):
       shutil.copy(target_file, backup)

   # Read the first line of the target file.  If it looks like a
   # temporary path (starts with '/tmp/tmp' and ends with the same
   # extension as the target), restore from the backup.
   if os.path.exists(target_file):
       with open(target_file, 'r', encoding='utf-8', errors='ignore') as f:
           first_line = f.readline().strip()
       _, ext = os.path.splitext(target_file)
       if first_line.startswith('/tmp/tmp') and first_line.endswith(ext):
           shutil.copy(backup, target_file)
   ```

   This check will restore the original file if a corrupted write occurs
   for any file type (Python, JavaScript, TypeScript, etc.) as long as
   you provide the correct ``OE_TARGET_FILE`` value.

After copying the new `patch_sanitizer.py` into place and updating
`process_parallel.py`, commit the changes on a new branch and open a
pull request for review.
