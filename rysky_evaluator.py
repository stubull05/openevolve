#!/usr/bin/env python3
"""
Evaluator for Rysky trading app files.
Focuses on JavaScript/TypeScript React components and Python backend files.
"""

import ast
import sys
import subprocess
import tempfile
import os
import json
from pathlib import Path

def evaluate_react_component(code_content, file_path):
    """Evaluate React component for syntax and structure."""
    metrics = {
        "syntax_score": 0.0,
        "react_score": 0.0,
        "complexity_score": 0.0,
        "error_handling_score": 0.0,
        "combined_score": 0.0
    }
    
    try:
        # Check syntax without Node.js dependency
        lines = code_content.split('\n')
        
        # Basic syntax checks
        brace_count = code_content.count('{') - code_content.count('}')
        paren_count = code_content.count('(') - code_content.count(')')
        bracket_count = code_content.count('[') - code_content.count(']')
        
        if brace_count == 0 and paren_count == 0 and bracket_count == 0:
            metrics["syntax_score"] = 1.0
        else:
            metrics["syntax_score"] = max(0.0, 1.0 - abs(brace_count + paren_count + bracket_count) * 0.1)
        
        # Enhanced React patterns
        react_patterns = {
            'import React': 0.2,
            'useState': 0.15,
            'useEffect': 0.15,
            'useContext': 0.1,
            'export default': 0.1,
            'return (': 0.1,
            'const ': 0.1,
            'function': 0.05,
            'props': 0.05
        }
        
        react_score = sum(weight for pattern, weight in react_patterns.items() if pattern in code_content)
        metrics["react_score"] = min(react_score, 1.0)
        
        # Complexity score based on component structure
        complexity_indicators = {
            'useState': 0.1,
            'useEffect': 0.15,
            'async': 0.1,
            'await': 0.1,
            'try': 0.1,
            'catch': 0.1,
            'if': 0.05,
            'map': 0.05,
            'filter': 0.05,
            'reduce': 0.05
        }
        
        complexity = sum(weight * code_content.count(indicator) for indicator, weight in complexity_indicators.items())
        metrics["complexity_score"] = min(complexity / 2.0, 1.0)  # Normalize
        
        # Error handling score
        error_patterns = ['try', 'catch', 'error', 'Error', 'finally']
        error_score = sum(1 for pattern in error_patterns if pattern in code_content) / len(error_patterns)
        metrics["error_handling_score"] = min(error_score, 1.0)
            
    except Exception as e:
        print(f"Error evaluating React component: {e}")
    
    # Enhanced combined score
    metrics["combined_score"] = (
        metrics["syntax_score"] * 0.3 +
        metrics["react_score"] * 0.3 +
        metrics["complexity_score"] * 0.2 +
        metrics["error_handling_score"] * 0.2
    )
    
    return metrics

def evaluate_python_file(code_content, file_path):
    """Evaluate Python backend file."""
    metrics = {
        "syntax_score": 0.0,
        "structure_score": 0.0,
        "import_score": 0.0,
        "combined_score": 0.0
    }
    
    try:
        # Check syntax
        tree = ast.parse(code_content)
        metrics["syntax_score"] = 1.0
        
        # Check structure (functions, classes)
        functions = len([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)])
        classes = len([n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)])
        
        if functions > 0 or classes > 0:
            metrics["structure_score"] = 1.0
            
        # Check imports
        imports = len([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))])
        if imports > 0:
            metrics["import_score"] = 1.0
            
    except SyntaxError as e:
        print(f"Python syntax error: {e}")
    except Exception as e:
        print(f"Error evaluating Python file: {e}")
    
    # Combined score with better weighting
    metrics["combined_score"] = (
        metrics["syntax_score"] * 0.4 +
        metrics["structure_score"] * 0.4 +
        metrics["import_score"] * 0.2
    )
    
    return metrics

def evaluate(code_content, file_path=None):
    """Main evaluation function called by OpenEvolve."""
    if not file_path:
        return {
            "syntax_score": 0.0,
            "react_score": 0.0,
            "complexity_score": 0.0,
            "error_handling_score": 0.0,
            "combined_score": 0.0
        }
    
    try:
        file_path = Path(file_path)
        file_extension = file_path.suffix.lower()
        
        # Check for EVOLVE-BLOCK markers
        has_evolve_blocks = 'EVOLVE-BLOCK-START' in code_content and 'EVOLVE-BLOCK-END' in code_content
        
        if file_extension in ['.js', '.jsx', '.ts', '.tsx']:
            metrics = evaluate_react_component(code_content, file_path)
        elif file_extension == '.py':
            metrics = evaluate_python_file(code_content, file_path)
        else:
            # Generic evaluation
            metrics = {
                "syntax_score": min(1.0, len(code_content.split('\n')) / 50.0),
                "react_score": 0.5,
                "complexity_score": min(1.0, len(code_content.split('\n')) / 100.0),
                "error_handling_score": 0.3,
                "combined_score": min(1.0, len(code_content.split('\n')) / 50.0)
            }
        
        # Ensure all required metrics exist
        required_metrics = ["syntax_score", "react_score", "complexity_score", "error_handling_score"]
        for metric in required_metrics:
            if metric not in metrics:
                metrics[metric] = 0.0
        
        # Bonus for having evolve blocks
        if has_evolve_blocks:
            metrics["evolve_ready"] = 1.0
            metrics["combined_score"] = min(1.0, metrics["combined_score"] * 1.1)
        else:
            metrics["evolve_ready"] = 0.0
            metrics["combined_score"] = metrics["combined_score"] * 0.8
        
        return metrics
        
    except Exception as e:
        print(f"Error in evaluator: {e}")
        return {
            "syntax_score": 0.0,
            "react_score": 0.0,
            "complexity_score": 0.0,
            "error_handling_score": 0.0,
            "combined_score": 0.0
        }

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python rysky_evaluator.py <file_path>")
        sys.exit(1)
    
    file_path = Path(sys.argv[1])
    
    if not file_path.exists():
        print(f"Error: File {file_path} does not exist")
        sys.exit(1)
    
    try:
        code_content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
    
    metrics = evaluate(code_content, str(file_path))
    
    print("Evaluation Results:")
    for key, value in metrics.items():
        print(f"{key}: {value:.4f}")