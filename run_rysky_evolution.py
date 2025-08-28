#!/usr/bin/env python3
"""
Direct script to run evolution on Rysky files with proper configuration.
"""

import os
import sys
import subprocess
import time
from pathlib import Path

def run_evolution_on_rysky_files():
    """Run evolution directly on Rysky React files."""
    
    # Set up paths
    openevolve_root = Path("C:/Source/GIT/openevolve")
    rysky_root = Path("C:/Source/GIT/Rysky")
    
    # Target React files with EVOLVE blocks
    target_files = [
        rysky_root / "desktop/src/Chat.js",
        rysky_root / "desktop/src/App.js", 
        rysky_root / "desktop/src/AuthContext.js",
        rysky_root / "desktop/src/Chart.js",
    ]
    
    # Filter to existing files
    existing_files = [f for f in target_files if f.exists()]
    
    if not existing_files:
        print("No target files found!")
        return
    
    print(f"Found {len(existing_files)} files to evolve:")
    for f in existing_files:
        print(f"  - {f}")
    
    # Set up environment
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = "dummy-key-for-ollama"
    
    # Run evolution on each file
    for target_file in existing_files:
        print(f"\n{'='*60}")
        print(f"Evolving: {target_file.name}")
        print(f"{'='*60}")
        
        cmd = [
            sys.executable,
            str(openevolve_root / "openevolve-run.py"),
            str(target_file),
            str(openevolve_root / "rysky_evaluator.py"),
            "--config", str(openevolve_root / "rysky_config.yaml"),
            "--iterations", "5"
        ]
        
        print(f"Command: {' '.join(cmd)}")
        
        try:
            # Run with real-time output
            process = subprocess.Popen(
                cmd,
                env=env,
                cwd=str(openevolve_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Print output in real-time
            for line in process.stdout:
                print(line.rstrip())
            
            process.wait()
            
            if process.returncode == 0:
                print(f"Evolution completed successfully for {target_file.name}")
            else:
                print(f"Evolution failed for {target_file.name} (exit code: {process.returncode})")
                
        except Exception as e:
            print(f"Error running evolution on {target_file.name}: {e}")
        
        # Small delay between files
        time.sleep(2)
    
    print(f"\n{'='*60}")
    print("Evolution complete! Check the files for mutations.")

if __name__ == "__main__":
    run_evolution_on_rysky_files()