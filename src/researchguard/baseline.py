from __future__ import annotations

from researchguard.models import StatisticalPlan, StudyDesign
from researchguard.quality import audit_design
from researchguard.tools import (
    estimate_two_arm_sample_size,
    search_corpus,
    verify_citation,
    verify_claim_support,
)


def run_single_agent_baseline(inputs: dict) -> dict:
    """A credible one-pass baseline without specialist review or revision."""
    question = inputs["question"]
    evidence = search_corpus(question)[:1]
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
    study = StudyDesign(
        design="One-pass preregistered randomized controlled trial",
        population="Consenting adults meeting prespecified eligibility criteria",
        intervention="Structured intervention inferred from the research question",
        comparator="Attention-matched control condition",
        outcome="Validated primary outcome measured by blinded assessors",
        duration="8 weeks with a 4-week follow-up",
        controls=[
            "allocation concealment",
            "blinded outcome assessment",
            "intention-to-treat analysis",
        ],
    )
    powered_size = estimate_two_arm_sample_size.invoke({"effect_size": 0.4, "power": 0.8})
    statistics = StatisticalPlan(
        primary_metric=study.outcome,
        analysis="Intention-to-treat model with baseline adjustment and 95% confidence interval",
        target_sample_size=int(powered_size / 0.85 + 0.5),
        assumptions=[
            "standardized effect size 0.4",
            "80% power",
            "two-sided alpha 0.05",
            "15% attrition inflation included",
        ],
    )
    issues = audit_design(study, statistics, evidence)
    return {
        "has_evidence": bool(evidence),
        "verified_evidence_rate": sum(item.verified for item in evidence) / max(len(evidence), 1),
        "models_attrition": True,
        "requires_approval": True,
        "unresolved_high_risks": sum(issue.severity in {"high", "critical"} for issue in issues),
        "revision_count": 0,
        "supports_collaboration": False,
    }


def council_metrics(state: dict) -> dict:
    evidence = state.get("evidence", [])
    risks = state.get("protocol", {}).get("unresolved_risks", [])
    approval = state.get("approval")
    return {
        "has_evidence": bool(evidence),
        "verified_evidence_rate": sum(item.get("verified", False) for item in evidence)
        / max(len(evidence), 1),
        "models_attrition": any(
            "attrition inflation included" in value
            for value in state.get("statistics", {}).get("assumptions", [])
        ),
        "requires_approval": approval is None or approval.get("approved", False),
        "unresolved_high_risks": sum(
            item.get("severity") in {"high", "critical"} for item in risks
        ),
        "revision_count": state.get("revision", 0),
        "supports_collaboration": True,
    }
