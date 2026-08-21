"""Model backends. Pick one with DEVFLOW_PROVIDER."""

from __future__ import annotations

from .base import (
    END_TURN,
    MAX_TOKENS,
    REFUSAL,
    TOOL_USE,
    Provider,
    ToolCall,
    ToolResult,
    Turn,
    json_schema_of,
)

__all__ = [
    "END_TURN",
    "MAX_TOKENS",
    "REFUSAL",
    "TOOL_USE",
    "Provider",
    "ToolCall",
    "ToolResult",
    "Turn",
    "build_provider",
    "json_schema_of",
]


def build_provider(settings) -> Provider:
    """Construct the configured backend.

    Imports are deferred so that running against an open model does not require
    the `anthropic` package to be installed, and vice versa.
    """
    kind = (settings.provider or "anthropic").lower()

    if kind == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            model=settings.model,
            max_tokens=settings.max_tokens,
            effort=settings.effort,
            api_key=settings.api_key or None,
            base_url=settings.base_url or None,
        )

    if kind in {"openai_compat", "openai", "ollama", "vllm", "openrouter"}:
        from .openai_compat import OpenAICompatProvider

        base_url = settings.base_url or _DEFAULT_BASE_URLS.get(kind)
        if not base_url:
            raise ValueError(
                "provider '{}' needs DEVFLOW_BASE_URL (e.g. http://localhost:11434/v1)"
                .format(kind)
            )
        return OpenAICompatProvider(
            model=settings.model,
            base_url=base_url,
            max_tokens=settings.max_tokens,
            api_key=settings.api_key,
            temperature=settings.temperature,
        )

    raise ValueError(
        "unknown DEVFLOW_PROVIDER '{}'; expected 'anthropic' or 'openai_compat'".format(
            kind
        )
    )


_DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434/v1",
    "vllm": "http://localhost:8000/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
}
