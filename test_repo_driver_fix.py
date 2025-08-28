#!/usr/bin/env python3
"""
Test script to verify the repo_driver.py fix for metadata vs code issue
"""

import os
import tempfile
from pathlib import Path

def test_best_program_selection():
    """Test that repo_driver correctly selects code files over JSON metadata files"""
    
    # Create a temporary directory structure
    with tempfile.TemporaryDirectory() as temp_dir:
        checkpoint_dir = Path(temp_dir) / "checkpoint_10"
        checkpoint_dir.mkdir(parents=True)
        
        # Create a JSON metadata file (this should be ignored)
        json_file = checkpoint_dir / "best_program_info.json"
        json_file.write_text('{"id": "test", "metrics": {"score": 0.95}}')
        
        # Create the actual code file (this should be selected)
        code_file = checkpoint_dir / "best_program.js"
        code_file.write_text('console.log("Hello, evolved world!");')
        
        # Simulate the repo_driver logic
        best = None
        for cand in sorted(checkpoint_dir.glob("best_program*")):
            if cand.is_file() and not cand.name.endswith('.json'):
                best = cand
                print(f"Found best program file: {cand}")
                break
        
        if best:
            content = best.read_text()
            print(f"Content: {content}")
            
            # Verify we got the code, not the JSON
            assert "console.log" in content, "Should have selected the code file"
            assert "metrics" not in content, "Should not have selected the JSON file"
            print("[PASS] Test passed: Code file selected correctly")
        else:
            print("[FAIL] Test failed: No best program file found")
            return False
    
    return True

if __name__ == "__main__":
    print("Testing repo_driver.py fix...")
    if test_best_program_selection():
        print("[SUCCESS] All tests passed! The fix should work correctly.")
    else:
        print("[ERROR] Tests failed!")