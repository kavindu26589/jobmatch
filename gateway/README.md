# opencode-gateway

A small, provider-agnostic LLM gateway. It is designed around **opencode's
ber model** — any API key or base URL that works with opencode works here,
and the same provider config block from `opencode.json` can be loaded
directly.

- Default provider **`zen`**: `https://opencode.ai/zen/v1` with
  `OPENCODE_API_KEY` (from [opencode.ai/auth](https://opencode.ai/auth)).
- OpenAI-compatible and Anthropic-compatible protocols.
- Structured output, tool calling, streaming, retries, rate limiting,
  circuit breaking, and per-call cost accounting.

```bash
pip install -e gateway[dev]
```

```python
from gateway import build_registry, LLMGateway, structured

gateway = LLMGateway(build_registry())
answer = gateway.structured(
    "zen",
    "gpt-5.4-mini",
    system="You extract facts.",
    user="John 5 years Python",
    schema=Person,
)
```

See `../app` for a complete job-matching application built on it.