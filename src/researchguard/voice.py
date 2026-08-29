from __future__ import annotations

import io
import os


def _client():
    try:
        from elevenlabs.client import ElevenLabs
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("The ElevenLabs SDK is not installed") from exc
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is required for voice features")
    return ElevenLabs(api_key=api_key)


def transcribe_audio(content: bytes, filename: str = "question.webm") -> str:
    """Transcribe uploaded research-question audio with ElevenLabs Scribe."""
    audio = io.BytesIO(content)
    audio.name = filename
    result = _client().speech_to_text.convert(file=audio, model_id="scribe_v1")
    return result.text


def speak_briefing(text: str) -> bytes:
    """Render a protocol briefing as MP3 with ElevenLabs."""
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    chunks = _client().text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    return b"".join(chunks)


async def open_realtime_transcription():
    """Open an ElevenLabs Scribe v2 real-time PCM transcription session."""
    from elevenlabs.realtime.connection import RealtimeEvents
    from elevenlabs.realtime.scribe import AudioFormat, CommitStrategy

    connection = await _client().speech_to_text.realtime.connect(
        {
            "model_id": "scribe_v2_realtime",
            "audio_format": AudioFormat.PCM_16000,
            "sample_rate": 16000,
            "commit_strategy": CommitStrategy.VAD,
        }
    )
    return connection, RealtimeEvents
