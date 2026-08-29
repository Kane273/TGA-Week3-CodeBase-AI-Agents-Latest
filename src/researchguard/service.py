from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from researchguard.checkpointing import researchguard_serializer
from researchguard.graph import build_graph
from researchguard.models import GraphEvent, RevisionRecord, StatisticalPlan, StudyDesign


def jsonable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


class ResearchService:
    """Durable graph service with migrations, ownership, and background execution."""

    def __init__(self, db_path: str | Path = "researchguard.db") -> None:
        self.db_path = str(db_path)
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="researchguard")
        self.jobs: dict[str, dict] = {}
        self.jobs_lock = Lock()
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def _database(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _migrate(self) -> None:
        with self._database() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS researchguard_schema "
                "(version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS researchguard_threads "
                "(thread_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, "
                "question TEXT DEFAULT '', status TEXT DEFAULT 'created', archived INTEGER DEFAULT 0, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(researchguard_threads)").fetchall()
            }
            additions = {
                "question": "TEXT DEFAULT ''",
                "status": "TEXT DEFAULT 'created'",
                "archived": "INTEGER DEFAULT 0",
                "updated_at": "TEXT",
            }
            for name, definition in additions.items():
                if name not in columns:
                    conn.execute(
                        f"ALTER TABLE researchguard_threads ADD COLUMN {name} {definition}"
                    )
            conn.execute(
                "UPDATE researchguard_threads SET updated_at = COALESCE(updated_at, created_at)"
            )
            conn.execute("INSERT OR IGNORE INTO researchguard_schema(version) VALUES (1)")
            conn.execute("INSERT OR IGNORE INTO researchguard_schema(version) VALUES (2)")

    @contextmanager
    def _graph(self) -> Iterator:
        conn = self._connect()
        try:
            yield build_graph(SqliteSaver(conn, serde=researchguard_serializer()))
        finally:
            conn.close()

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def _register(self, thread_id: str, owner_id: str, question: str = "") -> None:
        with self._database() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO researchguard_threads(thread_id, owner_id, question) "
                "VALUES (?, ?, ?)",
                (thread_id, owner_id, question),
            )

    def _touch(self, thread_id: str, status: str) -> None:
        with self._database() as conn:
            conn.execute(
                "UPDATE researchguard_threads SET status = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE thread_id = ?",
                (status, thread_id),
            )

    def _assert_owner(self, thread_id: str, owner_id: str | None) -> None:
        if owner_id is None:
            return
        with self._database() as conn:
            row = conn.execute(
                "SELECT owner_id FROM researchguard_threads WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        if row and row[0] != owner_id:
            raise PermissionError(thread_id)

    def start(
        self,
        question: str,
        constraints: list[str] | None = None,
        owner_id: str = "demo-user",
        thread_id: str | None = None,
        showcase_mode: bool = False,
        force_offline: bool = False,
    ) -> dict:
        thread_id = thread_id or str(uuid.uuid4())
        self._register(thread_id, owner_id, question)
        with self._graph() as graph:
            graph.invoke(
                {
                    "question": question,
                    "constraints": constraints or [],
                    "owner_id": owner_id,
                    "showcase_mode": showcase_mode,
                    "force_offline": force_offline,
                    "revision": 0,
                    "max_revisions": 1,
                    "status": "planning",
                },
                config=self._config(thread_id),
            )
            snapshot = self._snapshot(graph, thread_id)
            self._touch(thread_id, snapshot["state"].get("status", "ready"))
            return snapshot

    def submit(
        self,
        question: str,
        constraints: list[str] | None = None,
        owner_id: str = "demo-user",
        showcase_mode: bool = False,
        force_offline: bool = False,
    ) -> dict:
        thread_id = str(uuid.uuid4())
        self._register(thread_id, owner_id, question)
        with self.jobs_lock:
            self.jobs[thread_id] = {"status": "queued", "error": None}

        def work() -> None:
            with self.jobs_lock:
                self.jobs[thread_id]["status"] = "running"
            try:
                self.start(
                    question,
                    constraints,
                    owner_id,
                    thread_id,
                    showcase_mode,
                    force_offline,
                )
                status, error = "awaiting_approval", None
            except Exception as exc:  # noqa: BLE001 - background boundary records failed jobs
                status, error = "failed", str(exc)[:500]
            with self.jobs_lock:
                if self.jobs[thread_id].get("cancel_requested"):
                    status = "cancelled"
                self.jobs[thread_id].update({"status": status, "error": error})
            self._touch(thread_id, status)

        future = self.executor.submit(work)
        with self.jobs_lock:
            self.jobs[thread_id]["future"] = future
        return {"thread_id": thread_id, "job_status": "queued", "next": [], "state": {}}

    def cancel(self, thread_id: str, owner_id: str | None = None) -> dict:
        self._assert_owner(thread_id, owner_id)
        with self.jobs_lock:
            job = self.jobs.get(thread_id)
            if not job:
                return {"thread_id": thread_id, "job_status": "not_running"}
            job["cancel_requested"] = True
            future = job.get("future")
            if future and future.cancel():
                job["status"] = "cancelled"
            else:
                job["status"] = "cancelling"
            return {"thread_id": thread_id, "job_status": job["status"]}

    def restart(
        self, thread_id: str, owner_id: str | None = None, force_offline: bool = False
    ) -> dict:
        snapshot = self.get(thread_id, owner_id)
        state = snapshot["state"]
        return self.submit(
            state["question"],
            state.get("constraints", []),
            owner_id or state.get("owner_id", "demo-user"),
            state.get("showcase_mode", False) and not force_offline,
            force_offline,
        )

    def get(self, thread_id: str, owner_id: str | None = None) -> dict:
        self._assert_owner(thread_id, owner_id)
        with self._graph() as graph:
            try:
                return self._snapshot(graph, thread_id)
            except KeyError:
                with self.jobs_lock:
                    job = self.jobs.get(thread_id)
                if job:
                    return {
                        "thread_id": thread_id,
                        "job_status": job["status"],
                        "error": job["error"],
                        "next": [],
                        "state": {},
                    }
                raise

    def decide(
        self,
        thread_id: str,
        approved: bool,
        feedback: str = "",
        owner_id: str | None = None,
    ) -> dict:
        self._assert_owner(thread_id, owner_id)
        with self._graph() as graph:
            graph.invoke(
                Command(resume={"approved": approved, "feedback": feedback}),
                config=self._config(thread_id),
            )
            snapshot = self._snapshot(graph, thread_id)
            self._touch(thread_id, snapshot["state"].get("status", "ready"))
            return snapshot

    def list_runs(self, owner_id: str, include_archived: bool = False) -> list[dict]:
        with self._database() as conn:
            rows = conn.execute(
                "SELECT thread_id, question, status, archived, created_at, updated_at "
                "FROM researchguard_threads WHERE owner_id = ? AND (? OR archived = 0) "
                "ORDER BY updated_at DESC LIMIT 100",
                (owner_id, int(include_archived)),
            ).fetchall()
        return [
            {
                "thread_id": row[0],
                "question": row[1],
                "status": row[2],
                "archived": bool(row[3]),
                "created_at": row[4],
                "updated_at": row[5],
            }
            for row in rows
        ]

    def archive(self, thread_id: str, archived: bool, owner_id: str | None = None) -> dict:
        self._assert_owner(thread_id, owner_id)
        with self._database() as conn:
            conn.execute(
                "UPDATE researchguard_threads SET archived = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE thread_id = ?",
                (int(archived), thread_id),
            )
        return {"thread_id": thread_id, "archived": archived}

    def delete(self, thread_id: str, owner_id: str | None = None) -> dict:
        self._assert_owner(thread_id, owner_id)
        with self._database() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                if table in tables:
                    conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
            conn.execute("DELETE FROM researchguard_threads WHERE thread_id = ?", (thread_id,))
        return {"thread_id": thread_id, "deleted": True}

    def history(self, thread_id: str, owner_id: str | None = None) -> list[dict]:
        self._assert_owner(thread_id, owner_id)
        with self._graph() as graph:
            snapshots = list(graph.get_state_history(self._config(thread_id), limit=50))
        return [
            {
                "created_at": snapshot.created_at,
                "next": list(snapshot.next),
                "revision": snapshot.values.get("revision", 0),
                "status": snapshot.values.get("status"),
                "protocol": jsonable(snapshot.values.get("protocol")),
            }
            for snapshot in snapshots
        ]

    def edit_protocol(self, thread_id: str, changes: dict, owner_id: str | None = None) -> dict:
        self._assert_owner(thread_id, owner_id)
        with self._graph() as graph:
            config = self._config(thread_id)
            snapshot = graph.get_state(config)
            if not snapshot.values or "human_approval" not in snapshot.next:
                raise ValueError("Protocol can only be edited while awaiting final approval")
            study = snapshot.values["study"].model_copy(deep=True)
            statistics = snapshot.values["statistics"].model_copy(deep=True)
            before = {"study": study.model_dump(), "statistics": statistics.model_dump()}
            for field in ("population", "intervention", "comparator", "outcome", "duration"):
                if field in changes:
                    setattr(study, field, str(changes[field]))
            if "controls" in changes:
                study.controls = [str(value) for value in changes["controls"]]
            if "target_sample_size" in changes:
                statistics.target_sample_size = int(changes["target_sample_size"])
            revision = snapshot.values.get("revision", 0) + 1
            after = {"study": study.model_dump(), "statistics": statistics.model_dump()}
            record = RevisionRecord(
                revision=revision,
                agent="human_protocol_editor",
                reason="Human edited protocol fields before approval.",
                before=json.dumps(before, sort_keys=True),
                after=json.dumps(after, sort_keys=True),
            )
            graph.update_state(
                config,
                {
                    "study": StudyDesign.model_validate(study),
                    "statistics": StatisticalPlan.model_validate(statistics),
                    "revision": revision,
                    "revision_history": [record],
                    "events": [
                        GraphEvent(
                            node="human_protocol_editor",
                            message="Updated protocol fields and requested re-review.",
                        )
                    ],
                },
                as_node="revision_editor",
            )
            graph.invoke(None, config=config)
            result = self._snapshot(graph, thread_id)
        self._touch(thread_id, result["state"].get("status", "reviewing"))
        return result

    def _snapshot(self, graph, thread_id: str) -> dict:
        snapshot = graph.get_state(self._config(thread_id))
        if not snapshot.values:
            raise KeyError(thread_id)
        with self.jobs_lock:
            job = self.jobs.get(thread_id)
        return {
            "thread_id": thread_id,
            "job_status": job["status"] if job else "ready",
            "next": list(snapshot.next),
            "state": jsonable(snapshot.values),
        }

    def purge_expired(self, retention_days: int = 30) -> int:
        """Remove expired thread ownership and its LangGraph checkpoint data."""
        with self._database() as conn:
            rows = conn.execute(
                "SELECT thread_id FROM researchguard_threads WHERE created_at < datetime('now', ?)",
                (f"-{max(retention_days, 1)} days",),
            ).fetchall()
            thread_ids = [row[0] for row in rows]
            for thread_id in thread_ids:
                for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                    conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
                conn.execute("DELETE FROM researchguard_threads WHERE thread_id = ?", (thread_id,))
            return len(thread_ids)

    def ping(self) -> bool:
        with self._database() as conn:
            return conn.execute("SELECT 1").fetchone()[0] == 1


class PostgresResearchService(ResearchService):
    """Production-compatible service using LangGraph's PostgreSQL checkpointer."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="researchguard")
        self.jobs = {}
        self.jobs_lock = Lock()
        self._migrate()

    def _pg_connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            self.database_url,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )

    def _migrate(self) -> None:
        from langgraph.checkpoint.postgres import PostgresSaver

        with self._pg_connect() as conn:
            PostgresSaver(conn, serde=researchguard_serializer()).setup()
            conn.execute(
                "CREATE TABLE IF NOT EXISTS researchguard_schema "
                "(version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS researchguard_threads "
                "(thread_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, question TEXT DEFAULT '', "
                "status TEXT DEFAULT 'created', archived BOOLEAN DEFAULT FALSE, "
                "created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP, "
                "updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)"
            )
            for statement in (
                "ADD COLUMN IF NOT EXISTS question TEXT DEFAULT ''",
                "ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'created'",
                "ADD COLUMN IF NOT EXISTS archived BOOLEAN DEFAULT FALSE",
                "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
            ):
                conn.execute(f"ALTER TABLE researchguard_threads {statement}")
            conn.execute(
                "INSERT INTO researchguard_schema(version) VALUES (1) ON CONFLICT DO NOTHING"
            )
            conn.execute(
                "INSERT INTO researchguard_schema(version) VALUES (2) ON CONFLICT DO NOTHING"
            )

    @contextmanager
    def _graph(self) -> Iterator:
        from langgraph.checkpoint.postgres import PostgresSaver

        with self._pg_connect() as conn:
            yield build_graph(PostgresSaver(conn, serde=researchguard_serializer()))

    def _register(self, thread_id: str, owner_id: str, question: str = "") -> None:
        with self._pg_connect() as conn:
            conn.execute(
                "INSERT INTO researchguard_threads(thread_id, owner_id, question) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (thread_id, owner_id, question),
            )

    def _touch(self, thread_id: str, status: str) -> None:
        with self._pg_connect() as conn:
            conn.execute(
                "UPDATE researchguard_threads SET status = %s, updated_at = CURRENT_TIMESTAMP "
                "WHERE thread_id = %s",
                (status, thread_id),
            )

    def _assert_owner(self, thread_id: str, owner_id: str | None) -> None:
        if owner_id is None:
            return
        with self._pg_connect() as conn:
            row = conn.execute(
                "SELECT owner_id FROM researchguard_threads WHERE thread_id = %s", (thread_id,)
            ).fetchone()
        if row and row["owner_id"] != owner_id:
            raise PermissionError(thread_id)

    def list_runs(self, owner_id: str, include_archived: bool = False) -> list[dict]:
        with self._pg_connect() as conn:
            rows = conn.execute(
                "SELECT thread_id, question, status, archived, created_at, updated_at "
                "FROM researchguard_threads WHERE owner_id = %s AND (%s OR archived = FALSE) "
                "ORDER BY updated_at DESC LIMIT 100",
                (owner_id, include_archived),
            ).fetchall()
        return [dict(row) for row in rows]

    def archive(self, thread_id: str, archived: bool, owner_id: str | None = None) -> dict:
        self._assert_owner(thread_id, owner_id)
        with self._pg_connect() as conn:
            conn.execute(
                "UPDATE researchguard_threads SET archived = %s, updated_at = CURRENT_TIMESTAMP "
                "WHERE thread_id = %s",
                (archived, thread_id),
            )
        return {"thread_id": thread_id, "archived": archived}

    def delete(self, thread_id: str, owner_id: str | None = None) -> dict:
        self._assert_owner(thread_id, owner_id)
        with self._pg_connect() as conn:
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                conn.execute(f"DELETE FROM {table} WHERE thread_id = %s", (thread_id,))
            conn.execute("DELETE FROM researchguard_threads WHERE thread_id = %s", (thread_id,))
        return {"thread_id": thread_id, "deleted": True}

    def purge_expired(self, retention_days: int = 30) -> int:
        with self._pg_connect() as conn:
            rows = conn.execute(
                "SELECT thread_id FROM researchguard_threads "
                "WHERE created_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')",
                (max(retention_days, 1),),
            ).fetchall()
            thread_ids = [row["thread_id"] for row in rows]
            for thread_id in thread_ids:
                for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                    conn.execute(f"DELETE FROM {table} WHERE thread_id = %s", (thread_id,))
                conn.execute("DELETE FROM researchguard_threads WHERE thread_id = %s", (thread_id,))
            return len(thread_ids)

    def ping(self) -> bool:
        with self._pg_connect() as conn:
            return conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1


def create_service(database: str) -> ResearchService:
    if database.startswith(("postgresql://", "postgres://")):
        return PostgresResearchService(database)
    return ResearchService(database)
