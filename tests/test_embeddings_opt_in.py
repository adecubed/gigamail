"""Mail text goes to OpenAI only when the user asks for it.

The search memory used to pick OpenAI embeddings whenever OPENAI_API_KEY
was in the environment. MCP clients such as Claude Code pass their whole
environment to the server, so a key set for something else was enough to
send mail text to api.openai.com. Now OpenAI needs
GIGAMAIL_EMBEDDINGS=openai."""
import pytest
import requests

from gigamail.core import mail_memory


class _Ok:
    status_code = 200

    def json(self):
        return {"embedding": [0.0, 1.0], "data": [{"index": 0, "embedding": [0.0, 1.0]}]}


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_post(url, *args, **kwargs):
        seen.append(url)
        return _Ok()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(mail_memory, "_embed_backend", None)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.delenv("GIGAMAIL_EMBEDDINGS", raising=False)
    return seen


def _openai(urls):
    return [u for u in urls if "openai.com" in u]


def test_a_key_in_the_environment_is_not_consent(calls):
    assert mail_memory._detect_embed_backend() == "ollama"
    mail_memory._get_embeddings_batch(["Quote request for Via Roma 10"])
    assert calls and not _openai(calls)


def test_openai_when_chosen(calls, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_EMBEDDINGS", "openai")
    assert mail_memory._detect_embed_backend() == "openai"
    assert _openai(calls)


def test_openai_chosen_without_a_key_sends_nothing(calls, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_EMBEDDINGS", "OpenAI")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert mail_memory._detect_embed_backend() is None
    assert calls == []


def test_off_contacts_nobody(calls, monkeypatch):
    monkeypatch.setenv("GIGAMAIL_EMBEDDINGS", "off")
    assert mail_memory._detect_embed_backend() is None
    assert mail_memory._get_embeddings_batch(["hello"]) == [None]
    assert calls == []
