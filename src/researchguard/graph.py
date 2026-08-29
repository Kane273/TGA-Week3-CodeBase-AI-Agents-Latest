from __future__ import annotations

from functools import wraps
from time import perf_counter
from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from researchguard.agents import (
    ethics_agent,
    ethics_revision_agent,
    fallback_literature_agent,
    hypothesis_agent,
    literature_agent,
    methods_agent,
    planner_agent,
    revision_agent,
    skeptic_agent,
    statistics_agent,
)
from researchguard.models import Approval, GraphEvent, Protocol
from researchguard.state import ResearchState


def timed_node(name, function):
    """Attach elapsed time to a node's event without changing agent behavior."""

    @wraps(function)
    def wrapped(state):
        started = perf_counter()
        result = function(state)
        elapsed = round((perf_counter() - started) * 1000, 2)
        events = result.setdefault("events", [])
        matching = [event for event in events if event.node.split(":")[0] == name]
        if matching:
            matching[-1].duration_ms = elapsed
        else:
            events.append(GraphEvent(node=name, message="Completed.", duration_ms=elapsed))
        return result

    return wrapped


def route_review(state: ResearchState) -> Literal["revise", "synthesize"]:
    severe = any(item.severity in {"high", "critical"} for item in state["critiques"])
    return (
        "revise"
        if severe and state.get("revision", 0) < state.get("max_revisions", 1)
        else "synthesize"
    )


def synthesize_agent(state: ResearchState) -> dict:
    protocol = Protocol(
        question=state["question"],
        hypothesis=state["hypothesis"],
        study=state["study"],
        statistics=state["statistics"],
        evidence=state["evidence"],
        ethics=state["ethics"],
        unresolved_risks=state["critiques"],
        critique_history=state.get("critique_history", []),
        revision_history=state.get("revision_history", []),
        warnings=state.get("warnings", []),
        revision=state.get("revision", 0),
    )
    return {
        "protocol": protocol,
        "status": "approval",
        "events": [GraphEvent(node="protocol_synthesizer", message="Prepared auditable protocol.")],
    }


def dispatch_evidence(state: ResearchState) -> list[Send]:
    return [
        Send(
            "evidence_worker",
            {
                "question": state["question"],
                "evidence_source": source,
                "showcase_mode": state.get("showcase_mode", False),
                "force_offline": state.get("force_offline", False),
            },
        )
        for source in state["research_plan"].evidence_sources
    ]


def evidence_gate(state: ResearchState) -> dict:
    failures = state.get("tool_failures", [])
    if failures and state.get("evidence"):
        return {
            "warnings": [f"Partial evidence outage: {len(failures)} source(s) failed."],
            "events": [
                GraphEvent(
                    node="evidence_gate",
                    message="Continued with verified partial evidence.",
                    status="warning",
                )
            ],
        }
    return {"events": [GraphEvent(node="evidence_gate", message="Evidence checks completed.")]}


def route_evidence(state: ResearchState) -> Literal["continue", "fallback"]:
    return "continue" if state.get("evidence") else "fallback"


def fallback_evidence(state: ResearchState) -> dict:
    return fallback_literature_agent(state)


def route_ethics(state: ResearchState) -> Literal["continue", "human_review"]:
    needs_review = state["ethics"].requires_human_review and not state.get("ethics_approval")
    return "human_review" if needs_review else "continue"


def ethics_human_review(state: ResearchState) -> dict:
    response = interrupt(
        {
            "kind": "ethics_approval",
            "question": state["question"],
            "ethics": state["ethics"].model_dump(mode="json"),
            "prompt": "Review mandatory ethics safeguards and provide approval or feedback.",
        }
    )
    approval = Approval.model_validate(response)
    return {
        "ethics_approval": approval,
        "events": [
            GraphEvent(
                node="ethics_human_review",
                message="Human reviewed mandatory ethics safeguards.",
                status="warning",
            )
        ],
    }


def human_approval(state: ResearchState) -> dict:
    response = interrupt(
        {
            "kind": "protocol_approval",
            "question": state["question"],
            "revision": state.get("revision", 0),
            "protocol": state["protocol"].model_dump(mode="json"),
            "prompt": "Approve this protocol? Resume with {'approved': bool, 'feedback': str}.",
        }
    )
    approval = Approval.model_validate(response)
    return {
        "approval": approval,
        "status": "complete" if approval.approved else "reviewing",
        "events": [
            GraphEvent(
                node="human_approval",
                message="Approved protocol."
                if approval.approved
                else f"Requested revision: {approval.feedback}",
            )
        ],
    }


def route_approval(state: ResearchState) -> Literal["complete", "revise"]:
    return "complete" if state["approval"].approved else "revise"


def complete_agent(state: ResearchState) -> dict:
    return {
        "status": "complete",
        "events": [GraphEvent(node="complete", message="Protocol finalized with human approval.")],
    }


def build_graph(checkpointer=None):
    builder = StateGraph(ResearchState)
    builder.add_node("research_planner", timed_node("research_planner", planner_agent))
    builder.add_node("evidence_worker", timed_node("evidence_worker", literature_agent))
    builder.add_node("evidence_gate", timed_node("evidence_gate", evidence_gate))
    builder.add_node("fallback_evidence", timed_node("fallback_evidence", fallback_evidence))
    builder.add_node("hypothesis_scientist", timed_node("hypothesis_scientist", hypothesis_agent))
    builder.add_node("methods_designer", timed_node("methods_designer", methods_agent))
    builder.add_node("ethics_reviewer", timed_node("ethics_reviewer", ethics_agent))
    builder.add_node("ethics_human_review", timed_node("ethics_human_review", ethics_human_review))
    builder.add_node(
        "ethics_revision_editor", timed_node("ethics_revision_editor", ethics_revision_agent)
    )
    builder.add_node("statistician", timed_node("statistician", statistics_agent))
    builder.add_node("skeptical_reviewer", timed_node("skeptical_reviewer", skeptic_agent))
    builder.add_node("revision_editor", timed_node("revision_editor", revision_agent))
    builder.add_node("protocol_synthesizer", timed_node("protocol_synthesizer", synthesize_agent))
    builder.add_node("human_approval", timed_node("human_approval", human_approval))
    builder.add_node("complete", timed_node("complete", complete_agent))

    builder.add_edge(START, "research_planner")
    builder.add_conditional_edges("research_planner", dispatch_evidence, ["evidence_worker"])
    builder.add_edge("evidence_worker", "evidence_gate")
    builder.add_conditional_edges(
        "evidence_gate",
        route_evidence,
        {"continue": "hypothesis_scientist", "fallback": "fallback_evidence"},
    )
    builder.add_edge("fallback_evidence", "hypothesis_scientist")
    builder.add_edge("hypothesis_scientist", "methods_designer")
    builder.add_edge("methods_designer", "ethics_reviewer")
    builder.add_conditional_edges(
        "ethics_reviewer",
        route_ethics,
        {"continue": "statistician", "human_review": "ethics_human_review"},
    )
    builder.add_edge("ethics_human_review", "ethics_revision_editor")
    builder.add_edge("ethics_revision_editor", "ethics_reviewer")
    builder.add_edge("statistician", "skeptical_reviewer")
    builder.add_conditional_edges(
        "skeptical_reviewer",
        route_review,
        {"revise": "revision_editor", "synthesize": "protocol_synthesizer"},
    )
    builder.add_edge("revision_editor", "skeptical_reviewer")
    builder.add_edge("protocol_synthesizer", "human_approval")
    builder.add_conditional_edges(
        "human_approval", route_approval, {"complete": "complete", "revise": "revision_editor"}
    )
    builder.add_edge("complete", END)
    return builder.compile(checkpointer=checkpointer)
