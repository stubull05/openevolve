#!/usr/bin/env python3
"""
Test script to verify Rysky file mutations are working.
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

def create_test_react_file():
    """Create a simple React test file with EVOLVE blocks."""
    test_content = '''import React, { useState } from 'react';

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

export default TestComponent;
'''
    
    # Create in Rysky desktop/src directory
    rysky_src = Path("C:/Source/GIT/Rysky/desktop/src")
    test_file = rysky_src / "TestMutation.js"
    test_file.write_text(test_content)
    return test_file

def run_short_evolution(test_file):
    """Run a short evolution on the test file."""
    openevolve_root = Path("C:/Source/GIT/openevolve")
    
    # Set up environment
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = "dummy-key-for-ollama"
    
    cmd = [
        sys.executable,
        str(openevolve_root / "openevolve-run.py"),
        str(test_file),
        str(openevolve_root / "rysky_evaluator.py"),
        "--config", str(openevolve_root / "rysky_config.yaml"),
        "--iterations", "3"  # Just 3 iterations for testing
    ]
    
    print(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd, 
            env=env, 
            cwd=str(openevolve_root),
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        print(f"Exit code: {result.returncode}")
        if result.stdout:
            print("STDOUT:")
            print(result.stdout[-1000:])  # Last 1000 chars
        if result.stderr:
            print("STDERR:")
            print(result.stderr[-1000:])  # Last 1000 chars
            
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        print("Evolution timed out after 5 minutes")
        return False
    except Exception as e:
        print(f"Error running evolution: {e}")
        return False

def check_for_mutations(test_file, original_content):
    """Check if the file was actually mutated."""
    if not test_file.exists():
        print("Test file no longer exists!")
        return False
    
    current_content = test_file.read_text()
    
    # Check if content changed
    if current_content == original_content:
        print("❌ File was NOT mutated - content is identical")
        return False
    else:
        print("✅ File WAS mutated - content changed")
        print(f"Original length: {len(original_content)}")
        print(f"New length: {len(current_content)}")
        
        # Show a diff preview
        original_lines = original_content.split('\n')
        new_lines = current_content.split('\n')
        
        print("\nChanges detected:")
        for i, (orig, new) in enumerate(zip(original_lines, new_lines)):
            if orig != new:
                print(f"Line {i+1}:")
                print(f"  - {orig}")
                print(f"  + {new}")
        
        return True

def check_output_directory(test_file):
    """Check if evolution output was created."""
    # Look for output directory
    test_dir = test_file.parent
    output_dirs = list(test_dir.glob("openevolve_output*"))
    
    if not output_dirs:
        print("❌ No openevolve_output directory found")
        return False
    
    output_dir = output_dirs[0]
    print(f"✅ Found output directory: {output_dir}")
    
    # Check for checkpoints
    checkpoints_dir = output_dir / "checkpoints"
    if checkpoints_dir.exists():
        checkpoints = list(checkpoints_dir.glob("checkpoint_*"))
        print(f"✅ Found {len(checkpoints)} checkpoints")
        
        # Check latest checkpoint for best program
        if checkpoints:
            latest = max(checkpoints, key=lambda p: int(p.name.split('_')[1]))
            best_files = list(latest.glob("best_program.*"))
            if best_files:
                print(f"✅ Found best program files: {[f.name for f in best_files]}")
                return True
    
    print("❌ No valid checkpoints or best programs found")
    return False

def main():
    print("Testing Rysky file mutations...")
    print("="*50)
    
    # Create test file
    print("1. Creating test React file...")
    test_file = create_test_react_file()
    original_content = test_file.read_text()
    print(f"   Created: {test_file}")
    print(f"   Size: {len(original_content)} characters")
    
    try:
        # Run evolution
        print("\n2. Running short evolution (3 iterations)...")
        evolution_success = run_short_evolution(test_file)
        print(f"   Evolution completed: {'✅' if evolution_success else '❌'}")
        
        # Check for mutations
        print("\n3. Checking for file mutations...")
        mutation_detected = check_for_mutations(test_file, original_content)
        
        # Check output directory
        print("\n4. Checking evolution output...")
        output_created = check_output_directory(test_file)
        
        # Summary
        print("\n" + "="*50)
        print("SUMMARY:")
        print(f"Evolution ran: {'YES' if evolution_success else 'NO'}")
        print(f"File mutated: {'YES' if mutation_detected else 'NO'}")
        print(f"Output created: {'YES' if output_created else 'NO'}")
        
        if mutation_detected:
            print("\n🎉 SUCCESS: File mutations are working!")
        else:
            print("\n❌ ISSUE: Files are not being mutated")
            print("   Check the logs for 'No valid diffs found' errors")
            
    finally:
        # Cleanup
        print(f"\n5. Cleaning up...")
        if test_file.exists():
            test_file.unlink()
            print(f"   Removed test file: {test_file}")
        
        # Remove output directories
        test_dir = test_file.parent
        for output_dir in test_dir.glob("openevolve_output*"):
            shutil.rmtree(output_dir)
            print(f"   Removed output: {output_dir}")

if __name__ == "__main__":
    main()