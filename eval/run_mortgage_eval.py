"""Mortgage calculation accuracy evaluation for FlatAgent.

Verifies that calculate_mortgage() matches reference bank values
within the specified tolerance.

Usage::

    cd eval && python run_mortgage_eval.py

Target: all cases within tolerance_pct (usually 1%)
"""

import json
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

from tabulate import tabulate

sys.path.append(str(Path(__file__).parent.parent))

from agent.tools.mortgage_calc import calculate_mortgage

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def load_test_cases(file_path: str = "test_mortgage.json") -> List[Dict]:
    eval_dir = Path(__file__).parent
    with open(eval_dir / file_path, encoding="utf-8") as f:
        return json.load(f)


def evaluate_mortgage(test_cases: List[Dict]) -> Tuple[Dict, List]:
    results = []
    passed = 0
    failed = 0

    for i, case in enumerate(test_cases, 1):
        amount = case["amount"]
        rate = case["annual_rate"]
        term = case["term_months"]
        expected = case["expected_monthly"]
        tolerance = case["tolerance_pct"]

        start = time.time()
        try:
            result = calculate_mortgage(amount, rate, term)
            actual = result["monthly_payment"]
            latency_ms = (time.time() - start) * 1000

            if expected == 0:
                deviation_pct = 0.0 if actual == 0 else 100.0
            else:
                deviation_pct = abs(actual - expected) / expected * 100

            ok = deviation_pct <= tolerance
            if ok:
                passed += 1
            else:
                failed += 1

            results.append({
                "id": i,
                "description": case.get("description", ""),
                "amount_mln": round(amount / 1_000_000, 1),
                "rate_pct": rate,
                "term_years": round(term / 12, 1),
                "expected": expected,
                "actual": actual,
                "deviation_pct": round(deviation_pct, 3),
                "tolerance_pct": tolerance,
                "source": case.get("source", ""),
                "passed": ok,
                "latency_ms": round(latency_ms, 2),
                "error": None,
            })

        except Exception as exc:
            latency_ms = (time.time() - start) * 1000
            failed += 1
            results.append({
                "id": i,
                "description": case.get("description", ""),
                "amount_mln": round(amount / 1_000_000, 1),
                "rate_pct": rate,
                "term_years": round(term / 12, 1),
                "expected": expected,
                "actual": None,
                "deviation_pct": None,
                "tolerance_pct": tolerance,
                "source": case.get("source", ""),
                "passed": False,
                "latency_ms": round(latency_ms, 2),
                "error": str(exc),
            })

    metrics = {
        "total_cases": len(test_cases),
        "passed": passed,
        "failed": failed,
        "pass_rate_pct": round(passed / len(test_cases) * 100, 1) if test_cases else 0,
        "all_passed": failed == 0,
    }

    return metrics, results


def print_results(metrics: Dict, results: List) -> None:
    print("\n--- mortgage accuracy evaluation ---")
    print(f"\n{metrics['passed']}/{metrics['total_cases']} cases passed")
    print(f"pass rate: {metrics['pass_rate_pct']}%")

    status = "PASS" if metrics["all_passed"] else "FAIL"
    print(f"overall: {status}")

    table = []
    for r in results:
        actual_str = f"{r['actual']:,.0f}" if r["actual"] is not None else "ERROR"
        dev_str = f"{r['deviation_pct']:.3f}%" if r["deviation_pct"] is not None else r.get("error", "")
        ok_str = "OK" if r["passed"] else "FAIL"
        table.append([
            r["id"],
            r["description"],
            f"{r['expected']:,.0f}",
            actual_str,
            dev_str,
            f"<= {r['tolerance_pct']}%",
            ok_str,
        ])

    print("\n" + tabulate(
        table,
        headers=["id", "case", "expected", "actual", "deviation", "tolerance", "result"],
        tablefmt="grid",
    ))
    print("\n--- end of report ---")


def save_results(metrics: Dict, results: List, output_file: str = "eval_mortgage_results.json") -> None:
    eval_dir = Path(__file__).parent
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "metrics": metrics,
        "detailed_results": results,
    }
    with open(eval_dir / output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


def main() -> None:
    test_cases = load_test_cases()
    print(f"loaded {len(test_cases)} mortgage test cases")
    metrics, results = evaluate_mortgage(test_cases)
    print_results(metrics, results)
    save_results(metrics, results)
    sys.exit(0 if metrics["all_passed"] else 1)


if __name__ == "__main__":
    main()
