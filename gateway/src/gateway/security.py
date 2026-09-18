"""Credential resolution and safe logging helpers.

Keys are never logged: the ``redact`` helper strips bearer-token style values
from any text before it reaches a logger or report.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from .errors import ConfigurationError

_TOKEN_PATTERNS = (
    re.compile(r"(?i)\b(sk-[a-zA-Z0-9_-]{8,}|sk-ant-[a-zA-Z0-9_-]{8,}|pk-[a-zA-Z0-9_-]{8,})"),
    re.compile(r"(?i)(Bearer|Authorization|Api-Key)\s*[:=]?\s*(\S{8,})"),
)


def redact(text: str) -> str:
    """Replace token-shaped values with ``***`` in a copy of ``text``."""
    out = text
    for pattern in _TOKEN_PATTERNS:
        out = pattern.sub(lambda m: m.group(1) + "=***" if m.lastindex == 2 else "***", out)
    return out


def redact_mapping(mapping: Mapping[str, object]) -> dict[str, object]:
    return {k: redact(str(v)) if isinstance(v, str) else v for k, v in mapping.items()}


def resolve_api_key(
    *,
    env: Mapping[str, str],
    api_key: str | None,
    api_key_env: str | None,
    allow_missing: bool = False,
) -> str | None:
    """Resolve the effective API key for a provider.

    Precedence: explicit key > ``api_key_env`` from ``env``. Raises
    :class:`ConfigurationError` when no key is found and ``allow_missing`` is
    False. Remote endpoints that ship with no auth (e.g. Ollama) should pass
    ``allow_missing=True``.
    """
    env = env if env is not None else os.environ
    if api_key:
        return api_key
    if api_key_env:
        value = env.get(api_key_env)
        if value:
            return value
    if allow_missing:
        return None
    raise ConfigurationError(
        f"No API key available for provider. "
        f"Set it directly or via env var {api_key_env or '<unset api_key_env>'}."
    )


def parse_env_key(value: str) -> tuple[str | None, str | None]:
    """Parse an opencode-style ``{env:VAR}`` value into (api_key, api_key_env)."""
    match = re.fullmatch(r"\{env:(.+)\}", value.strip())
    if match:
        return None, match.group(1)
    return (value, None) if value else (None, None)
