from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock
from typing import Literal

import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from researchguard.baseline import council_metrics, run_single_agent_baseline
from researchguard.report import protocol_markdown
from researchguard.service import create_service
from researchguard.voice import open_realtime_transcription, speak_briefing, transcribe_audio

WEB_DIR = Path(__file__).parent / "web"
app = FastAPI(title="ResearchGuard", version="0.3.0")
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")
service = create_service(os.getenv("RESEARCHGUARD_DB", "researchguard.db"))
MAX_VOICE_UPLOAD_BYTES = int(os.getenv("RESEARCHGUARD_MAX_VOICE_UPLOAD_BYTES", "10000000"))
ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4"}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=(), payment=()"
        if request.url.path == "/" or request.url.path.startswith("/assets/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; media-src 'self' blob:; "
                "connect-src 'self' ws: wss:; object-src 'none'; base-uri 'self'; "
                "form-action 'self'; frame-ancestors 'none'"
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 120) -> None:
        super().__init__(app)
        self.limit = requests_per_minute
        self.requests: dict[str, deque] = defaultdict(deque)
        self.lock = Lock()

    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/api/"):
            identity = request.client.host if request.client else "unknown"
            now = time.monotonic()
            with self.lock:
                window = self.requests[identity]
                while window and window[0] < now - 60:
                    window.popleft()
                if len(window) >= self.limit:
                    return Response("Rate limit exceeded", status_code=429)
                window.append(now)
        return await call_next(request)


app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=int(os.getenv("RESEARCHGUARD_RATE_LIMIT", "120")),
)
app.add_middleware(SecurityHeadersMiddleware)


def require_api_key(x_researchguard_key: str | None = Header(default=None)) -> None:
    expected = os.getenv("RESEARCHGUARD_API_KEY")
    if expected and not secrets.compare_digest(x_researchguard_key or "", expected):
        raise HTTPException(status_code=401, detail="Invalid ResearchGuard API key")


def current_owner(x_researchguard_user: str = Header(default="demo-user")) -> str:
    return x_researchguard_user[:200]


class RunRequest(BaseModel):
    question: str = Field(min_length=10, max_length=2_000)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    background: bool = False
    showcase_mode: bool = False


class DecisionRequest(BaseModel):
    approved: bool
    feedback: str = Field(default="", max_length=2_000)


class RecoveryRequest(BaseModel):
    action: Literal["retry", "offline", "continue", "cancel"]


class BriefingRequest(BaseModel):
    protocol: dict


class ArchiveRequest(BaseModel):
    archived: bool = True


class ProtocolEditRequest(BaseModel):
    population: str | None = None
    intervention: str | None = None
    comparator: str | None = None
    outcome: str | None = None
    duration: str | None = None
    controls: list[str] | None = None
    target_sample_size: int | None = Field(default=None, ge=2)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": os.getenv("RESEARCHGUARD_MODE", "demo")}


@app.get("/ready")
def readiness() -> dict:
    try:
        return {"status": "ready" if service.ping() else "not_ready", "database": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


@app.post("/api/runs", dependencies=[Depends(require_api_key)])
def create_run(request: RunRequest, owner_id: str = Depends(current_owner)) -> dict:
    if request.background:
        return service.submit(
            request.question, request.constraints, owner_id, request.showcase_mode
        )
    return service.start(
        request.question, request.constraints, owner_id, showcase_mode=request.showcase_mode
    )


@app.get("/api/runs", dependencies=[Depends(require_api_key)])
def list_runs(include_archived: bool = False, owner_id: str = Depends(current_owner)) -> list[dict]:
    return service.list_runs(owner_id, include_archived)


@app.post("/api/showcase", dependencies=[Depends(require_api_key)])
def guided_showcase(owner_id: str = Depends(current_owner)) -> dict:
    scenarios = (
        (
            "Does an AI tutor improve algebra transfer for first-year students?",
            ["Keep the study under eight weeks", "Require a measurable far-transfer outcome"],
        ),
        (
            "Does retrieval-augmented generation reduce hallucinations in technical support answers?",
            ["Compare against the same model without retrieval", "Blind expert factuality ratings"],
        ),
        (
            "Can protected focus time reduce software-engineer burnout without lowering delivery quality?",
            ["Measure wellbeing and delivery outcomes", "Avoid collecting private message content"],
        ),
        (
            "Does code review assisted by an AI agent find more security defects than standard review?",
            ["Use seeded vulnerabilities", "Require human confirmation of every reported defect"],
        ),
        (
            "Can spaced retrieval practice improve long-term memory for engineering certification material?",
            ["Include a delayed retention test", "Control for total study time"],
        ),
        (
            "Does a structured exercise program improve mood for remote knowledge workers?",
            ["Track adherence", "Use a validated wellbeing measure"],
        ),
        (
            "Does an AI tutor improve Python debugging skills for novice programmers?",
            ["Measure performance on unseen bugs", "Match practice time across groups"],
        ),
        (
            "Can retrieval-augmented generation improve citation accuracy in AI literature reviews?",
            ["Verify every cited identifier", "Use blinded claim-support scoring"],
        ),
        (
            "Does AI-assisted code review reduce missed access-control vulnerabilities in web APIs?",
            ["Use versioned synthetic repositories", "Track false-positive review time"],
        ),
        (
            "Can meeting-free mornings improve deep-work output for distributed engineering teams?",
            ["Preserve incident-response coverage", "Measure output quality and wellbeing"],
        ),
        (
            "Does spaced retrieval improve delayed recall of cloud architecture concepts?",
            ["Use a six-week delayed assessment", "Equalize total learning time"],
        ),
        (
            "Can short movement breaks reduce afternoon fatigue among remote data scientists?",
            ["Measure adherence objectively", "Use a validated fatigue scale"],
        ),
        (
            "Does an adaptive AI tutor improve geometry proof construction for high-school students?",
            ["Require guardian consent", "Score novel proofs with blinded raters"],
        ),
        (
            "Can source reranking reduce unsupported claims in retrieval-augmented legal summaries?",
            ["Use public non-confidential cases", "Have legal experts adjudicate factual support"],
        ),
        (
            "Does AI-assisted threat modeling identify more cloud misconfigurations than checklist review?",
            ["Seed known misconfigurations", "Require expert confirmation before scoring"],
        ),
        (
            "Can protected focus blocks improve pull-request quality for junior software engineers?",
            ["Adjust for task complexity", "Do not collect private communication content"],
        ),
        (
            "Does spaced retrieval improve cybersecurity certification retention after eight weeks?",
            ["Include an eight-week delayed test", "Control for prior security experience"],
        ),
        (
            "Does a guided walking program improve stress recovery for hybrid product teams?",
            ["Track participation without location histories", "Use a validated stress measure"],
        ),
    )
    # Choose the next scenario per workspace so repeated showcases demonstrate
    # different research domains while remaining deterministic and testable.
    saved_runs = service.list_runs(owner_id, include_archived=True)
    existing_questions = {run["question"].strip().casefold() for run in saved_runs}
    start = len(saved_runs) % len(scenarios)
    scenario = next(
        (
            scenarios[(start + offset) % len(scenarios)]
            for offset in range(len(scenarios))
            if scenarios[(start + offset) % len(scenarios)][0].casefold() not in existing_questions
        ),
        None,
    )
    if scenario is None:
        # The catalog is exhausted. Vary a real design dimension rather than
        # presenting the same question as a numbered replication.
        base = scenarios[start]
        follow_up_weeks = 12 + len(saved_runs)
        question = f"{base[0][:-1]} with outcomes assessed after {follow_up_weeks} weeks?"
        constraints = [*base[1], f"Use a {follow_up_weeks}-week outcome assessment"]
    else:
        question, scenario_constraints = scenario
        constraints = list(scenario_constraints)
    return service.submit(
        question,
        constraints,
        owner_id,
        showcase_mode=True,
    )


@app.get("/api/runs/{thread_id}", dependencies=[Depends(require_api_key)])
def get_run(thread_id: str, owner_id: str = Depends(current_owner)) -> dict:
    try:
        return service.get(thread_id, owner_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Research thread not found") from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403, detail="Research thread belongs to another user"
        ) from exc


@app.get("/api/runs/{thread_id}/comparison", dependencies=[Depends(require_api_key)])
def comparison(thread_id: str, owner_id: str = Depends(current_owner)) -> dict:
    try:
        state = service.get(thread_id, owner_id)["state"]
        if not state:
            raise HTTPException(status_code=409, detail="Research run is still starting")
        return {
            "single_agent": run_single_agent_baseline({"question": state["question"]}),
            "researchguard": council_metrics(state),
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Research thread not found") from exc


@app.get("/api/compare", dependencies=[Depends(require_api_key)])
def compare_runs(left: str, right: str, owner_id: str = Depends(current_owner)) -> dict:
    try:
        left_state = service.get(left, owner_id)["state"]
        right_state = service.get(right, owner_id)["state"]
        return {"left": council_metrics(left_state), "right": council_metrics(right_state)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Research thread not found") from exc


@app.get("/api/runs/{thread_id}/history", dependencies=[Depends(require_api_key)])
def run_history(thread_id: str, owner_id: str = Depends(current_owner)) -> list[dict]:
    return service.history(thread_id, owner_id)


@app.get("/api/runs/{thread_id}/nodes/{node_name}", dependencies=[Depends(require_api_key)])
def node_details(thread_id: str, node_name: str, owner_id: str = Depends(current_owner)) -> dict:
    state = service.get(thread_id, owner_id)["state"]
    artifact_map = {
        "research_planner": "research_plan",
        "evidence_worker": "evidence",
        "evidence_gate": "tool_failures",
        "hypothesis_scientist": "hypothesis",
        "methods_designer": "study",
        "ethics_reviewer": "ethics",
        "statistician": "statistics",
        "skeptical_reviewer": "critiques",
        "revision_editor": "revision_history",
        "protocol_synthesizer": "protocol",
    }
    events = [
        event for event in state.get("events", []) if event["node"].split(":")[0] == node_name
    ]
    return {
        "node": node_name,
        "events": events,
        "artifact": state.get(artifact_map.get(node_name, "")),
        "model": os.getenv("RESEARCHGUARD_MODEL", "deterministic-demo"),
        "mode": os.getenv("RESEARCHGUARD_MODE", "demo"),
        "trace_project": os.getenv("LANGSMITH_PROJECT", "researchguard"),
    }


@app.patch("/api/runs/{thread_id}/protocol", dependencies=[Depends(require_api_key)])
def edit_protocol(
    thread_id: str, request: ProtocolEditRequest, owner_id: str = Depends(current_owner)
) -> dict:
    try:
        changes = request.model_dump(exclude_none=True)
        if not changes:
            raise HTTPException(status_code=422, detail="At least one protocol field is required")
        return service.edit_protocol(thread_id, changes, owner_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/runs/{thread_id}/archive", dependencies=[Depends(require_api_key)])
def archive_run(
    thread_id: str, request: ArchiveRequest, owner_id: str = Depends(current_owner)
) -> dict:
    return service.archive(thread_id, request.archived, owner_id)


@app.delete("/api/runs/{thread_id}", dependencies=[Depends(require_api_key)])
def delete_run(thread_id: str, owner_id: str = Depends(current_owner)) -> dict:
    return service.delete(thread_id, owner_id)


@app.post("/api/runs/{thread_id}/decision", dependencies=[Depends(require_api_key)])
def decide(
    thread_id: str, request: DecisionRequest, owner_id: str = Depends(current_owner)
) -> dict:
    try:
        return service.decide(thread_id, request.approved, request.feedback, owner_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Research thread not found") from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403, detail="Research thread belongs to another user"
        ) from exc


@app.post("/api/runs/{thread_id}/recovery", dependencies=[Depends(require_api_key)])
def recover(
    thread_id: str, request: RecoveryRequest, owner_id: str = Depends(current_owner)
) -> dict:
    try:
        if request.action == "cancel":
            return service.cancel(thread_id, owner_id)
        if request.action == "continue":
            return service.get(thread_id, owner_id)
        return service.restart(thread_id, owner_id, force_offline=request.action == "offline")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Research thread not found") from exc


@app.get("/api/runs/{thread_id}/events")
async def run_events(
    thread_id: str,
    user: str = "demo-user",
    key: str = "",
) -> StreamingResponse:
    expected = os.getenv("RESEARCHGUARD_API_KEY")
    if expected and not secrets.compare_digest(key, expected):
        raise HTTPException(status_code=401, detail="Invalid ResearchGuard API key")

    async def stream():
        last_payload = ""
        while True:
            try:
                snapshot = service.get(thread_id, user[:200])
            except KeyError:
                snapshot = {
                    "thread_id": thread_id,
                    "job_status": "starting",
                    "next": [],
                    "state": {},
                }
            payload = json.dumps(snapshot)
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            terminal = snapshot.get("job_status") in {"failed", "cancelled"}
            terminal = terminal or snapshot.get("state", {}).get("status") == "complete"
            terminal = terminal or any(
                node == "human_approval" or "human_review" in node
                for node in snapshot.get("next", [])
            )
            if terminal:
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{thread_id}/report.md", dependencies=[Depends(require_api_key)])
def report(thread_id: str, owner_id: str = Depends(current_owner)) -> Response:
    try:
        protocol = service.get(thread_id, owner_id)["state"].get("protocol")
        if not protocol:
            raise HTTPException(status_code=409, detail="Protocol is not ready")
        headers = {"Content-Disposition": f'attachment; filename="researchguard-{thread_id}.md"'}
        return Response(protocol_markdown(protocol), media_type="text/markdown", headers=headers)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Research thread not found") from exc


@app.post("/api/voice/transcribe", dependencies=[Depends(require_api_key)])
async def transcribe(file: UploadFile = File(...)) -> dict:
    try:
        content_type = (file.content_type or "").lower()
        if content_type not in ALLOWED_AUDIO_TYPES:
            raise HTTPException(status_code=415, detail="Unsupported audio type")
        content = await file.read(MAX_VOICE_UPLOAD_BYTES + 1)
        if len(content) > MAX_VOICE_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Audio upload exceeds the local demo limit")
        if not content:
            raise HTTPException(status_code=422, detail="Audio upload is empty")
        return {"text": transcribe_audio(content, file.filename or "question.webm")}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/voice/briefing", dependencies=[Depends(require_api_key)])
def briefing(request: BriefingRequest) -> Response:
    try:
        summary = json.dumps(request.protocol, indent=2)[:8_000]
        return Response(speak_briefing(summary), media_type="audio/mpeg")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.websocket("/api/voice/realtime")
async def realtime_voice(websocket: WebSocket) -> None:
    expected = os.getenv("RESEARCHGUARD_API_KEY")
    if expected and not secrets.compare_digest(websocket.query_params.get("key", ""), expected):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    connection = None
    try:
        connection, events = await open_realtime_transcription()
        loop = asyncio.get_running_loop()

        def forward(payload: dict) -> None:
            loop.create_task(websocket.send_json(payload))

        connection.on(events.PARTIAL_TRANSCRIPT, forward)
        connection.on(events.COMMITTED_TRANSCRIPT, forward)
        connection.on(events.ERROR, forward)
        while True:
            message = await websocket.receive()
            if chunk := message.get("bytes"):
                await connection.send({"audio_base_64": base64.b64encode(chunk).decode()})
            elif message.get("text") == "commit":
                await connection.commit()
    except WebSocketDisconnect:
        pass
    except RuntimeError as exc:
        await websocket.send_json({"message_type": "error", "error": str(exc)})
    finally:
        if connection:
            await connection.close()


@app.get("/", response_class=FileResponse)
def dashboard() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


def main() -> None:
    certfile = os.getenv("RESEARCHGUARD_SSL_CERTFILE", "").strip()
    keyfile = os.getenv("RESEARCHGUARD_SSL_KEYFILE", "").strip()
    if bool(certfile) != bool(keyfile):
        raise SystemExit(
            "Set both RESEARCHGUARD_SSL_CERTFILE and RESEARCHGUARD_SSL_KEYFILE, or neither."
        )
    for label, value in (("certificate", certfile), ("private key", keyfile)):
        if value and not Path(value).expanduser().is_file():
            raise SystemExit(f"Configured TLS {label} file does not exist: {value}")
    uvicorn.run(
        "researchguard.api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        ssl_certfile=str(Path(certfile).expanduser()) if certfile else None,
        ssl_keyfile=str(Path(keyfile).expanduser()) if keyfile else None,
    )
