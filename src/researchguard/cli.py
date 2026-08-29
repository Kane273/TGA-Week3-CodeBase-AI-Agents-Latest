from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import typer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from researchguard.checkpointing import researchguard_serializer
from researchguard.graph import build_graph

app = typer.Typer(no_args_is_help=True, help="Multi-agent research design and review council.")
console = Console()


def _print_update(update: dict) -> None:
    for node, value in update.items():
        if node == "__interrupt__":
            continue
        console.print(f"[cyan]✓ {node.replace('_', ' ').title()}[/cyan]")
        if isinstance(value, dict) and value.get("critiques"):
            for critique in value["critiques"]:
                console.print(f"  [{critique.severity}] {critique.issue}")


@app.command()
def run(
    question: str = typer.Argument(..., help="Research question to investigate."),
    thread_id: str = typer.Option("", help="Stable ID used to resume a saved run."),
    db: Path = typer.Option(Path("researchguard.db"), help="SQLite checkpoint database."),
    auto_approve: bool = typer.Option(False, help="Approve the protocol without prompting."),
) -> None:
    """Run a new research council and pause for protocol approval."""
    thread_id = thread_id or str(uuid.uuid4())
    conn = sqlite3.connect(db, check_same_thread=False)
    graph = build_graph(SqliteSaver(conn, serde=researchguard_serializer()))
    config = {"configurable": {"thread_id": thread_id}}
    initial = {
        "question": question,
        "constraints": [],
        "revision": 0,
        "max_revisions": 1,
        "status": "researching",
    }
    console.print(Panel(f"Thread: {thread_id}\nQuestion: {question}", title="ResearchGuard"))
    for update in graph.stream(initial, config=config, stream_mode="updates"):
        _print_update(update)

    snapshot = graph.get_state(config)
    if snapshot.next and "human_approval" in snapshot.next:
        protocol = snapshot.values["protocol"]
        console.print(
            Panel(json.dumps(protocol.model_dump(mode="json"), indent=2), title="Protocol")
        )
        approved = auto_approve or Confirm.ask("Approve this protocol?")
        feedback = "" if approved else Prompt.ask("What must change?")
        for update in graph.stream(
            Command(resume={"approved": approved, "feedback": feedback}),
            config=config,
            stream_mode="updates",
        ):
            _print_update(update)
    final = graph.get_state(config).values
    console.print(f"[bold]Status:[/bold] {final.get('status')}  [bold]Thread:[/bold] {thread_id}")
    conn.close()


@app.command()
def inspect(
    thread_id: str = typer.Argument(...),
    db: Path = typer.Option(Path("researchguard.db")),
) -> None:
    """Inspect the latest durable state for a research thread."""
    conn = sqlite3.connect(db, check_same_thread=False)
    graph = build_graph(SqliteSaver(conn, serde=researchguard_serializer()))
    state = graph.get_state({"configurable": {"thread_id": thread_id}})
    console.print_json(json.dumps(state.values, default=lambda value: value.model_dump()))
    conn.close()


if __name__ == "__main__":
    app()
