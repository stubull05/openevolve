"""
Tests for iteration counting and checkpoint behavior
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import Mock, patch, MagicMock

# Set dummy API key for testing
os.environ["OPENAI_API_KEY"] = "test"

from openevolve.config import Config
from openevolve.controller import OpenEvolve
from openevolve.database import Program, ProgramDatabase


class TestIterationCounting(unittest.TestCase):
    """Tests for correct iteration counting behavior"""

    def setUp(self):
        """Set up test environment"""
        self.test_dir = tempfile.mkdtemp()

        # Create test program
        self.program_content = """# EVOLVE-BLOCK-START
def compute(x):
    return x * 2
# EVOLVE-BLOCK-END
"""
        self.program_file = os.path.join(self.test_dir, "test_program.py")
        with open(self.program_file, "w") as f:
            f.write(self.program_content)

        # Create test evaluator
        self.eval_content = """
def evaluate(program_path):
    return {"score": 0.5, "performance": 0.6}
"""
        self.eval_file = os.path.join(self.test_dir, "evaluator.py")
        with open(self.eval_file, "w") as f:
            f.write(self.eval_content)

    def tearDown(self):
        """Clean up test environment"""
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_fresh_start_iteration_counting(self):
        """Test that fresh start correctly handles iteration 0 as special"""
        # Test the logic without actually running evolution
        config = Config()
        config.max_iterations = 20
        config.checkpoint_interval = 10

        # Simulate fresh start
        start_iteration = 0
        should_add_initial = True

        # Apply the logic from controller.py
        evolution_start = start_iteration
        evolution_iterations = config.max_iterations

        if should_add_initial and start_iteration == 0:
            evolution_start = 1

        # Verify
        self.assertEqual(evolution_start, 1, "Evolution should start at iteration 1")
        self.assertEqual(evolution_iterations, 20, "Should run 20 evolution iterations")

        # Simulate what process_parallel would do
        total_iterations = evolution_start + evolution_iterations
        self.assertEqual(total_iterations, 21, "Total range should be 21 (1 through 20)")

        # Check checkpoint alignment
        expected_checkpoints = []
        for i in range(evolution_start, total_iterations):
            if i > 0 and i % config.checkpoint_interval == 0:
                expected_checkpoints.append(i)

        self.assertEqual(expected_checkpoints, [10, 20], "Checkpoints should be at 10 and 20")

    def test_resume_iteration_counting(self):
        """Test that resume correctly continues from checkpoint"""
        config = Config()
        config.max_iterations = 10
        config.checkpoint_interval = 10

        # Simulate resume from checkpoint 10
        start_iteration = 11  # Last iteration was 10, so start at 11
        should_add_initial = False

        # Apply the logic
        evolution_start = start_iteration
        evolution_iterations = config.max_iterations

        if should_add_initial and start_iteration == 0:
            evolution_start = 1

        # Verify
        self.assertEqual(evolution_start, 11, "Evolution should continue from iteration 11")
        self.assertEqual(evolution_iterations, 10, "Should run 10 more iterations")

        # Total iterations
        total_iterations = evolution_start + evolution_iterations
        self.assertEqual(total_iterations, 21, "Should run through iteration 20")

        # Check checkpoint at 20
        expected_checkpoints = []
        for i in range(evolution_start, total_iterations):
            if i > 0 and i % config.checkpoint_interval == 0:
                expected_checkpoints.append(i)

        self.assertEqual(expected_checkpoints, [20], "Should checkpoint at 20")

    def test_checkpoint_boundary_conditions(self):
        """Test checkpoint behavior at various boundaries"""
        test_cases = [
            # (start_iter, max_iter, checkpoint_interval, expected_checkpoints)
            (1, 100, 10, list(range(10, 101, 10))),  # Standard case
            (1, 99, 10, list(range(10, 100, 10))),  # Just short of last checkpoint
            (1, 101, 10, list(range(10, 101, 10))),  # Just past checkpoint
            (0, 20, 5, [5, 10, 15, 20]),  # Special case with iteration 0
        ]

        for start, max_iter, interval, expected in test_cases:
            # Apply fresh start logic
            evolution_start = start
            if start == 0:
                evolution_start = 1

            total = evolution_start + max_iter

            checkpoints = []
            for i in range(evolution_start, total):
                if i > 0 and i % interval == 0:
                    checkpoints.append(i)

            self.assertEqual(
                checkpoints,
                expected,
                f"Failed for start={start}, max={max_iter}, interval={interval}",
            )

    async def test_controller_iteration_behavior(self):
        """Test actual controller behavior with iteration counting"""
        config = Config()
        config.max_iterations = 20
        config.checkpoint_interval = 10
        config.database.in_memory = True
        config.evaluator.parallel_evaluations = 1

        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=config,
            output_dir=self.test_dir,
        )

        # Track checkpoint calls
        checkpoint_calls = []
        original_save = controller._save_checkpoint
        controller._save_checkpoint = lambda i: checkpoint_calls.append(i) or original_save(i)

        # Mock LLM
        with patch("openevolve.llm.ensemble.LLMEnsemble.generate_with_context") as mock_llm:
            mock_llm.return_value = """```python
# EVOLVE-BLOCK-START
def compute(x):
    return x << 1
# EVOLVE-BLOCK-END
```"""

            # Run with limited iterations to test
            await controller.run(iterations=20)

        # Verify checkpoints were called correctly
        # Note: We expect checkpoints at 10 and 20
        self.assertIn(10, checkpoint_calls, "Should checkpoint at iteration 10")
        self.assertIn(20, checkpoint_calls, "Should checkpoint at iteration 20")

        # Verify we have the right number of programs (initial + 20 evolution)
        # This may vary due to parallel execution, but should be at least 21
        self.assertGreaterEqual(
            len(controller.database.programs),
            21,
            "Should have at least 21 programs (initial + 20 iterations)",
        )


if __name__ == "__main__":
    # Run async test
    suite = unittest.TestLoader().loadTestsFromTestCase(TestIterationCounting)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Run the async test separately
    async def run_async_test():
        test = TestIterationCounting()
        test.setUp()
        try:
            await test.test_controller_iteration_behavior()
            print("✓ test_controller_iteration_behavior passed")
        except Exception as e:
            print(f"✗ test_controller_iteration_behavior failed: {e}")
        finally:
            test.tearDown()

    asyncio.run(run_async_test())
