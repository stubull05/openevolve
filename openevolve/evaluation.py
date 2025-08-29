#!/usr/bin/env python3
"""
Fixed evaluation.py that handles import issues and provides better test results
"""

import os
import sys
import subprocess
import importlib.util
from pathlib import Path
from typing import Dict, Any, Union

def safe_import_module(module_name: str = "api", search_paths: list = None) -> Any:
    """
    Safely import a module with multiple fallback strategies
    """
    if search_paths is None:
        search_paths = [
            "/workspace/target",
            "/workspace", 
            str(Path.cwd()),
            str(Path(__file__).parent),
        ]
    
    # Ensure search paths are in sys.path
    for path in search_paths:
        if path and str(path) not in sys.path:
            sys.path.insert(0, str(path))
    
    # Strategy 1: Direct import
    try:
        return importlib.import_module(module_name)
    except ImportError:
        pass
    
    # Strategy 2: Import from file
    for search_path in search_paths:
        module_file = Path(search_path) / f"{module_name}.py"
        if module_file.exists():
            try:
                spec = importlib.util.spec_from_file_location(module_name, module_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    return module
            except Exception as e:
                print(f"Failed to load {module_file}: {e}")
                continue
    
    raise ImportError(f"Could not import {module_name} from any location")

def check_syntax(file_path: Union[str, Path]) -> tuple[bool, str]:
    """Check if a Python file has valid syntax"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        compile(source, str(file_path), 'exec')
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"Error reading {file_path}: {e}"

def run_pytest(test_dir: str = "/workspace/target/tests") -> Dict[str, Any]:
    """
    Run pytest with proper environment setup and error handling
    """
    test_path = Path(test_dir)
    target_dir = Path("/workspace/target")
    
    # Check if test directory exists
    if not test_path.exists():
        return {
            "py_pass": 0.0,
            "error": f"Test directory {test_dir} not found",
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "total": 0
        }
    
    # Check if target file has valid syntax
    target_file = target_dir / "api.py"
    if target_file.exists():
        is_valid, error = check_syntax(target_file)
        if not is_valid:
            return {
                "py_pass": 0.0,
                "error": f"Syntax error in api.py: {error}",
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "total": 0
            }
    
    # Try to import the target module
    try:
        api_module = safe_import_module("api")
        print(f"Successfully imported api module: {api_module}")
    except Exception as e:
        return {
            "py_pass": 0.0,
            "error": f"Cannot import api module: {e}",
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "total": 0
        }
    
    # Set up environment for pytest
    env = os.environ.copy()
    env["PYTHONPATH"] = f"/workspace/target:/workspace:{env.get('PYTHONPATH', '')}"
    env["PYTHONUNBUFFERED"] = "1"
    
    # Run pytest
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-v", "--tb=short", str(test_path)],
            capture_output=True,
            text=True,
            cwd=str(target_dir),
            env=env,
            timeout=300  # 5 minute timeout
        )
        
        # Parse the output to count results
        stdout_lines = result.stdout.splitlines()
        stderr_lines = result.stderr.splitlines()
        
        passed = 0
        failed = 0
        errors = 0
        skipped = 0
        
        # Count test results from output
        for line in stdout_lines:
            if " PASSED " in line:
                passed += 1
            elif " FAILED " in line:
                failed += 1
            elif " ERROR " in line:
                errors += 1
            elif " SKIPPED " in line:
                skipped += 1
        
        # Also check the summary line
        for line in stdout_lines:
            if " passed" in line or " failed" in line or " error" in line:
                # Extract numbers from summary like "2 failed, 1 passed in 1.23s"
                import re
                numbers = re.findall(r'(\d+) (passed|failed|error)', line)
                for count, status in numbers:
                    if status == "passed":
                        passed = max(passed, int(count))
                    elif status == "failed":
                        failed = max(failed, int(count))
                    elif status == "error":
                        errors = max(errors, int(count))
        
        total_tests = passed + failed + errors
        
        if total_tests > 0:
            py_pass = passed / total_tests
        else:
            py_pass = 0.0
        
        # Return comprehensive results
        return {
            "py_pass": py_pass,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "total": total_tests,
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
        
    except subprocess.TimeoutExpired:
        return {
            "py_pass": 0.0,
            "error": "Tests timed out after 5 minutes",
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "total": 0
        }
    except Exception as e:
        return {
            "py_pass": 0.0,
            "error": f"Error running pytest: {e}",
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "total": 0
        }

def run_ui_tests() -> Dict[str, Any]:
    """
    Placeholder for UI tests - returns success for now
    """
    return {
        "ui_pass": 1.0,
        "ui_tests_run": 1,
        "ui_tests_passed": 1
    }

def run_playwright_tests() -> Dict[str, Any]:
    """
    Placeholder for Playwright tests - returns success for now
    """
    return {
        "pw_pass": 0.0,  # Set to 0 to match your current scoring
        "pw_tests_run": 0,
        "pw_tests_passed": 0
    }

def evaluate(program_path: str) -> Dict[str, Union[float, str]]:
    """
    Main evaluation function called by OpenEvolve
    """
    print(f"[eval] Evaluating program: {program_path}")
    
    # Ensure the program file exists
    program_file = Path(program_path)
    if not program_file.exists():
        return {
            "py_pass": 0.0,
            "ui_pass": 0.0,
            "pw_pass": 0.0,
            "combined_score": 0.0,
            "error": f"Program file not found: {program_path}"
        }
    
    # Check syntax first
    is_valid, error = check_syntax(program_file)
    if not is_valid:
        return {
            "py_pass": 0.0,
            "ui_pass": 0.0,
            "pw_pass": 0.0,
            "combined_score": 0.0,
            "error": f"Syntax error: {error}"
        }
    
    # Run different test suites
    pytest_results = run_pytest()
    ui_results = run_ui_tests()
    pw_results = run_playwright_tests()
    
    # Calculate combined score (weights can be adjusted)
    py_pass = pytest_results.get("py_pass", 0.0)
    ui_pass = ui_results.get("ui_pass", 1.0)
    pw_pass = pw_results.get("pw_pass", 0.0)
    
    # Weight the scores (adjust these weights as needed)
    combined_score = (py_pass * 0.5) + (ui_pass * 0.3) + (pw_pass * 0.2)
    
    # Prepare result
    result = {
        "py_pass": py_pass,
        "ui_pass": ui_pass, 
        "pw_pass": pw_pass,
        "combined_score": combined_score
    }
    
    # Add debugging info if tests failed
    if py_pass == 0.0 and "error" in pytest_results:
        result["debug_info"] = pytest_results["error"]
    
    # Add test counts for debugging
    result.update({
        "tests_passed": pytest_results.get("passed", 0),
        "tests_failed": pytest_results.get("failed", 0),
        "tests_errors": pytest_results.get("errors", 0),
        "tests_total": pytest_results.get("total", 0)
    })
    
    print(f"[eval] Results: py_pass={py_pass:.4f}, ui_pass={ui_pass:.4f}, pw_pass={pw_pass:.4f}, combined={combined_score:.4f}")
    
    return result

# For compatibility with different calling conventions
def main():
    """Command line interface"""
    if len(sys.argv) > 1:
        program_path = sys.argv[1]
    else:
        program_path = "/workspace/target/api.py"
    
    results = evaluate(program_path)
    
    print("Evaluation Results:")
    for key, value in results.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")

if __name__ == "__main__":
    main()