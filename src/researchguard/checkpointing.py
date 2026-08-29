from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


def researchguard_serializer() -> JsonPlusSerializer:
    """Allow only ResearchGuard's known Pydantic artifacts in durable checkpoints."""
    model_names = (
        "Approval",
        "Critique",
        "EvidenceItem",
        "EthicsAssessment",
        "GraphEvent",
        "Hypothesis",
        "Protocol",
        "ResearchPlan",
        "ResearchTask",
        "RevisionRecord",
        "StatisticalPlan",
        "StudyDesign",
        "ToolFailure",
    )
    return JsonPlusSerializer(
        allowed_msgpack_modules=[("researchguard.models", name) for name in model_names]
    )
