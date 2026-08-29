from __future__ import annotations

import json
import os
from typing import Any, TypeVar

from pydantic import BaseModel

from researchguard.models import (
    Critique,
    EthicsAssessment,
    EvidenceBundle,
    GraphEvent,
    Hypothesis,
    ResearchPlan,
    ResearchTask,
    RevisionRecord,
    StatisticalPlan,
    StudyDesign,
    ToolFailure,
)
from researchguard.quality import audit_design
from researchguard.state import ResearchState
from researchguard.tools import (
    estimate_two_arm_sample_size,
    search_corpus,
    search_crossref,
    search_demo_corpus,
    search_pubmed,
    verify_citation,
    verify_claim_support,
)

T = TypeVar("T", bound=BaseModel)


SYSTEM_ROLES = {
    "planner": "You decompose research questions into bounded specialist tasks with testable success criteria.",
    "literature": "You are a careful literature analyst. Never invent citations.",
    "hypothesis": "You formulate specific, falsifiable hypotheses.",
    "methods": "You design controlled, ethical, reproducible studies.",
    "ethics": "You are a research ethics reviewer. Escalate risks involving consent, vulnerable groups, privacy, deception, or safety.",
    "statistics": "You are a conservative statistician who states assumptions.",
    "skeptic": "You are a hostile but constructive peer reviewer.",
}


AGENT_TOOLS = {
    "planner": [],
    "literature": [
        search_pubmed,
        search_crossref,
        search_demo_corpus,
        verify_citation,
        verify_claim_support,
    ],
    "hypothesis": [verify_citation],
    "methods": [],
    "ethics": [],
    "statistics": [estimate_two_arm_sample_size],
    "skeptic": [verify_citation, estimate_two_arm_sample_size],
}


def planner_agent(state: ResearchState) -> dict:
    live = _live_structured(
        "planner",
        ResearchPlan,
        {"question": state["question"], "constraints": state.get("constraints", [])},
    )
    evidence_sources = (
        ["demo-primary", "showcase-failure", "demo-secondary"]
        if state.get("showcase_mode")
        else ["demo-primary", "demo-secondary", "demo-tertiary"]
    )
    plan = live or ResearchPlan(
        rationale="Separate evidence discovery, causal design, statistical validity, and adversarial review.",
        tasks=[
            ResearchTask(
                owner="literature",
                objective="Find traceable prior evidence.",
                success_criterion="Every item has a verifiable source.",
            ),
            ResearchTask(
                owner="hypothesis",
                objective="State a falsifiable causal claim.",
                success_criterion="A null result can disconfirm it.",
            ),
            ResearchTask(
                owner="methods",
                objective="Design a controlled study.",
                success_criterion="Comparator and bias controls are explicit.",
            ),
            ResearchTask(
                owner="statistics",
                objective="Create a powered analysis plan.",
                success_criterion="Assumptions and sample size are explicit.",
            ),
            ResearchTask(
                owner="ethics",
                objective="Review consent, privacy, vulnerable populations, and participant safety.",
                success_criterion="Critical ethics risks require explicit human review.",
            ),
            ResearchTask(
                owner="skeptic",
                objective="Attack the proposed protocol.",
                success_criterion="High-risk defects trigger revision.",
            ),
        ],
        evidence_sources=evidence_sources,
    )
    return {
        "research_plan": plan,
        "events": [
            GraphEvent(
                node="research_planner", message=f"Dispatched {len(plan.tasks)} specialist tasks."
            )
        ],
    }


def _live_structured(role: str, schema: type[T], payload: dict[str, Any]) -> T | None:
    if os.getenv("RESEARCHGUARD_MODE", "demo") != "live":
        return None
    try:
        from langchain.agents import create_agent
        from langchain_openai import ChatOpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install ResearchGuard with the 'openai' extra for live mode") from exc
    model = ChatOpenAI(model=os.getenv("RESEARCHGUARD_MODEL", "gpt-4.1-mini"), temperature=0)
    agent = create_agent(
        model=model,
        tools=AGENT_TOOLS[role],
        system_prompt=SYSTEM_ROLES[role],
        response_format=schema,
        name=f"researchguard_{role}_agent",
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": json.dumps(payload, default=str)}]}
    )
    return result["structured_response"]


def _ground_evidence(evidence: list, question: str) -> list:
    verified = []
    for item in evidence:
        citation = verify_citation.invoke({"source": item.source, "identifier": item.identifier})
        support = verify_claim_support.invoke(
            {"claim": item.claim or item.finding, "abstract": item.abstract}
        )
        relevance = verify_claim_support.invoke(
            {"claim": question, "abstract": f"{item.title}. {item.abstract}"}
        )
        item.supporting_passage = support["passage"]
        item.entailment_score = support["score"]
        item.relevance_score = relevance["score"]
        item.verified = citation["verified"] and support["supported"] and relevance["supported"]
        if item.verified:
            verified.append(item)
    return verified


def literature_agent(state: ResearchState) -> dict:
    source = state.get("evidence_source", "demo-primary")
    try:
        if source == "showcase-failure":
            raise RuntimeError("Guided showcase: simulated scholarly database outage")
        live = None
        if not state.get("force_offline"):
            live = _live_structured(
                "literature",
                EvidenceBundle,
                {"question": state["question"], "required_source": source},
            )
        if live:
            evidence = live.items
        else:
            ranked = search_corpus(state["question"])
            index = {"demo-primary": 0, "demo-secondary": 1, "demo-tertiary": 2}.get(source, 0)
            evidence = ranked[index : index + 1]
        verified = _ground_evidence(evidence, state["question"])
        return {
            "evidence": verified,
            "events": [
                GraphEvent(
                    node=f"evidence_worker:{source}",
                    message=f"Verified {len(verified)} evidence item(s).",
                )
            ],
        }
    except Exception as exc:  # noqa: BLE001 - agent boundary converts tool failures into graph state
        return {
            "tool_failures": [ToolFailure(tool=source, error=str(exc)[:300])],
            "events": [
                GraphEvent(
                    node=f"evidence_worker:{source}", message=str(exc)[:160], status="failed"
                )
            ],
        }


def fallback_literature_agent(state: ResearchState) -> dict:
    """Credential-free recovery path that never calls a model or remote source."""
    evidence = _ground_evidence(search_corpus(state["question"])[:1], state["question"])
    if not evidence:
        from researchguard.models import EvidenceItem

        question = state["question"]
        synthetic = EvidenceItem(
            title=f"Synthetic demonstration record: {question}",
            finding="This offline-only record demonstrates provenance and orchestration behavior.",
            claim=question,
            abstract=f"A synthetic demonstration examined the question: {question}",
            source="demo://synthetic-fallback",
            strength="low",
        )
        evidence = _ground_evidence([synthetic], question)
    return {
        "evidence": evidence,
        "warnings": ["All live evidence sources failed; used the auditable fallback corpus."],
        "status": "recovering",
        "events": [
            GraphEvent(
                node="fallback_evidence", message="Recovered with local corpus.", status="warning"
            )
        ],
    }


def _demo_design(question: str) -> tuple[Hypothesis, StudyDesign, float]:
    """Return domain-specific offline artifacts instead of one generic demo protocol."""
    text = question.lower()
    if "hallucination" in text or "retrieval-augmented" in text:
        return (
            Hypothesis(
                statement="RAG answers have a lower blinded factual-error rate than answers from the same model without retrieval.",
                mechanism="Relevant retrieved passages ground claims in inspectable source text.",
                falsifier="The preregistered factual-error reduction is absent or retrieval increases errors.",
            ),
            StudyDesign(
                design="Preregistered paired benchmark with blinded expert adjudication",
                population="A stratified set of 240 technical-support questions with no customer personal data",
                intervention="The target language model with retrieval from a versioned support corpus",
                comparator="The identical model and prompt without retrieval",
                outcome="Adjudicated factual errors per answer and citation precision",
                duration="Two evaluation rounds over 3 weeks",
                controls=[
                    "fixed model version and temperature",
                    "randomized answer order",
                    "blinded dual expert rating",
                    "locked retrieval corpus",
                ],
            ),
            0.30,
        )
    if "burnout" in text or "focus time" in text:
        return (
            Hypothesis(
                statement="Protected focus blocks reduce developer burnout scores without decreasing completed delivery points.",
                mechanism="Fewer interruptions improve perceived control and cognitive recovery.",
                falsifier="Burnout does not improve or delivery quality crosses the non-inferiority margin.",
            ),
            StudyDesign(
                design="Preregistered cluster-randomized team trial",
                population="Consenting software engineers from at least 12 product teams",
                intervention="Two protected 90-minute focus blocks on four workdays each week",
                comparator="Usual team scheduling and interruption practices",
                outcome="Change in validated burnout score with delivery-quality non-inferiority",
                duration="10 weeks with a 4-week follow-up",
                controls=[
                    "team-level allocation",
                    "baseline workload adjustment",
                    "blinded outcome analysis",
                    "no collection of private message content",
                ],
            ),
            0.35,
        )
    if "security defect" in text or "security code review" in text:
        return (
            Hypothesis(
                statement="AI-assisted reviewers detect a higher proportion of seeded security defects than unaided reviewers.",
                mechanism="The agent supplies an additional systematic vulnerability-search pass.",
                falsifier="Confirmed defect recall does not improve or false-positive workload exceeds the preset threshold.",
            ),
            StudyDesign(
                design="Preregistered randomized crossover code-review experiment",
                population="Consenting professional developers reviewing versioned synthetic repositories",
                intervention="Code review with AI-agent findings and source-linked explanations",
                comparator="Standard review using the same IDE and time limit",
                outcome="Human-confirmed seeded-vulnerability recall and false-positive rate",
                duration="Four review sessions across 2 weeks",
                controls=[
                    "counterbalanced task order",
                    "equal review time",
                    "blinded defect adjudication",
                    "human confirmation before recording any finding",
                ],
            ),
            0.45,
        )
    if "spaced retrieval" in text or "certification" in text:
        return (
            Hypothesis(
                statement="Spaced retrieval produces higher delayed certification-test scores than time-matched restudy.",
                mechanism="Effortful recall distributed over time strengthens durable retrieval pathways.",
                falsifier="The delayed-test advantage is absent or practically negligible.",
            ),
            StudyDesign(
                design="Preregistered parallel-group randomized learning trial",
                population="Consenting engineers preparing for the same technical certification",
                intervention="Adaptive spaced retrieval quizzes using the assigned curriculum",
                comparator="Time-matched rereading of identical curriculum content",
                outcome="Score on a blinded four-week delayed retention test",
                duration="6 weeks plus a 4-week delayed test",
                controls=[
                    "equal total study time",
                    "baseline knowledge stratification",
                    "locked assessment items",
                    "intention-to-treat analysis",
                ],
            ),
            0.40,
        )
    if "exercise" in text and "mood" in text:
        return (
            Hypothesis(
                statement="A structured exercise program improves validated mood scores among remote knowledge workers.",
                mechanism="Regular activity supports stress regulation and behavioral activation.",
                falsifier="Mood change is absent after adjustment for baseline wellbeing and adherence.",
            ),
            StudyDesign(
                design="Preregistered parallel-group randomized controlled trial",
                population="Consenting remote knowledge workers with medical exercise clearance",
                intervention="Three supervised 30-minute moderate exercise sessions per week",
                comparator="Attention-matched wellbeing education without prescribed exercise",
                outcome="Change in validated wellbeing and mood score",
                duration="8 weeks with a 4-week follow-up",
                controls=[
                    "baseline activity adjustment",
                    "wearable-based adherence",
                    "blinded outcome assessment",
                    "adverse-event monitoring",
                ],
            ),
            0.38,
        )
    if "ai tutor" in text or "algebra" in text:
        return (
            Hypothesis(
                statement="AI-tutor practice improves algebra far-transfer scores relative to time-matched digital practice.",
                mechanism="Adaptive feedback targets misconceptions and varies practice contexts.",
                falsifier="The preregistered far-transfer difference is absent or limited to practiced items.",
            ),
            StudyDesign(
                design="Preregistered classroom-cluster randomized controlled trial",
                population="Consenting first-year students enrolled in introductory algebra",
                intervention="Three weekly sessions with an adaptive AI algebra tutor",
                comparator="Time-matched non-adaptive digital algebra exercises",
                outcome="Blinded far-transfer algebra assessment score",
                duration="8 weeks with a 4-week retention test",
                controls=[
                    "classroom-level allocation",
                    "baseline algebra adjustment",
                    "equal practice time",
                    "blinded outcome scoring",
                ],
            ),
            0.40,
        )
    return (
        Hypothesis(
            statement=f"A controlled intervention related to '{question}' changes the primary outcome.",
            mechanism="The intervention changes exposure while measured covariates reduce alternative explanations.",
            falsifier="The preregistered effect is absent or practically negligible.",
        ),
        StudyDesign(
            design="Preregistered, parallel-group randomized controlled trial",
            population="Consenting adults meeting prespecified inclusion criteria",
            intervention="Structured exposure defined from the research question",
            comparator="Attention-matched control condition",
            outcome="Validated primary outcome measured by blinded assessors",
            duration="8 weeks with a 4-week follow-up",
            controls=[
                "allocation concealment",
                "blinded outcome assessment",
                "intention-to-treat analysis",
            ],
        ),
        0.40,
    )


def hypothesis_agent(state: ResearchState) -> dict:
    live = _live_structured(
        "hypothesis",
        Hypothesis,
        {"question": state["question"], "evidence": state["evidence"]},
    )
    hypothesis = live or _demo_design(state["question"])[0]
    return {
        "hypothesis": hypothesis,
        "status": "designing",
        "events": [
            GraphEvent(node="hypothesis_scientist", message="Created a falsifiable hypothesis.")
        ],
    }


def methods_agent(state: ResearchState) -> dict:
    live = _live_structured(
        "methods",
        StudyDesign,
        {
            "question": state["question"],
            "hypothesis": state["hypothesis"],
            "constraints": state.get("constraints", []),
        },
    )
    study = live or _demo_design(state["question"])[1]
    return {
        "study": study,
        "events": [
            GraphEvent(node="methods_designer", message="Defined study controls and comparator.")
        ],
    }


def ethics_agent(state: ResearchState) -> dict:
    live = _live_structured(
        "ethics",
        EthicsAssessment,
        {
            "question": state["question"],
            "study": state["study"],
            "constraints": state.get("constraints", []),
        },
    )
    if live:
        assessment = live
    else:
        population = state["study"].population.lower()
        controls = " ".join(state["study"].controls).lower()
        findings: list[Critique] = []
        safeguards: list[str] = []
        if "consent" not in population and "informed consent" not in controls:
            findings.append(
                Critique(
                    severity="critical",
                    issue="Informed consent is not explicit.",
                    recommendation="Require documented informed consent and ethics-board review.",
                )
            )
            safeguards.append("Documented informed consent")
        vulnerable = any(word in population for word in ("child", "minor", "prisoner", "patient"))
        if vulnerable and "guardian" not in controls:
            findings.append(
                Critique(
                    severity="critical",
                    issue="A vulnerable population lacks additional consent safeguards.",
                    recommendation="Add guardian consent, assent, and independent oversight.",
                )
            )
            safeguards.append("Guardian consent and independent participant advocate")
        risk = "critical" if any(item.severity == "critical" for item in findings) else "low"
        assessment = EthicsAssessment(
            risk_level=risk,
            requires_human_review=risk in {"high", "critical"},
            findings=findings,
            required_safeguards=safeguards,
        )
    return {
        "ethics": assessment,
        "critique_history": assessment.findings,
        "events": [
            GraphEvent(
                node="ethics_reviewer",
                message=f"Ethics risk: {assessment.risk_level}; {len(assessment.findings)} finding(s).",
                status="warning" if assessment.requires_human_review else "completed",
            )
        ],
    }


def ethics_revision_agent(state: ResearchState) -> dict:
    study = state["study"].model_copy(deep=True)
    before = json.dumps({"controls": study.controls}, sort_keys=True)
    safeguards = state["ethics"].required_safeguards or ["Human ethics review required"]
    for safeguard in safeguards:
        if safeguard not in study.controls:
            study.controls.append(safeguard)
    feedback = state.get("ethics_approval")
    if feedback and feedback.feedback.strip():
        study.controls.append(f"Ethics reviewer requirement: {feedback.feedback.strip()}")
    revision = state.get("revision", 0) + 1
    record = RevisionRecord(
        revision=revision,
        agent="ethics_revision_editor",
        reason="Applied mandatory ethics safeguards.",
        before=before,
        after=json.dumps({"controls": study.controls}, sort_keys=True),
    )
    return {
        "study": study,
        "revision": revision,
        "revision_history": [record],
        "events": [GraphEvent(node="ethics_revision_editor", message=record.reason)],
    }


def statistics_agent(state: ResearchState) -> dict:
    live = _live_structured(
        "statistics",
        StatisticalPlan,
        {"question": state["question"], "study": state["study"]},
    )
    effect_size = _demo_design(state["question"])[2]
    sample_size = estimate_two_arm_sample_size.invoke({"effect_size": effect_size, "power": 0.8})
    plan = live or StatisticalPlan(
        primary_metric=state["study"].outcome,
        analysis="Intention-to-treat linear model with baseline adjustment and 95% confidence interval",
        target_sample_size=sample_size,
        assumptions=[
            f"standardized effect size {effect_size:.2f}",
            "80% power",
            "two-sided alpha 0.05",
            "15% attrition buffer not included",
        ],
    )
    return {
        "statistics": plan,
        "status": "reviewing",
        "events": [
            GraphEvent(
                node="statistician", message=f"Estimated enrollment at {plan.target_sample_size}."
            )
        ],
    }


def skeptic_agent(state: ResearchState) -> dict:
    live = _live_structured(
        "skeptic",
        Critique,
        {"question": state["question"], "study": state["study"], "statistics": state["statistics"]},
    )
    critiques = [live] if live else []
    deterministic = audit_design(state["study"], state["statistics"], state.get("evidence", []))
    known = {(item.issue, item.recommendation) for item in critiques}
    critiques.extend(
        item for item in deterministic if (item.issue, item.recommendation) not in known
    )
    return {
        "critiques": critiques,
        "critique_history": critiques,
        "events": [
            GraphEvent(
                node="skeptical_reviewer", message=f"Found {len(critiques)} active issue(s)."
            )
        ],
    }


def revision_agent(state: ResearchState) -> dict:
    statistics = state["statistics"].model_copy(deep=True)
    study = state["study"].model_copy(deep=True)
    before = json.dumps(
        {"sample_size": statistics.target_sample_size, "controls": study.controls}, sort_keys=True
    )
    assumptions_text = " ".join(statistics.assumptions).lower()
    reasons: list[str] = []
    active_issues = " ".join(item.issue.lower() for item in state.get("critiques", []))
    if "allocation is not concealed" in active_issues and "allocation concealment" not in {
        value.lower() for value in study.controls
    }:
        study.controls.append("allocation concealment")
        reasons.append("Added concealed allocation after skeptical review")
    if "post-randomization exclusions" in active_issues and "intention-to-treat analysis" not in {
        value.lower() for value in study.controls
    }:
        study.controls.append("intention-to-treat analysis")
        reasons.append("Added intention-to-treat analysis after skeptical review")
    if "attrition" not in assumptions_text or "not included" in assumptions_text:
        statistics.target_sample_size = int(statistics.target_sample_size / 0.85 + 0.5)
        assumptions = [item for item in statistics.assumptions if "not included" not in item]
        assumptions.append("15% attrition inflation included")
        statistics.assumptions = assumptions
        reasons.append("Included the skeptic's attrition correction")
    approval = state.get("approval")
    if approval and not approval.approved and approval.feedback.strip():
        safeguard = f"Human-requested safeguard: {approval.feedback.strip()}"
        if safeguard not in study.controls:
            study.controls.append(safeguard)
        reasons.append(f"Applied human feedback: {approval.feedback.strip()}")
    revision = state.get("revision", 0) + 1
    after = json.dumps(
        {"sample_size": statistics.target_sample_size, "controls": study.controls}, sort_keys=True
    )
    record = RevisionRecord(
        revision=revision,
        agent="revision_editor",
        reason="; ".join(reasons) or "Revalidated protocol",
        before=before,
        after=after,
    )
    return {
        "statistics": statistics,
        "study": study,
        "revision": revision,
        "revision_history": [record],
        "events": [GraphEvent(node="revision_editor", message=record.reason)],
    }
