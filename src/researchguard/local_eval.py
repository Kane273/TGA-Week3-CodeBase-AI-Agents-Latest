from __future__ import annotations

import json
import time
from datetime import UTC, datetime

from researchguard.baseline import run_single_agent_baseline
from researchguard.langsmith_eval import EXAMPLES, run_council


def _passes(metrics: dict) -> dict[str, bool | None]:
    return {
        "task_completion": bool(
            metrics["has_evidence"]
            and metrics["models_attrition"]
            and metrics["requires_approval"]
            and metrics["unresolved_high_risks"] == 0
        ),
        "evidence_grounding": bool(
            metrics["has_evidence"] and metrics["verified_evidence_rate"] == 1
        ),
        "design_safety": bool(
            metrics["models_attrition"]
            and metrics["requires_approval"]
            and metrics["unresolved_high_risks"] == 0
        ),
        "collaboration_value": (
            bool(
                metrics["verified_evidence_rate"] == 1
                and metrics["revision_count"] >= 1
                and metrics["unresolved_high_risks"] == 0
            )
            if metrics.get("supports_collaboration", False)
            else None
        ),
    }


def run_local_benchmark() -> dict:
    started = time.perf_counter()
    rows = []
    for example in EXAMPLES:
        question = example["inputs"]["question"]
        run_started = time.perf_counter()
        council = run_council({"question": question})
        council_seconds = time.perf_counter() - run_started
        baseline = run_single_agent_baseline({"question": question})
        rows.append(
            {
                "question": question,
                "council": council,
                "baseline": baseline,
                "council_passes": _passes(council),
                "baseline_passes": _passes(baseline),
                "council_seconds": round(council_seconds, 4),
            }
        )

    def summary(system: str) -> dict:
        count = len(rows)
        keys = next(iter(rows))[f"{system}_passes"]
        passes = {
            key: sum(row[f"{system}_passes"][key] is True for row in rows) for key in keys
        }
        evaluated = {
            key: sum(row[f"{system}_passes"][key] is not None for row in rows) for key in keys
        }
        return {
            "questions": count,
            "passes": passes,
            "evaluated": evaluated,
            "rates": {
                key: round(value / evaluated[key], 4) if evaluated[key] else None
                for key, value in passes.items()
            },
        }

    return {
        "benchmark": "researchguard-local-protocol-quality-v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "deterministic offline",
        "scope_note": "Measures orchestration behavior, not live-model or source quality.",
        "total_seconds": round(time.perf_counter() - started, 4),
        "council": summary("council"),
        "single_agent_baseline": summary("baseline"),
        "runs": rows,
    }


def main() -> None:
    print(json.dumps(run_local_benchmark(), indent=2))


if __name__ == "__main__":
    main()
