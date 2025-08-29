# Instructions for Applying the OpenEvolve Patch

This patch set contains two items:

1. **openevolve/openevolve/utils/patch_sanitizer.py**

   A complete replacement for the `patch_sanitizer.py` module.  It improves
   handling of model‑generated diffs by stripping code fences and git
   headers, repairing malformed hunk lines, retargeting filenames to
   `api.py`, and coercing stray lines inside hunks to proper context
   lines.  The sanitizer also enforces an allow‑list and prints a short
   preview of the cleaned diff for debugging.  Drop this file into your
   repository at the path shown.

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

   Sometimes a failed diff causes a temporary filename (e.g. `/tmp/tmp…py`)
   to be written into `api.py`, causing a `SyntaxError` when tests import
   the file.  To prevent this, you can add a simple check at the start
   of your evolution entrypoint:

   ```python
   # Keep a clean backup
   if os.path.exists('api.py') and not os.path.exists('api.py.bak'):
       shutil.copy('api.py', 'api.py.bak')
   # If the first line of api.py looks like a temp file path, restore
   with open('api.py', 'r') as f:
       first = f.readline().strip()
   if first.startswith('/tmp/tmp') and first.endswith('.py'):
       shutil.copy('api.py.bak', 'api.py')
   ```

   This guard restores the original file if a corrupted write occurs.

After copying the new `patch_sanitizer.py` into place and updating
`process_parallel.py`, commit the changes on a new branch and open a
pull request for review.
