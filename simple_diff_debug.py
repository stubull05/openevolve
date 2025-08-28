#!/usr/bin/env python3
"""
Simple diff debug without Unicode characters.
"""

def debug_diff_whitespace():
    """Debug whitespace issues in diff matching."""
    
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

    # The search text from the diff
    search_text = """  const handleIncrement = () => {
    setCount(count + 1);
  };"""

    print("Checking if search text exists in original...")
    print(f"Search text in original: {search_text in original_code}")
    
    if search_text not in original_code:
        print("\nAnalyzing whitespace differences...")
        
        # Split into lines and check each
        original_lines = original_code.split('\n')
        search_lines = search_text.split('\n')
        
        print(f"Original has {len(original_lines)} lines")
        print(f"Search has {len(search_lines)} lines")
        
        # Find the function in original
        for i, line in enumerate(original_lines):
            if 'const handleIncrement' in line:
                print(f"\nFound function at line {i}: {repr(line)}")
                
                # Show next few lines
                for j in range(3):
                    if i + j < len(original_lines):
                        orig_line = original_lines[i + j]
                        if j < len(search_lines):
                            search_line = search_lines[j]
                            match = orig_line == search_line
                            print(f"Line {i+j}: {match}")
                            print(f"  Original: {repr(orig_line)}")
                            print(f"  Search:   {repr(search_line)}")
                        else:
                            print(f"Line {i+j}: {repr(orig_line)}")
                break

def test_manual_replacement():
    """Test manual string replacement."""
    
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

    # Try exact replacement
    old_func = """  const handleIncrement = () => {
    setCount(count + 1);
  };"""
    
    new_func = """  const handleIncrement = () => {
    setCount(prevCount => prevCount + 1);
  };"""
    
    if old_func in original_code:
        result = original_code.replace(old_func, new_func)
        print("Manual replacement: SUCCESS")
        print(f"Changed: {result != original_code}")
        return True
    else:
        print("Manual replacement: FAILED - text not found")
        return False

if __name__ == "__main__":
    print("Debugging diff application...")
    print("="*40)
    
    debug_diff_whitespace()
    
    print("\n" + "="*40)
    test_manual_replacement()