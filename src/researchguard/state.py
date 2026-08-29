from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from researchguard.models import (
    Approval,
    Critique,
    EthicsAssessment,
    EvidenceItem,
    GraphEvent,
    Hypothesis,
    Protocol,
    ResearchPlan,
    RevisionRecord,
    StatisticalPlan,
    StudyDesign,
    ToolFailure,
)


class ResearchState(TypedDict, total=False):
    question: str
    constraints: list[str]
    owner_id: str
    showcase_mode: bool
    force_offline: bool
    research_plan: ResearchPlan
    evidence_source: str
    evidence: Annotated[list[EvidenceItem], operator.add]
    tool_failures: Annotated[list[ToolFailure], operator.add]
    warnings: Annotated[list[str], operator.add]
    events: Annotated[list[GraphEvent], operator.add]
    hypothesis: Hypothesis
    study: StudyDesign
    ethics: EthicsAssessment
    ethics_approval: Approval
    statistics: StatisticalPlan
    critiques: list[Critique]
    critique_history: Annotated[list[Critique], operator.add]
    revision_history: Annotated[list[RevisionRecord], operator.add]
    protocol: Protocol
    approval: Approval
    revision: int
    max_revisions: int
    status: Literal[
        "planning", "researching", "recovering", "designing", "reviewing", "approval", "complete"
    ]
