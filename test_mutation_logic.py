#!/usr/bin/env python3
"""
Test the core mutation logic without requiring LLM calls.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

def test_diff_parsing():
    """Test if diff parsing works correctly."""
    from openevolve.utils.diff_parser import extract_diffs_from_response
    
    # Test response that should work
    test_response = """
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
    
    diffs = extract_diffs_from_response(test_response)
    print(f"Diff parsing test: {len(diffs)} diffs found")
    
    if diffs:
        search, replace = diffs[0]
        print(f"  Search: {repr(search)}")
        print(f"  Replace: {repr(replace)}")
        return True
    return False

def test_diff_application():
    """Test if diffs can be applied to code."""
    from openevolve.utils.code_utils import apply_diff
    
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

    try:
        result = apply_diff(original_code, diff_text)
        
        if result and result != original_code:
            print("Diff application test: SUCCESS")
            print(f"  Original length: {len(original_code)}")
            print(f"  Result length: {len(result)}")
            print(f"  Changed: {'prevCount =>' in result}")
            return True
        else:
            print("Diff application test: FAILED - no change")
            return False
    except Exception as e:
        print(f"Diff application test: FAILED - {e}")
        return False

def test_full_rewrite_parsing():
    """Test if full rewrite parsing works."""
    from openevolve.utils.code_utils import parse_full_rewrite
    
    llm_response = """Here's the improved React component:

```javascript
import React, { useState } from 'react';

const TestComponent = () => {
  const [count, setCount] = useState(0);
  
  // EVOLVE-BLOCK-START
  const handleIncrement = () => {
    setCount(prevCount => prevCount + 1);
  };
  // EVOLVE-BLOCK-END
  
  return <div>{count}</div>;
};

export default TestComponent;
```

This version uses functional state updates which is better practice.
"""

    result = parse_full_rewrite(llm_response, "javascript")
    
    if result:
        print("Full rewrite parsing test: SUCCESS")
        print(f"  Parsed length: {len(result)}")
        print(f"  Contains improvement: {'prevCount =>' in result}")
        return True
    else:
        print("Full rewrite parsing test: FAILED")
        return False

def test_evaluator():
    """Test if the evaluator works correctly."""
    sys.path.insert(0, str(Path(__file__).parent))
    
    try:
        from rysky_evaluator import evaluate
        
        test_code = """import React, { useState } from 'react';

const TestComponent = () => {
  const [count, setCount] = useState(0);
  
  // EVOLVE-BLOCK-START
  const handleIncrement = () => {
    setCount(count + 1);
  };
  // EVOLVE-BLOCK-END
  
  return <div>{count}</div>;
};

export default TestComponent;"""

        metrics = evaluate(test_code, "test.js")
        
        print("Evaluator test:")
        print(f"  Metrics returned: {list(metrics.keys())}")
        print(f"  Combined score: {metrics.get('combined_score', 'MISSING')}")
        
        required_metrics = ["syntax_score", "react_score", "complexity_score", "error_handling_score"]
        has_all_metrics = all(metric in metrics for metric in required_metrics)
        
        print(f"  Has all required metrics: {has_all_metrics}")
        return has_all_metrics and metrics.get('combined_score', 0) > 0
        
    except Exception as e:
        print(f"Evaluator test: FAILED - {e}")
        return False

def test_file_mutation_simulation():
    """Simulate the complete mutation process."""
    
    # Create test file
    test_file = Path("test_mutation_sim.js")
    original_code = """import React, { useState } from 'react';

const TestComponent = () => {
  const [count, setCount] = useState(0);
  
  // EVOLVE-BLOCK-START
  const handleIncrement = () => {
    setCount(count + 1);
  };
  // EVOLVE-BLOCK-END
  
  return <div>{count}</div>;
};

export default TestComponent;"""

    test_file.write_text(original_code)
    
    try:
        # Simulate what OpenEvolve should do:
        # 1. Read file
        current_code = test_file.read_text()
        
        # 2. Generate improvement (simulate LLM response)
        simulated_llm_response = """```javascript
import React, { useState } from 'react';

const TestComponent = () => {
  const [count, setCount] = useState(0);
  
  // EVOLVE-BLOCK-START
  const handleIncrement = () => {
    setCount(prevCount => prevCount + 1);
  };
  // EVOLVE-BLOCK-END
  
  return <div>{count}</div>;
};

export default TestComponent;
```"""
        
        # 3. Parse the response
        from openevolve.utils.code_utils import parse_full_rewrite
        improved_code = parse_full_rewrite(simulated_llm_response, "javascript")
        
        # 4. Write back to file
        if improved_code and improved_code != current_code:
            test_file.write_text(improved_code)
            
            # 5. Verify mutation
            final_code = test_file.read_text()
            is_mutated = final_code != original_code
            
            print("File mutation simulation:")
            print(f"  Original length: {len(original_code)}")
            print(f"  Final length: {len(final_code)}")
            print(f"  File was mutated: {is_mutated}")
            print(f"  Contains improvement: {'prevCount =>' in final_code}")
            
            return is_mutated
        else:
            print("File mutation simulation: FAILED - no valid improvement generated")
            return False
            
    except Exception as e:
        print(f"File mutation simulation: FAILED - {e}")
        return False
    finally:
        if test_file.exists():
            test_file.unlink()

def main():
    print("Testing OpenEvolve mutation logic...")
    print("="*50)
    
    tests = [
        ("Diff parsing", test_diff_parsing),
        ("Diff application", test_diff_application),
        ("Full rewrite parsing", test_full_rewrite_parsing),
        ("Evaluator", test_evaluator),
        ("File mutation simulation", test_file_mutation_simulation),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"  ERROR: {e}")
            results[test_name] = False
    
    print("\n" + "="*50)
    print("SUMMARY:")
    
    all_passed = True
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test_name}: {status}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\nAll core mutation logic tests passed!")
        print("The issue is likely in the LLM communication or prompt formatting.")
    else:
        print("\nSome core logic tests failed - these need to be fixed first.")

if __name__ == "__main__":
    main()