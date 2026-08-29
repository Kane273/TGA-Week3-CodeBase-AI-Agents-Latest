from __future__ import annotations

import json
import os
from typing import Literal

from mcp.server import MCPServer

from researchguard.report import protocol_markdown
from researchguard.service import create_service
from researchguard.tools import (
    estimate_two_arm_sample_size,
    search_crossref,
    search_demo_corpus,
    search_pubmed,
    verify_citation,
    verify_claim_support,
)

mcp = MCPServer(
    "researchguard",
    title="ResearchGuard Research Tools",
    description="Read-only evidence, analysis, and protocol inspection for ResearchGuard.",
    instructions=(
        "Use these tools for research planning and evidence screening. Treat screening scores "
        "as decision support, not expert validation. Never infer approval: protocol writes and "
        "human decisions remain in the ResearchGuard application."
    ),
    version="0.4.0",
)
service = create_service(os.getenv("RESEARCHGUARD_DB", "researchguard.db"))


@mcp.tool()
def search_research_evidence(
    query: str,
    source: Literal["demo", "pubmed", "crossref"] = "demo",
    limit: int = 5,
) -> list[dict]:
    """Search an allowed evidence source. PubMed and Crossref require network access."""
    query = query.strip()
    if len(query) < 3 or len(query) > 500:
        raise ValueError("query must contain 3 to 500 characters")
    limit = max(1, min(limit, 10))
    if source == "pubmed":
        return search_pubmed.invoke({"query": query, "limit": limit})
    if source == "crossref":
        return search_crossref.invoke({"query": query, "limit": limit})
    return search_demo_corpus.invoke({"query": query})[:limit]


@mcp.tool()
def screen_claim_support(claim: str, abstract: str) -> dict:
    """Screen whether an abstract supports a claim and return the closest passage."""
    if len(claim) > 2_000 or len(abstract) > 20_000:
        raise ValueError("claim or abstract exceeds the local screening limit")
    return verify_claim_support.invoke({"claim": claim, "abstract": abstract})


@mcp.tool()
def check_citation(source: str, identifier: str | None = None) -> dict:
    """Check whether a citation has a recognized demo, PMID, or DOI source form."""
    return verify_citation.invoke({"source": source, "identifier": identifier})


@mcp.tool()
def estimate_study_sample_size(effect_size: float, power: float = 0.8) -> dict:
    """Estimate total enrollment for two equal study arms using a transparent approximation."""
    total = estimate_two_arm_sample_size.invoke({"effect_size": effect_size, "power": power})
    return {
        "total_sample_size": total,
        "per_arm": total // 2,
        "effect_size": effect_size,
        "power": power,
        "warning": "Planning approximation; confirm with a statistician.",
    }


@mcp.tool()
def list_research_runs(owner_id: str = "demo-user", include_archived: bool = False) -> list[dict]:
    """List saved ResearchGuard runs for a local workspace identity. Read-only."""
    return service.list_runs(owner_id[:200], include_archived)


@mcp.tool()
def get_research_protocol(thread_id: str, owner_id: str = "demo-user") -> dict:
    """Read a saved protocol and workflow status. Does not approve or modify it."""
    snapshot = service.get(thread_id, owner_id[:200])
    protocol = snapshot["state"].get("protocol")
    return {
        "thread_id": thread_id,
        "status": snapshot["state"].get("status"),
        "next": snapshot.get("next", []),
        "protocol": protocol,
        "human_action_required": bool(snapshot.get("next")),
    }


@mcp.resource("researchguard://about", mime_type="application/json")
def about_researchguard() -> str:
    """Describe this MCP server's capabilities and safety boundary."""
    return json.dumps(
        {
            "name": "ResearchGuard",
            "kind": "read-only research planning MCP server",
            "capabilities": [
                "evidence search",
                "claim-support screening",
                "citation checks",
                "sample-size estimation",
                "saved-run listing",
                "protocol inspection",
            ],
            "writes_exposed": False,
            "human_boundary": "Approval, edits, archive, and deletion remain in the web app.",
        },
        indent=2,
    )


@mcp.resource("researchguard://protocol/{owner_id}/{thread_id}", mime_type="text/markdown")
def protocol_resource(owner_id: str, thread_id: str) -> str:
    """Read a completed or review-ready ResearchGuard protocol as Markdown."""
    protocol = service.get(thread_id, owner_id[:200])["state"].get("protocol")
    if not protocol:
        raise ValueError("The run does not have a synthesized protocol yet")
    return protocol_markdown(protocol)


@mcp.prompt(title="Design a governed research study")
def design_research_study(question: str) -> str:
    """Create a request that uses ResearchGuard tools without bypassing human approval."""
    return (
        f"Help me plan a defensible study for: {question}\n\n"
        "Use ResearchGuard evidence and analysis tools. Separate sourced facts from assumptions, "
        "identify unresolved risks, and do not claim the protocol is approved. Direct any "
        "consequential edit or approval to the ResearchGuard human-review interface."
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
