import pytest

from researchguard.models import EvidenceItem, StatisticalPlan, StudyDesign
from researchguard.quality import audit_design


def safe_components():
    study = StudyDesign(
        design="Preregistered randomized controlled trial",
        population="Consenting adults",
        intervention="Eight weekly structured sessions",
        comparator="Attention-matched control",
        outcome="Validated primary outcome",
        duration="8 weeks",
        controls=[
            "allocation concealment",
            "blinded outcome assessment",
            "intention-to-treat analysis",
        ],
    )
    statistics = StatisticalPlan(
        primary_metric="Validated primary outcome",
        analysis="Baseline-adjusted linear model",
        target_sample_size=200,
        assumptions=["15% attrition inflation included"],
    )
    evidence = [
        EvidenceItem(
            title="Verified study",
            finding="The intervention affected the outcome.",
            claim="Intervention affects outcome.",
            abstract="The intervention affects the measured outcome.",
            source="demo://verified",
            verified=True,
            entailment_score=0.8,
        )
    ]
    return study, statistics, evidence


CASES = [
    ("no_comparator", "comparator"),
    ("selection_bias", "selection bias"),
    ("no_concealment", "concealed"),
    ("no_blinding", "biased"),
    ("no_itt", "exclusions"),
    ("no_consent", "Consent"),
    ("no_intervention", "operationalized"),
    ("no_outcome", "prespecified"),
    ("invalid_outcome", "validity"),
    ("no_duration", "duration"),
    ("underpowered", "underpowered"),
    ("no_attrition", "attrition"),
    ("attrition_excluded", "attrition"),
    ("multiple_comparisons", "Multiple comparisons"),
    ("data_leakage", "data leakage"),
    ("no_evidence", "no verified evidence"),
    ("unverified_evidence", "entailment verification"),
    ("combined_design", "comparator"),
    ("combined_analysis", "exclusions"),
    ("combined_ethics", "Consent"),
]


@pytest.mark.parametrize(("case", "expected"), CASES)
def test_adversarial_defects_are_detected(case, expected):
    study, statistics, evidence = safe_components()
    if case in {"no_comparator", "combined_design"}:
        study.comparator = "None"
    if case == "selection_bias":
        study.design = "Observational cohort"
    if case == "no_concealment":
        study.controls.remove("allocation concealment")
    if case == "no_blinding":
        study.controls.remove("blinded outcome assessment")
    if case in {"no_itt", "combined_analysis"}:
        study.controls.remove("intention-to-treat analysis")
    if case in {"no_consent", "combined_ethics"}:
        study.population = "Adults recruited online"
    if case == "no_intervention":
        study.intervention = ""
    if case == "no_outcome":
        study.outcome = "Unspecified"
    if case == "invalid_outcome":
        study.outcome = "Custom score"
    if case == "no_duration":
        study.duration = ""
    if case in {"underpowered", "combined_design"}:
        statistics.target_sample_size = 20
    if case == "no_attrition":
        statistics.assumptions = []
    if case == "attrition_excluded":
        statistics.assumptions = ["15% attrition not included"]
    if case == "multiple_comparisons":
        statistics.assumptions.append("multiple comparisons planned")
    if case == "data_leakage":
        statistics.assumptions.append("data leakage possible")
    if case in {"no_evidence", "combined_ethics"}:
        evidence = []
    if case == "unverified_evidence":
        evidence[0].verified = False

    issues = audit_design(study, statistics, evidence)
    assert any(expected.lower() in issue.issue.lower() for issue in issues)
