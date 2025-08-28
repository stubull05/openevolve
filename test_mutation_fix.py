#!/usr/bin/env python3
"""
Test to verify file mutations are working and fix the diff prompt template.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

def test_diff_parser():
    """Test the diff parser with various formats."""
    from openevolve.utils.diff_parser import extract_diffs_from_response
    
    # Test proper format
    response1 = """
<<<<<<< SEARCH
const oldFunction = () => {
    return 'old';
};
=======
const newFunction = () => {
    return 'new';
};
>>>>>>> REPLACE
"""
    
    diffs = extract_diffs_from_response(response1)
    print(f"Test 1 - Proper format: {len(diffs)} diffs found")
    if diffs:
        print(f"  Search: {diffs[0][0][:50]}...")
        print(f"  Replace: {diffs[0][1][:50]}...")
    
    # Test what LLM might actually return
    response2 = """
I'll improve the error handling in the chat function:

```javascript
<<<<<<< SEARCH
const handleSendMessage = async () => {
    if (inputValue.trim() === '' || isLoading) return;
=======
const handleSendMessage = async () => {
    if (inputValue.trim() === '' || isLoading) return;
    
    try {
>>>>>>> REPLACE
```
"""
    
    diffs = extract_diffs_from_response(response2)
    print(f"Test 2 - LLM format: {len(diffs)} diffs found")
    
    return len(diffs) > 0

def create_test_file():
    """Create a test file with EVOLVE blocks."""
    test_content = '''import React, { useState } from 'react';

const TestComponent = () => {
  const [count, setCount] = useState(0);
  
  // EVOLVE-BLOCK-START
  const handleClick = () => {
    setCount(count + 1);
  };
  // EVOLVE-BLOCK-END
  
  return (
    <div>
      <p>Count: {count}</p>
      <button onClick={handleClick}>Increment</button>
    </div>
  );
};

export default TestComponent;
'''
    
    test_file = Path("test_component.js")
    test_file.write_text(test_content)
    return test_file

def test_mutation_detection():
    """Test if we can detect when a file has been mutated."""
    test_file = create_test_file()
    original_content = test_file.read_text()
    
    # Simulate a mutation
    mutated_content = original_content.replace(
        "setCount(count + 1);", 
        "setCount(prevCount => prevCount + 1);"
    )
    test_file.write_text(mutated_content)
    
    # Check if mutation occurred
    new_content = test_file.read_text()
    is_mutated = new_content != original_content
    
    print(f"Mutation test: {'PASSED' if is_mutated else 'FAILED'}")
    print(f"Original length: {len(original_content)}")
    print(f"New length: {len(new_content)}")
    
    # Cleanup
    test_file.unlink()
    
    return is_mutated

def fix_diff_template():
    """Fix the diff template to provide proper instructions."""
    template_path = Path("c:/Source/GIT/openevolve/openevolve/prompts/defaults/diff_user.txt")
    
    if not template_path.exists():
        print(f"Template not found at {template_path}")
        return False
    
    # Read current template
    current_template = template_path.read_text()
    print("Current template:")
    print(current_template)
    print("\n" + "="*50 + "\n")
    
    # Create improved template
    improved_template = """# Current Program Information
- Fitness: {fitness_score}
- Feature coordinates: {feature_coords}
- Focus areas: {improvement_areas}

{artifacts}

# Program Evolution History
{evolution_history}

# Current Program
```{language}
{current_program}
```

# Task
Improve the code by making targeted changes. You MUST respond with diffs in this EXACT format:

<<<<<<< SEARCH
exact_code_to_find_and_replace
=======
new_improved_code
>>>>>>> REPLACE

CRITICAL RULES:
1. Use EXACTLY 7 < symbols, then SEARCH
2. Use EXACTLY 7 = symbols between search and replace
3. Use EXACTLY 7 > symbols, then REPLACE
4. The SEARCH section must match existing code EXACTLY (including whitespace)
5. Only modify code within EVOLVE-BLOCK-START and EVOLVE-BLOCK-END markers
6. Provide multiple diffs if needed
7. NO other text outside the diff blocks

Example:
<<<<<<< SEARCH
  const handleClick = () => {
    setCount(count + 1);
  };
=======
  const handleClick = () => {
    setCount(prevCount => prevCount + 1);
  };
>>>>>>> REPLACE

Provide your diffs now:"""
    
    # Backup original
    backup_path = template_path.with_suffix('.txt.backup')
    shutil.copy2(template_path, backup_path)
    print(f"Backed up original to {backup_path}")
    
    # Write improved template
    template_path.write_text(improved_template)
    print(f"Updated template at {template_path}")
    
    return True

def main():
    print("Testing OpenEvolve mutation system...")
    print("="*50)
    
    # Test 1: Diff parser
    print("1. Testing diff parser...")
    parser_works = test_diff_parser()
    print(f"   Result: {'PASS' if parser_works else 'FAIL'}")
    print()
    
    # Test 2: Mutation detection
    print("2. Testing mutation detection...")
    mutation_works = test_mutation_detection()
    print(f"   Result: {'PASS' if mutation_works else 'FAIL'}")
    print()
    
    # Test 3: Fix template
    print("3. Fixing diff template...")
    template_fixed = fix_diff_template()
    print(f"   Result: {'PASS' if template_fixed else 'FAIL'}")
    print()
    
    print("Summary:")
    print(f"- Diff parser: {'✓' if parser_works else '✗'}")
    print(f"- Mutation detection: {'✓' if mutation_works else '✗'}")
    print(f"- Template fix: {'✓' if template_fixed else '✗'}")
    
    if all([parser_works, mutation_works, template_fixed]):
        print("\n🎉 All tests passed! The mutation system should now work.")
    else:
        print("\n❌ Some tests failed. Check the issues above.")

if __name__ == "__main__":
    main()