from researchguard.local_eval import _passes, run_local_benchmark


def test_completion_requires_end_to_end_safety_and_governance():
    complete = {
        "has_evidence": True,
        "verified_evidence_rate": 1,
        "models_attrition": True,
        "requires_approval": True,
        "unresolved_high_risks": 0,
        "revision_count": 1,
        "supports_collaboration": True,
    }
    assert _passes(complete)["task_completion"]
    assert not _passes({**complete, "requires_approval": False})["task_completion"]


def test_committed_benchmark_result_remains_reproducible():
    result = run_local_benchmark()
    assert result["council"]["passes"]["task_completion"] == 24
    assert result["council"]["passes"]["evidence_grounding"] == 24
    assert result["single_agent_baseline"]["passes"]["task_completion"] == 24
    assert result["single_agent_baseline"]["passes"]["evidence_grounding"] == 24
    assert result["council"]["passes"]["collaboration_value"] == 24
    assert result["single_agent_baseline"]["evaluated"]["collaboration_value"] == 0
    assert result["single_agent_baseline"]["rates"]["collaboration_value"] is None
