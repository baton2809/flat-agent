"""Routing accuracy evaluation script for FlatAgent."""

import json
import time
import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

from tabulate import tabulate

sys.path.append(str(Path(__file__).parent.parent))

from langchain_core.messages import HumanMessage
from agent.nodes import router_node

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_test_cases(file_path: str = "test_cases.json") -> List[Dict]:
    """Load test cases from a JSON file.

    Args:
        file_path: path to the JSON file with test cases, relative to this script.

    Returns:
        list of test case dicts with 'input' and 'expected_route' keys.
    """
    eval_dir = Path(__file__).parent
    full_path = eval_dir / file_path

    with open(full_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def evaluate_router(test_cases: List[Dict]) -> Tuple[Dict, List]:
    """Measure routing accuracy against a labeled test set.

    Args:
        test_cases: list of test case dicts.

    Returns:
        tuple of (metrics dict, detailed results list).
    """
    results = []
    route_accuracy = defaultdict(lambda: {"correct": 0, "total": 0})
    total_time = 0

    logger.info("evaluating %d test cases", len(test_cases))

    for i, test_case in enumerate(test_cases, 1):
        input_text = test_case["input"]
        expected_route = test_case["expected_route"]

        state = {
            "messages": [HumanMessage(content=input_text)],
            "user_id": "eval_user",
            "route": None
        }

        start_time = time.time()

        try:
            result_state = router_node(state)
            predicted_route = result_state.get("route", "unknown")
        except Exception as e:
            logger.error("error on case %d: %s", i, e)
            predicted_route = "error"

        latency = (time.time() - start_time) * 1000
        total_time += latency

        is_correct = predicted_route == expected_route

        route_accuracy[expected_route]["total"] += 1
        if is_correct:
            route_accuracy[expected_route]["correct"] += 1

        results.append({
            "test_id": i,
            "input": input_text[:50] + "..." if len(input_text) > 50 else input_text,
            "expected": expected_route,
            "predicted": predicted_route,
            "correct": is_correct,
            "latency_ms": round(latency, 2)
        })

        if i % 5 == 0:
            logger.info("processed %d/%d cases", i, len(test_cases))

    total_correct = sum(r["correct"] for r in results)
    total_cases = len(test_cases)
    overall_accuracy = (total_correct / total_cases * 100) if total_cases > 0 else 0
    avg_latency = total_time / total_cases if total_cases > 0 else 0

    metrics = {
        "overall_accuracy": round(overall_accuracy, 2),
        "total_cases": total_cases,
        "correct_predictions": total_correct,
        "avg_latency_ms": round(avg_latency, 2),
        "route_accuracy": {}
    }

    for route, stats in route_accuracy.items():
        accuracy = (stats["correct"] / stats["total"] * 100) if stats["total"] > 0 else 0
        metrics["route_accuracy"][route] = {
            "accuracy": round(accuracy, 2),
            "correct": stats["correct"],
            "total": stats["total"]
        }

    return metrics, results


def print_results(metrics: Dict, results: List) -> None:
    """Print formatted evaluation results to stdout.

    Args:
        metrics: dict with accuracy and latency metrics.
        results: list of per-case result dicts.
    """
    print("\n--- routing evaluation results ---")

    print(f"\noverall metrics:")
    print(f"  accuracy: {metrics['overall_accuracy']}%")
    print(f"  correct predictions: {metrics['correct_predictions']}/{metrics['total_cases']}")
    print(f"  avg latency: {metrics['avg_latency_ms']} ms")

    print(f"\naccuracy by route:")
    route_table = []
    for route, stats in metrics["route_accuracy"].items():
        route_table.append([
            route,
            f"{stats['accuracy']}%",
            f"{stats['correct']}/{stats['total']}"
        ])

    print(tabulate(route_table, headers=["route", "accuracy", "correct/total"], tablefmt="grid"))

    errors = [r for r in results if not r["correct"]]
    if errors:
        print(f"\nfailed classifications ({len(errors)}):")
        error_table = []
        for err in errors[:10]:
            error_table.append([
                err["test_id"],
                err["input"],
                err["expected"],
                err["predicted"]
            ])

        print(tabulate(error_table, headers=["id", "input", "expected", "predicted"], tablefmt="grid"))

        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
    else:
        print("\nall test cases passed")

    latencies = [r["latency_ms"] for r in results]
    print(f"\nlatency stats:")
    print(f"  min: {min(latencies):.2f} ms")
    print(f"  max: {max(latencies):.2f} ms")
    print(f"  avg: {metrics['avg_latency_ms']} ms")

    print("\n--- end of report ---")


def save_results(metrics: Dict, results: List, output_file: str = "eval_results.json") -> None:
    """Persist evaluation results to a JSON file.

    Args:
        metrics: dict with accuracy and latency metrics.
        results: list of per-case result dicts.
        output_file: filename for output, relative to eval directory.
    """
    eval_dir = Path(__file__).parent
    output_path = eval_dir / output_file

    output_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": metrics,
        "detailed_results": results
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    logger.info("results saved to %s", output_path)


def main() -> None:
    """Run the full routing evaluation pipeline."""
    try:
        test_cases = load_test_cases()
        logger.info("loaded %d test cases", len(test_cases))

        metrics, results = evaluate_router(test_cases)

        print_results(metrics, results)

        save_results(metrics, results)

    except Exception as e:
        logger.error("evaluation failed: %s", e)
        raise


if __name__ == "__main__":
    main()
