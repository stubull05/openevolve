#!/usr/bin/env python3
"""
Force a mutation by directly calling the core functions with a mock LLM response.
"""

import sys
from pathlib import Path

# Add openevolve to path
sys.path.insert(0, str(Path(__file__).parent))

from openevolve.utils.code_utils import apply_diff, parse_full_rewrite
from openevolve.utils.diff_parser import extract_diffs_from_response

def test_force_mutation():
    """Test forcing a mutation with a mock LLM response."""
    
    # Original code from WorkingExample.js
    original_code = '''import React, { useState } from 'react';

const WorkingExample = () => {
  const [value, setValue] = useState('');
  
  // EVOLVE-BLOCK-START
  const handleChange = (e) => {
    setValue(e.target.value);
  };
  // EVOLVE-BLOCK-END
  
  return (
    <div>
      <input value={value} onChange={handleChange} />
      <p>You typed: {value}</p>
    </div>
  );
};

export default WorkingExample;'''

    # Mock LLM response with diff
    mock_diff_response = '''
<<<<<<< SEARCH
  const handleChange = (e) => {
    setValue(e.target.value);
  };
=======
  const handleChange = (e) => {
    // Improved with validation
    if (e.target.value.length <= 100) {
      setValue(e.target.value);
    }
  };
>>>>>>> REPLACE
'''

    # Mock LLM response with full rewrite
    mock_rewrite_response = f'''Here's the improved React component:

```javascript
{original_code.replace("setValue(e.target.value);", "// Improved with validation\\n    if (e.target.value.length <= 100) {\\n      setValue(e.target.value);\\n    }")}
```

This version adds input validation to prevent overly long inputs.
'''

    print("Testing diff-based mutation...")
    
    # Test diff parsing
    diffs = extract_diffs_from_response(mock_diff_response)
    print(f"Extracted {len(diffs)} diffs")
    
    if diffs:
        # Apply diff
        result_diff = apply_diff(original_code, mock_diff_response)
        
        if result_diff != original_code:
            print("✅ DIFF MUTATION SUCCESSFUL!")
            print(f"Original length: {len(original_code)}")
            print(f"Modified length: {len(result_diff)}")
            print("Changes made:")
            print(result_diff[result_diff.find("handleChange"):result_diff.find("};", result_diff.find("handleChange")) + 2])
        else:
            print("❌ Diff mutation failed - no changes")
    
    print("\nTesting full rewrite mutation...")
    
    # Test full rewrite
    result_rewrite = parse_full_rewrite(mock_rewrite_response, "javascript")
    
    if result_rewrite and result_rewrite != original_code:
        print("✅ FULL REWRITE MUTATION SUCCESSFUL!")
        print(f"Original length: {len(original_code)}")
        print(f"Modified length: {len(result_rewrite)}")
        print("Rewrite contains validation:", "validation" in result_rewrite.lower())
    else:
        print("❌ Full rewrite mutation failed")
    
    # Write the mutated version to test file
    test_file = Path("C:/Source/GIT/Rysky/desktop/src/WorkingExample.js")
    if test_file.exists():
        print(f"\nApplying mutation to {test_file}...")
        
        # Use the diff result if available, otherwise use rewrite
        final_code = result_diff if result_diff != original_code else result_rewrite
        
        if final_code and final_code != original_code:
            # Backup original
            backup_file = test_file.with_suffix('.js.backup')
            backup_file.write_text(test_file.read_text())
            
            # Write mutated version
            test_file.write_text(final_code)
            
            print(f"✅ File mutated! Backup saved as {backup_file.name}")
            print("The file now contains improved code with validation.")
        else:
            print("❌ No valid mutation to apply")
    else:
        print(f"❌ Test file not found: {test_file}")

if __name__ == "__main__":
    test_force_mutation()