import pytest

from app.config import Settings
from app.services import llm, stt


class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


def test_groq_llm_uses_groq_endpoint_key_and_model(monkeypatch):
    seen = {}
    def fake_post(url, headers=None, json=None, **kw):
        seen.update(url=url, auth=headers["authorization"], model=json["model"])
        return FakeResponse({"choices": [{"message": {"content": '{"facts": []}'}}]})
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    provider = llm.get_llm_provider(Settings(llm_provider="groq", groq_api_key="gsk_test", groq_llm_model="m1"))
    assert provider.name == "groq" and provider.complete_json("s", "u") == {"facts": []}
    assert seen == {"url": "https://api.groq.com/openai/v1/chat/completions", "auth": "Bearer gsk_test", "model": "m1"}


def test_groq_without_a_key_raises_so_the_workflow_falls_back_to_rules():
    with pytest.raises(llm.LLMError):
        llm.get_llm_provider(Settings(llm_provider="groq", groq_api_key=""))


def test_groq_speech_to_text_endpoint_and_model(monkeypatch):
    seen = {}
    def fake_post(url, headers=None, files=None, data=None, **kw):
        seen.update(url=url, auth=headers["authorization"], model=data["model"])
        return FakeResponse({"text": " hello "})
    monkeypatch.setattr(stt.httpx, "post", fake_post)
    s = Settings(stt_provider="groq", groq_api_key="gsk_test", groq_stt_model="w1")
    assert stt.transcribe(b"x", "a.webm", "audio/webm", settings=s) == "hello"
    assert seen == {"url": "https://api.groq.com/openai/v1/audio/transcriptions", "auth": "Bearer gsk_test", "model": "w1"}


def test_no_key_means_speech_is_reported_unavailable_not_faked():
    with pytest.raises(stt.SttUnavailable):
        stt.transcribe(b"x", "a.webm", "audio/webm", settings=Settings(stt_provider="groq", groq_api_key=""))
