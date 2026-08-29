# ResearchGuard evaluation results

Measured on 2026-08-28 with `researchguard-local-eval` against the committed 24-question dataset.

| End-to-end measure | Multi-agent council | Single-agent baseline |
|---|---:|---:|
| Task completion | 24/24 (100%) | 24/24 (100%) |
| Evidence grounding | 24/24 (100%) | 24/24 (100%) |
| Design safety | 24/24 (100%) | 24/24 (100%) |
| Collaboration value | 24/24 (100%) | N/A—single-agent system |

Task completion requires verified evidence, attrition modeling, human review, and zero unresolved
high or critical risks. Both systems can create a safe one-pass deterministic draft when given
equivalent topic-specific evidence. ResearchGuard's measured advantage is collaboration: its
specialists critique and revise the draft, retain provenance, recover through explicit graph
paths, and pause at human interrupts. The baseline produces no critique or revision record.

The single-agent baseline is a credible one-pass randomized design with power, attrition,
human-review requirements, and the same topic coverage. Collaboration value is not applicable
to the baseline because a one-pass system has no inter-agent critique or revision to evaluate.

The full deterministic benchmark completed locally in approximately 0.5 seconds. This establishes
that all 24 offline workflows finish well below three minutes; it does not estimate live model
or network latency.

These results measure deterministic orchestration, governance, and recovery behavior. They do
not establish live-model answer quality or the quality of external scholarly sources. Hosted
LangSmith experiments and live PubMed/Crossref runs require the corresponding credentials and
network access.

Reproduce the benchmark with:

```bash
python -m researchguard.local_eval
```
