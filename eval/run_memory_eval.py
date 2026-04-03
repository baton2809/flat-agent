"""Memory extraction accuracy evaluation for FlatAgent.

Measures recall: how often the extractor correctly identifies facts
that should be extracted vs messages that contain no facts.

Usage::

    cd eval && python run_memory_eval.py

Target: recall >= 85%
"""

import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

from tabulate import tabulate

sys.path.append(str(Path(__file__).parent.parent))

from agent.memory import memory_manager

logging.basicConfig(level=logging.WARNING)  # suppress info noise during eval
logger = logging.getLogger(__name__)


def load_test_cases(file_path: str = "test_memory.json") -> List[Dict]:
    eval_dir = Path(__file__).parent
    with open(eval_dir / file_path, encoding="utf-8") as f:
        return json.load(f)


def _extract_fact(user_id: str, message: str) -> str | None:
    """Run extraction and return extracted fact string, or None if nothing extracted."""
    before = set(memory_manager.get_user_facts(user_id))
    memory_manager.extract_and_store_facts(user_id, message)
    after = set(memory_manager.get_user_facts(user_id))
    new_facts = after - before
    return new_facts.pop() if new_facts else None


def evaluate_memory(test_cases: List[Dict]) -> Tuple[Dict, List]:
    results = []
    tp = 0  # should_extract=True и факт извлечён корректно
    fn = 0  # should_extract=True но факт не извлечён
    tn = 0  # should_extract=False и факт не извлечён (правильно)
    fp = 0  # should_extract=False но что-то извлеклось

    for i, case in enumerate(test_cases, 1):
        message = case["input"]
        should_extract = case["should_extract"]
        expected_contains = case.get("expected_contains")

        # Уникальный user_id на каждый кейс для изоляции
        user_id = f"eval_memory_case_{i}"
        memory_manager.delete_user_facts(user_id)  # clean up from previous runs

        start = time.time()
        fact = _extract_fact(user_id, message)
        latency_ms = (time.time() - start) * 1000

        extracted = fact is not None
        content_ok = (
            expected_contains is None
            or (fact is not None and expected_contains.lower() in fact.lower())
        )

        if should_extract and extracted and content_ok:
            outcome = "TP"
            tp += 1
        elif should_extract and (not extracted or not content_ok):
            outcome = "FN"
            fn += 1
        elif not should_extract and not extracted:
            outcome = "TN"
            tn += 1
        else:
            outcome = "FP"
            fp += 1

        results.append({
            "id": i,
            "input": message[:55] + "..." if len(message) > 55 else message,
            "should_extract": should_extract,
            "extracted_fact": (fact or "")[:60],
            "outcome": outcome,
            "latency_ms": round(latency_ms, 1),
            "description": case.get("description", ""),
        })

    should_extract_total = tp + fn
    recall = (tp / should_extract_total * 100) if should_extract_total > 0 else 0.0
    precision = (tp / (tp + fp) * 100) if (tp + fp) > 0 else 0.0
    specificity = (tn / (tn + fp) * 100) if (tn + fp) > 0 else 0.0

    metrics = {
        "total_cases": len(test_cases),
        "tp": tp, "fn": fn, "tn": tn, "fp": fp,
        "recall_pct": round(recall, 1),
        "precision_pct": round(precision, 1),
        "specificity_pct": round(specificity, 1),
        "target_recall_pct": 85.0,
        "passed": recall >= 85.0,
    }

    return metrics, results


def print_results(metrics: Dict, results: List) -> None:
    print("\n--- memory extraction evaluation ---")
    print(f"\nresults: {metrics['tp']} TP / {metrics['fn']} FN / {metrics['tn']} TN / {metrics['fp']} FP")
    print(f"  recall:      {metrics['recall_pct']}%  (target >= {metrics['target_recall_pct']}%)")
    print(f"  precision:   {metrics['precision_pct']}%")
    print(f"  specificity: {metrics['specificity_pct']}%")

    status = "PASS" if metrics["passed"] else "FAIL"
    print(f"\noverall: {status}")

    table = [
        [r["id"], r["input"], r["should_extract"], r["outcome"], r["extracted_fact"], f"{r['latency_ms']} ms"]
        for r in results
    ]
    print("\n" + tabulate(table, headers=["id", "input", "expected", "outcome", "extracted", "latency"], tablefmt="grid"))
    print("\n--- end of report ---")


def save_results(metrics: Dict, results: List, output_file: str = "eval_memory_results.json") -> None:
    eval_dir = Path(__file__).parent
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": metrics,
        "detailed_results": results,
    }
    with open(eval_dir / output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info("saved to %s", eval_dir / output_file)


def main() -> None:
    test_cases = load_test_cases()
    print(f"loaded {len(test_cases)} memory test cases")
    metrics, results = evaluate_memory(test_cases)
    print_results(metrics, results)
    save_results(metrics, results)
    sys.exit(0 if metrics["passed"] else 1)


if __name__ == "__main__":
    main()
