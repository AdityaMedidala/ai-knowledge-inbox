import pytest
from pydantic import ValidationError

from app.config import Settings

BASE = {"_env_file": None, "embedding_provider": "fake"}


def test_openai_compatible_requires_base_url_and_api_key() -> None:
    with pytest.raises(ValidationError, match="LLM_BASE_URL and LLM_API_KEY"):
        Settings(**BASE, llm_provider="openai_compatible", llm_model="m")


def test_openai_key_not_required_without_an_openai_provider() -> None:
    settings = Settings(
        **BASE,
        llm_provider="openai_compatible",
        llm_model="m",
        llm_base_url="https://api.groq.com/openai/v1",
        llm_api_key="gsk",
    )
    assert settings.openai_api_key is None


def test_openai_key_required_when_a_provider_is_openai() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(**BASE, llm_provider="openai", llm_model="m")


def test_llm_model_required_for_real_chat_providers() -> None:
    with pytest.raises(ValidationError, match="LLM_MODEL is required"):
        Settings(**BASE, llm_provider="openai", openai_api_key="sk")


def test_free_defaults() -> None:
    settings = Settings(_env_file=None, embedding_provider="fake", llm_provider="fake")
    fields = Settings.model_fields
    assert fields["embedding_provider"].default == "fastembed"
    assert (settings.embedding_model, settings.embedding_dim) == ("BAAI/bge-small-en-v1.5", 384)
    assert settings.chunk_tokens == 350


def test_jev_verifier_requires_an_openrouter_key() -> None:
    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY"):
        Settings(_env_file=None, embedding_provider="fake", llm_provider="fake", verifier="jev")


def test_verifier_is_off_by_default() -> None:
    assert (
        Settings(_env_file=None, embedding_provider="fake", llm_provider="fake").verifier == "off"
    )
