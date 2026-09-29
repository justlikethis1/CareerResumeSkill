from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .assertions import GoldenTestCase
from .eval_runner import evaluate_report_file, load_cases, write_scorecard


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate application reports offline.")
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--cases", type=Path, help="JSON list/object of cases keyed by report directory name.")
    parser.add_argument("--scorecard", type=Path, default=Path("output/eval_results.md"))
    args = parser.parse_args()
    case = GoldenTestCase.model_validate(json.loads(args.case.read_text(encoding="utf-8"))) if args.case else None
    cases = load_cases(args.cases) if args.cases else {}
    results = [
        evaluate_report_file(path, case=case or cases.get(path.parent.name))
        for path in args.reports
    ]
    scorecard = write_scorecard(results, args.scorecard)
    print(json.dumps({"passed": all(result.passed for result in results), "scorecard": str(scorecard)}, ensure_ascii=False))
    if not all(result.passed for result in results):
        sys.exit(1)


if __name__ == "__main__":
    main()