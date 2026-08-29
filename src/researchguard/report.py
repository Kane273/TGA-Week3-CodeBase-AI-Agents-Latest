from __future__ import annotations

from researchguard.models import Protocol


def protocol_markdown(protocol_data: dict) -> str:
    protocol = Protocol.model_validate(protocol_data)
    lines = [
        "# ResearchGuard Protocol",
        "",
        f"**Research question:** {protocol.question}",
        f"**Revision:** {protocol.revision}",
        "",
        "## Hypothesis",
        "",
        protocol.hypothesis.statement,
        "",
        f"**Mechanism:** {protocol.hypothesis.mechanism}",
        f"**Falsifier:** {protocol.hypothesis.falsifier}",
        "",
        "## Study design",
        "",
        f"- Design: {protocol.study.design}",
        f"- Population: {protocol.study.population}",
        f"- Intervention: {protocol.study.intervention}",
        f"- Comparator: {protocol.study.comparator}",
        f"- Outcome: {protocol.study.outcome}",
        f"- Duration: {protocol.study.duration}",
        f"- Controls: {'; '.join(protocol.study.controls)}",
        "",
        "## Statistical plan",
        "",
        f"- Target enrollment: {protocol.statistics.target_sample_size}",
        f"- Analysis: {protocol.statistics.analysis}",
        f"- Assumptions: {'; '.join(protocol.statistics.assumptions)}",
        "",
        "## Claim-level evidence",
        "",
        "| Claim | Supporting passage | Source | Support | Relevance | Verified |",
        "|---|---|---|---:|---:|:---:|",
    ]
    for item in protocol.evidence:
        claim = (item.claim or item.finding).replace("|", "\\|")
        passage = item.supporting_passage.replace("|", "\\|")
        lines.append(
            f"| {claim} | {passage} | [{item.identifier or item.title}]({item.source}) "
            f"| {item.entailment_score:.2f} | {item.relevance_score:.2f} "
            f"| {'Yes' if item.verified else 'No'} |"
        )
    lines.extend(["", "## Revision audit", ""])
    if not protocol.revision_history:
        lines.append("No revisions recorded.")
    for record in protocol.revision_history:
        lines.extend(
            [
                f"### Revision {record.revision}",
                "",
                f"**Reason:** {record.reason}",
                "",
                "```diff",
                f"- {record.before}",
                f"+ {record.after}",
                "```",
                "",
            ]
        )
    lines.extend(["## Unresolved risks", ""])
    if protocol.unresolved_risks:
        lines.extend(f"- **{risk.severity}:** {risk.issue}" for risk in protocol.unresolved_risks)
    else:
        lines.append("No unresolved high-risk defects detected by the automated review.")
    if protocol.warnings:
        lines.extend(["", "## Warnings", "", *[f"- {value}" for value in protocol.warnings]])
    lines.extend(
        [
            "",
            "## Ethics review",
            "",
            f"- Risk level: {protocol.ethics.risk_level}",
            f"- Human review required: {'Yes' if protocol.ethics.requires_human_review else 'No'}",
            f"- Required safeguards: {'; '.join(protocol.ethics.required_safeguards) or 'None'}",
        ]
    )
    lines.extend(
        [
            "",
            "---",
            "Generated as research decision support. Domain-expert and ethics review remain required.",
        ]
    )
    return "\n".join(lines)
