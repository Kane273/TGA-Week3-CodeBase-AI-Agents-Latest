from __future__ import annotations

from researchguard.models import Critique, EvidenceItem, StatisticalPlan, StudyDesign


def audit_design(
    study: StudyDesign, statistics: StatisticalPlan, evidence: list[EvidenceItem]
) -> list[Critique]:
    """Deterministic safety net used by the skeptic and adversarial evaluations."""
    issues: list[Critique] = []
    controls = " ".join(study.controls).lower()
    assumptions = " ".join(statistics.assumptions).lower()
    design = study.design.lower()

    def add(issue: str, recommendation: str, severity: str = "high") -> None:
        issues.append(Critique(severity=severity, issue=issue, recommendation=recommendation))

    if not study.comparator.strip() or "none" in study.comparator.lower():
        add("The study has no credible comparator.", "Add an attention-matched control group.")
    if "random" not in design:
        add(
            "Allocation may create selection bias.",
            "Use randomized allocation or justify an alternative.",
        )
    if "allocation concealment" not in controls:
        add("Allocation is not concealed.", "Conceal the allocation sequence.")
    if "blinded" not in controls:
        add("Outcome assessment may be biased.", "Blind outcome assessors.")
    if "intention-to-treat" not in controls:
        add("Post-randomization exclusions may bias results.", "Use intention-to-treat analysis.")
    if "consent" not in study.population.lower():
        add(
            "Consent protections are not explicit.",
            "Require informed consent and ethics review.",
            "critical",
        )
    if not study.intervention.strip():
        add("The intervention is not operationalized.", "Specify dose, frequency, and delivery.")
    if not study.outcome.strip() or "unspecified" in study.outcome.lower():
        add("The primary outcome is not prespecified.", "Name one validated primary outcome.")
    if "validated" not in study.outcome.lower():
        add(
            "Outcome validity is unclear.", "Use and cite a validated outcome instrument.", "medium"
        )
    if not study.duration.strip():
        add("Follow-up duration is missing.", "Specify intervention and follow-up windows.")
    if statistics.target_sample_size < 50:
        add("The study is likely underpowered.", "Provide a justified power analysis.")
    if "attrition" not in assumptions or "not included" in assumptions:
        add(
            "The stated sample size excludes its attrition buffer.",
            "Increase enrollment for attrition.",
        )
    if "multiple comparisons" in assumptions and "correction" not in assumptions:
        add(
            "Multiple comparisons inflate false positives.", "Prespecify a multiplicity correction."
        )
    if "data leakage" in assumptions and "prevented" not in assumptions:
        add(
            "The analysis permits data leakage.",
            "Separate training and evaluation data.",
            "critical",
        )
    if not evidence:
        add(
            "The protocol has no verified evidence.",
            "Retrieve and verify claim-level sources.",
            "critical",
        )
    elif any(not item.verified for item in evidence):
        add(
            "At least one claim lacks entailment verification.",
            "Remove or manually verify unsupported claims.",
        )
    return issues
