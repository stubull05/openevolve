#!/usr/bin/env python3
"""
Script to evolve specific files in the Rysky trading app.
"""

import os
import sys
import subprocess
from pathlib import Path

def main():
    # Set up paths
    openevolve_root = Path(__file__).parent
    rysky_root = Path("C:/Source/GIT/Rysky")
    
    if not rysky_root.exists():
        print(f"Error: Rysky repo not found at {rysky_root}")
        sys.exit(1)
    
    # Files to evolve (start with key React components)
    target_files = [
        rysky_root / "desktop/src/AuthContext.js",
        rysky_root / "desktop/src/Chart.js",
        rysky_root / "desktop/src/Chat.js",
        rysky_root / "desktop/src/StatusBar.js",
    ]
    
    # Check files exist
    existing_files = [f for f in target_files if f.exists()]
    if not existing_files:
        print("Error: No target files found")
        sys.exit(1)
    
    print(f"Found {len(existing_files)} files to evolve:")
    for f in existing_files:
        print(f"  - {f}")
    
    # Set up environment
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = "dummy-key-for-ollama"
    
    # Evolve each file
    for target_file in existing_files:
        print(f"\n=== Evolving {target_file.name} ===")
        
        cmd = [
            sys.executable,
            str(openevolve_root / "openevolve-run.py"),
            str(target_file),
            str(openevolve_root / "rysky_evaluator.py"),
            "--config", str(openevolve_root / "rysky_config.yaml"),
            "--iterations", "10"
        ]
        
        print(f"Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, env=env, cwd=str(openevolve_root))
            print(f"Evolution completed with exit code: {result.returncode}")
        except Exception as e:
            print(f"Error running evolution: {e}")
            continue

if __name__ == "__main__":
    main()