from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from researchguard.agents import ethics_agent
from researchguard.checkpointing import researchguard_serializer
from researchguard.graph import build_graph, fallback_evidence, route_evidence
from researchguard.models import StudyDesign


def initial_state():
    return {
        "question": "Does sleep improve learning in university students?",
        "constraints": ["eight-week maximum"],
        "revision": 0,
        "max_revisions": 1,
        "status": "researching",
    }


def test_graph_revises_then_interrupts_for_approval():
    graph = build_graph(MemorySaver(serde=researchguard_serializer()))
    config = {"configurable": {"thread_id": "eval-approval"}}
    graph.invoke(initial_state(), config=config)
    snapshot = graph.get_state(config)

    assert snapshot.next == ("human_approval",)
    assert len(snapshot.values["research_plan"].tasks) >= 3
    assert snapshot.values["revision"] == 1
    assert any(
        "attrition inflation included" in item for item in snapshot.values["statistics"].assumptions
    )
    assert not snapshot.values["protocol"].unresolved_risks
    assert snapshot.values["protocol"].evidence
    assert snapshot.values["protocol"].ethics.risk_level == "low"
    assert all(event.timestamp for event in snapshot.values["events"])
    assert any(event.duration_ms is not None for event in snapshot.values["events"])

    final = graph.invoke(Command(resume={"approved": True, "feedback": ""}), config=config)
    assert final["status"] == "complete"
    assert final["approval"].approved is True


def test_rejection_triggers_another_revision_and_approval():
    graph = build_graph(MemorySaver(serde=researchguard_serializer()))
    config = {"configurable": {"thread_id": "eval-rejection"}}
    graph.invoke(initial_state(), config=config)
    graph.invoke(
        Command(resume={"approved": False, "feedback": "Increase safeguards"}), config=config
    )
    snapshot = graph.get_state(config)

    assert snapshot.next == ("human_approval",)
    assert snapshot.values["revision"] == 2
    assert "Increase safeguards" in snapshot.values["study"].controls[-1]
    assert "Increase safeguards" in snapshot.values["revision_history"][-1].reason


def test_evidence_outage_routes_to_offline_fallback(monkeypatch):
    monkeypatch.setenv("RESEARCHGUARD_MODE", "live")
    state = {"question": "Does sleep improve memory?", "evidence": []}
    assert route_evidence(state) == "fallback"
    recovered = fallback_evidence(state)
    assert recovered["evidence"][0].verified is True
    assert "fallback corpus" in recovered["warnings"][0]


def test_ethics_agent_flags_vulnerable_population():
    assessment = ethics_agent(
        {
            "question": "Does an intervention help minors?",
            "constraints": [],
            "study": StudyDesign(
                design="Randomized trial",
                population="Minor patients recruited from a clinic",
                intervention="Weekly sessions",
                comparator="Attention control",
                outcome="Validated outcome",
                duration="8 weeks",
                controls=["allocation concealment", "blinded outcome assessment"],
            ),
        }
    )["ethics"]
    assert assessment.requires_human_review is True
    assert assessment.risk_level == "critical"
    assert len(assessment.findings) >= 2


def test_critical_ethics_risk_creates_separate_interrupt(monkeypatch):
    import researchguard.graph as graph_module

    def risky_methods(_state):
        return {
            "study": StudyDesign(
                design="Randomized controlled trial",
                population="Minor patients",
                intervention="Weekly sessions",
                comparator="Attention control",
                outcome="Validated primary outcome",
                duration="8 weeks",
                controls=[
                    "allocation concealment",
                    "blinded outcome assessment",
                    "intention-to-treat analysis",
                ],
            )
        }

    monkeypatch.setattr(graph_module, "methods_agent", risky_methods)
    graph = graph_module.build_graph(MemorySaver(serde=researchguard_serializer()))
    config = {"configurable": {"thread_id": "ethics-escalation"}}
    state = initial_state() | {"max_revisions": 3}
    graph.invoke(state, config=config)
    snapshot = graph.get_state(config)
    assert snapshot.next == ("ethics_human_review",)

    graph.invoke(
        Command(resume={"approved": True, "feedback": "Add a participant advocate"}),
        config=config,
    )
    resumed = graph.get_state(config)
    assert resumed.next == ("human_approval",)
    assert "Guardian consent" in " ".join(resumed.values["study"].controls)
