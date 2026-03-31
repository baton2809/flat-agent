#!/usr/bin/env python3
"""Main test runner for FlatAgent."""

import sys
import os
import subprocess
import logging
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_test_file(test_file: Path) -> bool:
    """Run a single test file."""
    logger.info(f"Running: {test_file.name}")

    try:
        result = subprocess.run(
            [sys.executable, str(test_file)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0:
            logger.info(f"{test_file.name} passed")
            return True
        else:
            logger.error(f"{test_file.name} failed")
            logger.error(f"stdout: {result.stdout}")
            logger.error(f"stderr: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error(f"{test_file.name} timeout")
        return False
    except Exception as e:
        logger.error(f"{test_file.name} error: {e}")
        return False

def run_tests(test_category: str = "all"):
    """Run tests in specified category."""
    test_dir = Path(__file__).parent

    if test_category == "all":
        test_dirs = [test_dir / "unit", test_dir / "integration", test_dir / "system"]
    else:
        test_dirs = [test_dir / test_category]

    total_tests = 0
    passed_tests = 0
    failed_tests = []

    print(f"Running FlatAgent tests: {test_category}")
    print("-" * 60)

    for test_dir_path in test_dirs:
        if not test_dir_path.exists():
            logger.warning(f"Test directory not found: {test_dir_path}")
            continue

        category = test_dir_path.name
        print(f"\n--- {category} tests ---")
        print("-" * 40)

        test_files = list(test_dir_path.glob("test_*.py"))

        if not test_files:
            logger.info(f"No test files found in {category}")
            continue

        for test_file in sorted(test_files):
            total_tests += 1
            if run_test_file(test_file):
                passed_tests += 1
            else:
                failed_tests.append(test_file.name)

    print("\n" + "-" * 60)
    print("Test summary")
    print(f"Total tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {len(failed_tests)}")

    if failed_tests:
        print(f"\nFailed tests:")
        for test in failed_tests:
            print(f"  - {test}")

        return False
    else:
        print(f"\nAll tests passed!")
        return True

def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Run FlatAgent tests")
    parser.add_argument(
        "category",
        nargs="?",
        default="all",
        choices=["all", "unit", "integration", "system"],
        help="Test category to run (default: all)"
    )

    args = parser.parse_args()

    success = run_tests(args.category)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
