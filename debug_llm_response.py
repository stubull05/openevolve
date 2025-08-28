#!/usr/bin/env python3
"""
Debug script to see what the LLM is actually returning.
"""

import asyncio
import os
from pathlib import Path
from openevolve.llm.ensemble import LLMEnsemble
from openevolve.config import load_config

async def test_llm_response():
    """Test what the LLM actually returns for a simple prompt."""
    
    # Load config
    config = load_config("rysky_config.yaml")
    
    # Set up LLM
    llm_ensemble = LLMEnsemble(config.llm.models)
    
    # Simple test code
    test_code = '''import React, { useState } from 'react';

const TestComponent = () => {
  const [count, setCount] = useState(0);
  
  // EVOLVE-BLOCK-START
  const handleIncrement = () => {
    setCount(count + 1);
  };
  // EVOLVE-BLOCK-END
  
  return (
    <div>
      <p>Count: {count}</p>
      <button onClick={handleIncrement}>Click me</button>
    </div>
  );
};

export default TestComponent;'''

    # Test with full rewrite prompt
    system_message = """You are an expert React/JavaScript developer. 
Improve the provided React component by making it better.
Return the complete improved code in a javascript code block."""

    user_message = f"""Here is a React component to improve:

```javascript
{test_code}
```

Please improve this component and return the complete code."""

    print("Testing LLM response...")
    print("System message:", system_message[:100] + "...")
    print("User message:", user_message[:200] + "...")
    print("\n" + "="*50)
    
    try:
        response = await llm_ensemble.generate_with_context(
            system_message=system_message,
            messages=[{"role": "user", "content": user_message}]
        )
        
        print("LLM Response:")
        print(response)
        print("\n" + "="*50)
        
        # Test parsing
        from openevolve.utils.code_utils import parse_full_rewrite
        parsed_code = parse_full_rewrite(response, "javascript")
        
        if parsed_code:
            print("✅ Successfully parsed code:")
            print(parsed_code[:300] + "..." if len(parsed_code) > 300 else parsed_code)
            
            # Check if it's different from original
            if parsed_code.strip() != test_code.strip():
                print("✅ Code was modified!")
                return True
            else:
                print("❌ Code is identical to original")
                return False
        else:
            print("❌ Failed to parse code from response")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

async def test_diff_response():
    """Test what the LLM returns for diff-based prompts."""
    
    config = load_config("rysky_config.yaml")
    llm_ensemble = LLMEnsemble(config.llm.models)
    
    test_code = '''  const handleIncrement = () => {
    setCount(count + 1);
  };'''

    system_message = """You are an expert React/JavaScript developer. 
You must respond with diffs in the exact format specified."""

    user_message = f"""Improve this React code by using functional state updates:

```javascript
{test_code}
```

You MUST respond with diffs in this EXACT format:

<<<<<<< SEARCH
exact_code_to_find_and_replace
=======
new_improved_code
>>>>>>> REPLACE

Example:
<<<<<<< SEARCH
  const handleIncrement = () => {{
    setCount(count + 1);
  }};
=======
  const handleIncrement = () => {{
    setCount(prevCount => prevCount + 1);
  }};
>>>>>>> REPLACE

Provide your diff now:"""

    print("\nTesting diff-based response...")
    print("="*50)
    
    try:
        response = await llm_ensemble.generate_with_context(
            system_message=system_message,
            messages=[{"role": "user", "content": user_message}]
        )
        
        print("LLM Response:")
        print(response)
        print("\n" + "="*50)
        
        # Test diff parsing
        from openevolve.utils.diff_parser import extract_diffs_from_response
        diffs = extract_diffs_from_response(response)
        
        if diffs:
            print(f"✅ Successfully parsed {len(diffs)} diffs:")
            for i, (search, replace) in enumerate(diffs):
                print(f"Diff {i+1}:")
                print(f"  Search: {search[:100]}...")
                print(f"  Replace: {replace[:100]}...")
            return True
        else:
            print("❌ No valid diffs found")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

async def main():
    # Set up environment
    os.environ["OPENAI_API_KEY"] = "dummy-key-for-ollama"
    
    print("Debugging LLM responses for OpenEvolve...")
    print("="*60)
    
    # Test full rewrite
    rewrite_works = await test_llm_response()
    
    # Test diff-based
    diff_works = await test_diff_response()
    
    print("\n" + "="*60)
    print("SUMMARY:")
    print(f"Full rewrite parsing: {'WORKS' if rewrite_works else 'FAILS'}")
    print(f"Diff parsing: {'WORKS' if diff_works else 'FAILS'}")
    
    if rewrite_works:
        print("\n✅ Recommendation: Use full rewrite mode (diff_based_evolution: false)")
    elif diff_works:
        print("\n✅ Recommendation: Use diff mode (diff_based_evolution: true)")
    else:
        print("\n❌ Both modes failing - check LLM configuration")

if __name__ == "__main__":
    asyncio.run(main())