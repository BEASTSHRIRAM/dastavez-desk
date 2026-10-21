"""Speech-to-text provider adapter. Transcription is deliberately separate from agent execution:
it only returns text, which the operator can edit before anything runs.

'demo' means no speech service is configured. The frontend then falls back to the browser's own
speech recognition where available, or typed input. Nothing is faked here."""
import httpx

from app.config import Settings, get_settings


class SttUnavailable(RuntimeError):
    """No speech service is configured. Message is safe to show."""


class SttFailed(RuntimeError):
    pass


def transcribe(audio: bytes, filename: str, content_type: str, language: str | None = None,
               settings: Settings | None = None) -> str:
    s = settings or get_settings()
    providers = {"openai": ("https://api.openai.com/v1", s.stt_api_key, "whisper-1"),
                 "groq": ("https://api.groq.com/openai/v1", s.groq_api_key, s.groq_stt_model)}
    base, key, model = providers.get(s.stt_provider, ("", "", ""))
    if not key:
        raise SttUnavailable("No speech service is configured on the server. Use the browser microphone "
                             "transcript or type your request instead.")
    try:
        r = httpx.post(
            f"{base}/audio/transcriptions",
            headers={"authorization": f"Bearer {key}"},
            files={"file": (filename, audio, content_type)},
            data={"model": model, **({"language": language} if language else {})},
            timeout=120,
        )
        r.raise_for_status()
        text = r.json().get("text", "").strip()
    except httpx.HTTPError as exc:
        raise SttFailed(f"The speech service did not respond ({exc.__class__.__name__}).") from exc
    if not text:
        raise SttFailed("No speech was recognised. Try again closer to the microphone, or type instead.")
    return text
