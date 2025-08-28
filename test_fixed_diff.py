#!/usr/bin/env python3
"""
Test a fixed version of the diff application.
"""

def apply_diff_fixed(original_code: str, diff_text: str) -> str:
    """
    Fixed version of apply_diff that uses simple string replacement.
    """
    from openevolve.utils.diff_parser import extract_diffs_from_response
    
    result = original_code
    diff_blocks = extract_diffs_from_response(diff_text)
    
    for search_text, replace_text in diff_blocks:
        if search_text in result:
            result = result.replace(search_text, replace_text, 1)
        else:
            print(f"Warning: Search text not found: {repr(search_text[:50])}")
    
    return result

def test_fixed_diff():
    """Test the fixed diff application."""
    
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

    print("Testing fixed diff application...")
    
    result = apply_diff_fixed(original_code, diff_text)
    
    if result != original_code:
        print("SUCCESS: Code was modified")
        print(f"Original length: {len(original_code)}")
        print(f"Result length: {len(result)}")
        print(f"Contains improvement: {'prevCount =>' in result}")
        return True
    else:
        print("FAILED: Code was not modified")
        return False

if __name__ == "__main__":
    test_fixed_diff()