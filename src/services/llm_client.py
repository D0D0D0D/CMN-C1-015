"""AgentCore Platform v1.0 — LLM injection seam for DataAnalysisAgent.

`framework.llm` does not exist in the wheel, so the template owns its own LLM
seam (the GovernmentProcedureQAAgent pattern).  Nodes depend on the abstract
``shared.services.llm.base_llm.BaseLLM`` and accept an injected instance, which
makes them trivially testable with a fake.  In production, ``default_llm()``
builds an Anthropic-backed client, sourcing the API key from the per-request
bound :class:`SecretProvider` (never ``os.environ``).
"""

from __future__ import annotations

import re

from shared.services.llm.base_llm import BaseLLM


def default_llm(model: str = "claude-sonnet-4-5") -> BaseLLM:
    """Build the production LLM client from the bound secret provider.

    Imported lazily so unit tests (which inject a fake BaseLLM) never need
    langchain_anthropic or a real credential.
    """
    from framework.secrets.context import current_secrets
    from shared.services.llm.anthropic_client import AnthropicClient

    api_key = current_secrets().require("ANTHROPIC_API_KEY")
    return AnthropicClient({"api_key": api_key, "model": model, "temperature": 0.0})


_CODE_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_code(content: str) -> str:
    """Pull a Python code block out of an LLM completion.

    Accepts either a fenced ```python ... ``` block or, as a fallback, the raw
    content (already code).  Returns the stripped code string.
    """
    m = _CODE_FENCE.search(content or "")
    if m:
        return m.group(1).strip()
    return (content or "").strip()
