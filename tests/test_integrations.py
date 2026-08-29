import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import researchguard.api as api_module
import researchguard.voice as voice_module
from researchguard.api import app
from researchguard.service import ResearchService
from researchguard.tools import _get_json, verify_citation


def test_citation_verifier_rejects_untraceable_source():
    result = verify_citation.invoke({"source": "https://example.com/blog", "identifier": None})
    assert result == {"verified": False, "reason": "missing stable PMID/DOI"}


def test_network_tool_retries_transient_failure(monkeypatch):
    attempts = 0

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def flaky_get(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("temporary outage")
        return Response()

    monkeypatch.setattr(httpx, "get", flaky_get)
    assert _get_json("https://example.test", {}) == {"ok": True}
    assert attempts == 3


def test_api_run_and_approval_are_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "service", ResearchService(tmp_path / "api.db"))
    client = TestClient(app)
    created = client.post("/api/runs", json={"question": "Does sleep improve learning outcomes?"})
    assert created.status_code == 200
    payload = created.json()
    assert payload["next"] == ["human_approval"]

    approved = client.post(
        f"/api/runs/{payload['thread_id']}/decision",
        json={"approved": True, "feedback": "reviewed"},
    )
    assert approved.status_code == 200
    assert approved.json()["state"]["status"] == "complete"
    report = client.get(f"/api/runs/{payload['thread_id']}/report.md")
    assert report.status_code == 200
    assert "# ResearchGuard Protocol" in report.text


def test_thread_ownership_is_enforced(tmp_path):
    service = ResearchService(tmp_path / "ownership.db")
    run = service.start("Does sleep improve learning?", owner_id="alice")
    with pytest.raises(PermissionError):
        service.get(run["thread_id"], owner_id="bob")


def test_voice_adapters_use_elevenlabs_client(monkeypatch):
    class SpeechToText:
        def convert(self, **kwargs):
            return type("Transcript", (), {"text": "Does sleep improve memory?"})()

    class TextToSpeech:
        def convert(self, **kwargs):
            return iter([b"audio", b"bytes"])

    fake = type(
        "ElevenLabs",
        (),
        {"speech_to_text": SpeechToText(), "text_to_speech": TextToSpeech()},
    )()
    monkeypatch.setattr(voice_module, "_client", lambda: fake)
    assert voice_module.transcribe_audio(b"input") == "Does sleep improve memory?"
    assert voice_module.speak_briefing("Protocol ready") == b"audiobytes"


def test_realtime_voice_opens_streaming_scribe_session(monkeypatch):
    captured = {}
    sentinel = object()

    class Realtime:
        async def connect(self, options):
            captured.update(options)
            return sentinel

    fake = type(
        "ElevenLabs",
        (),
        {"speech_to_text": type("Speech", (), {"realtime": Realtime()})()},
    )()
    monkeypatch.setattr(voice_module, "_client", lambda: fake)
    connection, _ = asyncio.run(voice_module.open_realtime_transcription())
    assert connection is sentinel
    assert captured["model_id"] == "scribe_v2_realtime"
    assert captured["sample_rate"] == 16000


def test_background_runs_complete_concurrently(tmp_path):
    service = ResearchService(tmp_path / "concurrent.db")
    runs = [
        service.submit(f"Does intervention number {index} improve learning?") for index in range(3)
    ]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        states = [service.get(run["thread_id"]) for run in runs]
        if all("human_approval" in state["next"] for state in states):
            break
        time.sleep(0.02)
    assert all("human_approval" in state["next"] for state in states)


def test_baseline_comparison_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "service", ResearchService(tmp_path / "comparison.db"))
    client = TestClient(app)
    created = client.post(
        "/api/runs", json={"question": "Does an AI tutor improve algebra transfer?"}
    )
    assert created.status_code == 200
    thread_id = created.json()["thread_id"]
    comparison = client.get(f"/api/runs/{thread_id}/comparison")
    assert comparison.status_code == 200
    scores = comparison.json()
    assert scores["researchguard"]["verified_evidence_rate"] == 1
    assert scores["single_agent"]["revision_count"] == 0
    assert scores["researchguard"]["revision_count"] >= 1


def test_guided_showcase_exposes_recovery_and_comparison(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "service", ResearchService(tmp_path / "showcase.db"))
    client = TestClient(app)
    created = client.post("/api/showcase")
    assert created.status_code == 200
    thread_id = created.json()["thread_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = client.get(f"/api/runs/{thread_id}").json()
        if "human_approval" in state.get("next", []):
            break
        time.sleep(0.02)
    assert state["state"]["tool_failures"]
    assert "Partial evidence outage" in state["state"]["warnings"][0]
    comparison = client.get(f"/api/runs/{thread_id}/comparison")
    assert comparison.status_code == 200
    assert comparison.json()["researchguard"]["verified_evidence_rate"] == 1

    offline = client.post(f"/api/runs/{thread_id}/recovery", json={"action": "offline"})
    assert offline.status_code == 200
    assert offline.json()["thread_id"] != thread_id


def test_guided_showcase_rotates_unique_research_questions(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "service", ResearchService(tmp_path / "showcase-rotation.db"))
    client = TestClient(app)

    first = client.post("/api/showcase").json()
    second = client.post("/api/showcase").json()
    runs = client.get("/api/runs").json()

    assert first["thread_id"] != second["thread_id"]
    assert len({run["question"] for run in runs}) == 2
    assert all("replication cohort" not in run["question"].lower() for run in runs)


def test_frontend_assets_are_external_and_accessible(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "service", ResearchService(tmp_path / "frontend.db"))
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert 'href="/assets/styles.css?v=0.3.6"' in page.text
    assert 'src="/assets/app.js?v=0.3.6"' in page.text
    assert "demo-question-options" in page.text
    assert "aria-live" in page.text
    assert "decision-dialog" in page.text
    assert client.get("/assets/styles.css").status_code == 200
    script = client.get("/assets/app.js")
    assert script.status_code == 200
    assert "EventSource" in script.text


def test_local_demo_security_headers_and_voice_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "service", ResearchService(tmp_path / "security.db"))
    monkeypatch.setattr(api_module, "MAX_VOICE_UPLOAD_BYTES", 8)
    client = TestClient(app)

    page = client.get("/")
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["referrer-policy"] == "no-referrer"

    unsupported = client.post(
        "/api/voice/transcribe", files={"file": ("note.txt", b"hello", "text/plain")}
    )
    assert unsupported.status_code == 415
    oversized = client.post(
        "/api/voice/transcribe",
        files={"file": ("voice.webm", b"123456789", "audio/webm")},
    )
    assert oversized.status_code == 413
    empty = client.post("/api/voice/transcribe", files={"file": ("voice.webm", b"", "audio/webm")})
    assert empty.status_code == 422


def test_server_sent_event_stream_returns_graph_state(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "service", ResearchService(tmp_path / "events.db"))
    client = TestClient(app)
    run = client.post(
        "/api/runs", json={"question": "Does sleep improve learning outcomes?"}
    ).json()
    with client.stream("GET", f"/api/runs/{run['thread_id']}/events") as response:
        assert response.status_code == 200
        event_lines = [line for line in response.iter_lines() if line.startswith("data: ")]
    assert event_lines
    assert run["thread_id"] in event_lines[0]


def test_workspace_run_management_and_inspection(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "service", ResearchService(tmp_path / "workspace.db"))
    client = TestClient(app)
    first = client.post("/api/runs", json={"question": "Does sleep improve recall?"}).json()
    second = client.post("/api/runs", json={"question": "Does exercise improve recall?"}).json()

    listed = client.get("/api/runs").json()
    assert {run["thread_id"] for run in listed} == {first["thread_id"], second["thread_id"]}

    node = client.get(f"/api/runs/{first['thread_id']}/nodes/research_planner")
    assert node.status_code == 200
    assert node.json()["events"]
    assert client.get(f"/api/runs/{first['thread_id']}/history").json()

    comparison = client.get(
        "/api/compare", params={"left": first["thread_id"], "right": second["thread_id"]}
    )
    assert comparison.status_code == 200
    assert "verified_evidence_rate" in comparison.json()["left"]

    archived = client.post(f"/api/runs/{first['thread_id']}/archive", json={"archived": True})
    assert archived.json()["archived"] is True
    assert first["thread_id"] not in {run["thread_id"] for run in client.get("/api/runs").json()}
    assert first["thread_id"] in {
        run["thread_id"]
        for run in client.get("/api/runs", params={"include_archived": True}).json()
    }

    deleted = client.delete(f"/api/runs/{second['thread_id']}")
    assert deleted.json()["deleted"] is True
    assert client.get(f"/api/runs/{second['thread_id']}").status_code == 404


def test_human_protocol_edit_is_recorded_and_re_reviewed(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "service", ResearchService(tmp_path / "edit.db"))
    client = TestClient(app)
    run = client.post("/api/runs", json={"question": "Does sleep improve recall?"}).json()
    response = client.patch(
        f"/api/runs/{run['thread_id']}/protocol",
        json={"population": "Adults aged 18 to 30", "target_sample_size": 240},
    )
    assert response.status_code == 200
    state = response.json()["state"]
    assert state["study"]["population"] == "Adults aged 18 to 30"
    assert state["statistics"]["target_sample_size"] == 240
    assert any(item["agent"] == "human_protocol_editor" for item in state["revision_history"])
