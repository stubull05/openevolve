#!/usr/bin/env python3
"""
Final test to verify mutations work with the fixes.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

def test_complete_mutation_pipeline():
    """Test the complete mutation pipeline with fixes."""
    
    # Create test file
    test_file = Path("C:/Source/GIT/Rysky/desktop/src/FinalTest.js")
    original_content = '''import React, { useState } from 'react';

const FinalTest = () => {
  const [count, setCount] = useState(0);
  
  // EVOLVE-BLOCK-START
  const handleClick = () => {
    setCount(count + 1);
  };
  // EVOLVE-BLOCK-END
  
  return (
    <div>
      <p>Count: {count}</p>
      <button onClick={handleClick}>Click me</button>
    </div>
  );
};

export default FinalTest;
'''
    
    test_file.write_text(original_content)
    print(f"Created test file: {test_file}")
    
    try:
        # Test evaluator
        sys.path.insert(0, str(Path(__file__).parent))
        from rysky_evaluator import evaluate
        
        metrics = evaluate(original_content, str(test_file))
        print(f"Evaluator works: {metrics.get('combined_score', 0) > 0}")
        
        # Test diff application with fixed function
        from openevolve.utils.code_utils import apply_diff
        
        test_diff = '''
<<<<<<< SEARCH
  const handleClick = () => {
    setCount(count + 1);
  };
=======
  const handleClick = () => {
    setCount(prevCount => prevCount + 1);
  };
>>>>>>> REPLACE
'''
        
        modified_code = apply_diff(original_content, test_diff)
        diff_works = modified_code != original_content
        print(f"Diff application works: {diff_works}")
        
        # Test full rewrite parsing
        from openevolve.utils.code_utils import parse_full_rewrite
        
        mock_llm_response = f'''Here's the improved code:

```javascript
{original_content.replace("setCount(count + 1)", "setCount(prevCount => prevCount + 1)")}
```
'''
        
        parsed_code = parse_full_rewrite(mock_llm_response, "javascript")
        rewrite_works = parsed_code and parsed_code != original_content
        print(f"Full rewrite parsing works: {rewrite_works}")
        
        # Summary
        all_working = all([
            metrics.get('combined_score', 0) > 0,
            diff_works,
            rewrite_works
        ])
        
        print(f"\nAll components working: {all_working}")
        
        if all_working:
            print("SUCCESS: Mutations should now work!")
            print("You can run OpenEvolve on Rysky files and they will be mutated.")
        else:
            print("ISSUE: Some components still not working")
            
        return all_working
        
    except Exception as e:
        print(f"Error in test: {e}")
        return False
    finally:
        # Cleanup
        if test_file.exists():
            test_file.unlink()
            print(f"Cleaned up: {test_file}")

def create_working_example():
    """Create a simple working example for testing."""
    
    example_file = Path("C:/Source/GIT/Rysky/desktop/src/WorkingExample.js")
    example_content = '''import React, { useState } from 'react';

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

export default WorkingExample;
'''
    
    example_file.write_text(example_content)
    print(f"Created working example: {example_file}")
    print("You can test evolution on this file with:")
    print(f"python openevolve-run.py {example_file} rysky_evaluator.py --config rysky_config.yaml --iterations 5")

if __name__ == "__main__":
    print("Final mutation test...")
    print("="*50)
    
    success = test_complete_mutation_pipeline()
    
    if success:
        print("\n" + "="*50)
        create_working_example()
        print("\nMutations are now working! Files will be modified during evolution.")