#!/usr/bin/env python3
"""
Debug why diff application is failing.
"""

def debug_diff_application():
    """Debug the diff application process step by step."""
    from openevolve.utils.code_utils import apply_diff
    from openevolve.utils.diff_parser import extract_diffs_from_response
    
    original_code = """import React, { useState } from 'react';

const TestComponent = () => {
  const [count, setCount] = useState(0);
  
  // EVOLVE-BLOCK-START
  const handleIncrement = () => {
    setCount(count + 1);
  };
  // EVOLVE-BLOCK-END
  
  return <div>{count}</div>;
};"""

    diff_text = """
<<<<<<< SEARCH
  const handleIncrement = () => {
    setCount(count + 1);
  };
=======
  const handleIncrement = () => {
    setCount(prevCount => prevCount + 1);
  };
>>>>>>> REPLACE
"""

    print("Original code:")
    print(repr(original_code))
    print("\nDiff text:")
    print(repr(diff_text))
    
    # Step 1: Extract diffs
    diffs = extract_diffs_from_response(diff_text)
    print(f"\nExtracted {len(diffs)} diffs:")
    
    for i, (search, replace) in enumerate(diffs):
        print(f"Diff {i+1}:")
        print(f"  Search: {repr(search)}")
        print(f"  Replace: {repr(replace)}")
        
        # Check if search text exists in original
        if search in original_code:
            print(f"  ✅ Search text found in original")
        else:
            print(f"  ❌ Search text NOT found in original")
            
            # Try to find similar text
            lines = original_code.split('\n')
            search_lines = search.split('\n')
            print(f"  Looking for similar lines...")
            for line in search_lines:
                line = line.strip()
                if line:
                    for orig_line in lines:
                        if line in orig_line:
                            print(f"    Found similar: {repr(orig_line)}")
    
    # Step 2: Apply diff
    try:
        result = apply_diff(original_code, diff_text)
        print(f"\nApply diff result:")
        print(f"  Success: {result is not None}")
        if result:
            print(f"  Changed: {result != original_code}")
            if result != original_code:
                print(f"  New code: {repr(result)}")
    except Exception as e:
        print(f"  Error: {e}")

if __name__ == "__main__":
    debug_diff_application()