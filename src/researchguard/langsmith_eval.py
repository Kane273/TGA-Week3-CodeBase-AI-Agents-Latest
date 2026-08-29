from __future__ import annotations

import os
import uuid

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from langsmith import Client, evaluate

from researchguard.baseline import run_single_agent_baseline
from researchguard.checkpointing import researchguard_serializer
from researchguard.graph import build_graph

DATASET_NAME = "researchguard-protocol-quality-v1"
TOPICS = [
    "sleep and university learning",
    "AI tutoring and algebra transfer",
    "exercise and adult wellbeing",
    "retrieval practice and retention",
    "mindfulness and workplace stress",
    "peer feedback and writing quality",
    "screen time and adolescent sleep",
    "remote work and productivity",
    "music practice and working memory",
    "green space and anxiety",
    "simulation training and clinical accuracy",
    "spaced repetition and vocabulary",
    "team diversity and decision quality",
    "standing desks and back pain",
    "notifications and sustained attention",
    "mentoring and employee retention",
    "telehealth and appointment adherence",
    "financial education and saving behavior",
    "class size and mathematics achievement",
    "daily walking and blood pressure",
    "coding assistants and defect rates",
    "four-day workweeks and burnout",
    "virtual reality and spatial learning",
    "break reminders and eye strain",
]
EXAMPLES = [
    {
        "inputs": {"question": f"What is the causal effect of {topic}?"},
        "outputs": {"must_have_evidence": True, "must_model_attrition": True},
    }
    for topic in TOPICS
]


def run_council(inputs: dict) -> dict:
    graph = build_graph(MemorySaver(serde=researchguard_serializer()))
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    state = {
        "question": inputs["question"],
        "constraints": [],
        "revision": 0,
        "max_revisions": 1,
        "status": "researching",
    }
    graph.invoke(state, config=config)
    final = graph.invoke(Command(resume={"approved": True, "feedback": "eval"}), config=config)
    return {
        "has_evidence": bool(final["evidence"]),
        "verified_evidence_rate": sum(item.verified for item in final["evidence"])
        / max(len(final["evidence"]), 1),
        "models_attrition": any(
            "attrition inflation included" in value for value in final["statistics"].assumptions
        ),
        "requires_approval": final["approval"].approved,
        "unresolved_high_risks": sum(
            issue.severity in {"high", "critical"} for issue in final["protocol"].unresolved_risks
        ),
        "revision_count": final["revision"],
        "supports_collaboration": True,
    }


def grounding_evaluator(outputs: dict, reference_outputs: dict) -> dict:
    passed = (
        outputs["has_evidence"] == reference_outputs["must_have_evidence"]
        and outputs["verified_evidence_rate"] == 1
    )
    return {"key": "evidence_grounding", "score": int(passed)}


def design_safety_evaluator(outputs: dict, reference_outputs: dict) -> dict:
    passed = (
        outputs["models_attrition"] == reference_outputs["must_model_attrition"]
        and outputs["requires_approval"]
        and outputs["unresolved_high_risks"] == 0
    )
    return {"key": "design_safety", "score": int(passed)}


def collaboration_value_evaluator(outputs: dict, reference_outputs: dict) -> dict:
    if not outputs.get("supports_collaboration", False):
        return {
            "key": "collaboration_value",
            "score": None,
            "comment": "Not applicable to a single-agent baseline.",
        }
    score = int(
        outputs["verified_evidence_rate"] == 1
        and outputs["revision_count"] >= 1
        and outputs["unresolved_high_risks"] == 0
    )
    return {"key": "collaboration_value", "score": score}


def ensure_dataset(client: Client) -> None:
    if client.has_dataset(dataset_name=DATASET_NAME):
        return
    client.create_dataset(
        DATASET_NAME,
        description="Research questions with deterministic protocol-quality expectations.",
    )
    client.create_examples(dataset_name=DATASET_NAME, examples=EXAMPLES)


def main() -> None:
    if not os.getenv("LANGSMITH_API_KEY"):
        raise SystemExit("LANGSMITH_API_KEY is required to upload an evaluation experiment")
    client = Client()
    ensure_dataset(client)
    evaluators = [grounding_evaluator, design_safety_evaluator, collaboration_value_evaluator]
    evaluate(
        run_council,
        data=DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix="researchguard-council",
        description="Multi-agent council quality and governance evaluation",
        client=client,
    )
    evaluate(
        run_single_agent_baseline,
        data=DATASET_NAME,
        evaluators=evaluators,
        experiment_prefix="researchguard-single-agent-baseline",
        description="One-pass baseline using the same questions for comparison",
        client=client,
    )


if __name__ == "__main__":
    main()
