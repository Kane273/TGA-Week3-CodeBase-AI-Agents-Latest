from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    title: str
    finding: str
    source: str
    strength: Literal["low", "medium", "high"] = "medium"
    identifier: str | None = None
    abstract: str = ""
    claim: str = ""
    supporting_passage: str = ""
    entailment_score: float = Field(default=0.0, ge=0, le=1)
    relevance_score: float = Field(default=0.0, ge=0, le=1)
    verified: bool = False


class EvidenceBundle(BaseModel):
    items: list[EvidenceItem]


class ResearchTask(BaseModel):
    owner: Literal["literature", "hypothesis", "methods", "ethics", "statistics", "skeptic"]
    objective: str
    success_criterion: str


class ResearchPlan(BaseModel):
    rationale: str
    tasks: list[ResearchTask] = Field(min_length=3, max_length=8)
    evidence_sources: list[str] = Field(min_length=1, max_length=4)


class Hypothesis(BaseModel):
    statement: str
    mechanism: str
    falsifier: str


class StudyDesign(BaseModel):
    design: str
    population: str
    intervention: str
    comparator: str
    outcome: str
    duration: str
    controls: list[str] = Field(default_factory=list)


class StatisticalPlan(BaseModel):
    primary_metric: str
    analysis: str
    target_sample_size: int = Field(ge=2)
    assumptions: list[str] = Field(default_factory=list)


class Critique(BaseModel):
    severity: Literal["low", "medium", "high", "critical"]
    issue: str
    recommendation: str


class EthicsAssessment(BaseModel):
    risk_level: Literal["low", "medium", "high", "critical"]
    requires_human_review: bool
    findings: list[Critique] = Field(default_factory=list)
    required_safeguards: list[str] = Field(default_factory=list)


class ToolFailure(BaseModel):
    tool: str
    error: str
    recoverable: bool = True


class RevisionRecord(BaseModel):
    revision: int
    agent: str
    reason: str
    before: str
    after: str


class GraphEvent(BaseModel):
    node: str
    message: str
    status: Literal["completed", "warning", "failed"] = "completed"
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    duration_ms: float | None = Field(default=None, ge=0)


class Protocol(BaseModel):
    question: str
    hypothesis: Hypothesis
    study: StudyDesign
    statistics: StatisticalPlan
    evidence: list[EvidenceItem]
    ethics: EthicsAssessment
    unresolved_risks: list[Critique]
    critique_history: list[Critique] = Field(default_factory=list)
    revision_history: list[RevisionRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    revision: int


class Approval(BaseModel):
    approved: bool
    feedback: str = ""
