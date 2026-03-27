from __future__ import annotations

from .mistral_client import MistralAIClient
from .mock_client import MockAIClient
from .openai_client import OpenAIClient


def get_ai_client(provider: str):
    provider = (provider or "mock").lower()
    if provider == "mock":
        return MockAIClient()
    if provider == "mistral":
        return MistralAIClient()
    if provider == "openai":
        return OpenAIClient()
    raise ValueError(f"Unsupported AI provider: {provider}")
