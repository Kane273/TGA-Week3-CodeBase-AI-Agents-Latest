import json

import anyio
import pytest

mcp_module = pytest.importorskip("mcp")

from mcp import Client

from researchguard.mcp_server import (
    about_researchguard,
    design_research_study,
    estimate_study_sample_size,
    mcp,
    screen_claim_support,
    search_research_evidence,
)


def test_mcp_tools_are_bounded_and_structured():
    evidence = search_research_evidence("AI tutor algebra", "demo", 2)
    estimate = estimate_study_sample_size(0.4, 0.8)
    support = screen_claim_support(
        "AI tutoring improves algebra performance",
        "A controlled study found that AI tutoring improved algebra performance.",
    )
    assert len(evidence) == 2
    assert estimate["total_sample_size"] > 2
    assert 0 <= support["score"] <= 1


def test_mcp_boundary_exposes_no_writes():
    about = about_researchguard()
    prompt = design_research_study("Does retrieval improve factuality?")
    assert '"writes_exposed": false' in about
    assert "do not claim the protocol is approved" in prompt


def test_mcp_protocol_discovers_and_calls_tools():
    async def exercise_protocol():
        async with Client(mcp) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert "search_research_evidence" in names
            assert "get_research_protocol" in names
            assert not names.intersection({"approve_protocol", "delete_run", "edit_protocol"})
            result = await client.call_tool(
                "estimate_study_sample_size", {"effect_size": 0.4, "power": 0.8}
            )
            payload = json.loads(result.content[0].text)
            assert not result.is_error
            assert payload["total_sample_size"] > 2

    anyio.run(exercise_protocol)
