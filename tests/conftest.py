"""Shared test fixtures for CMN-C1-015 DataAnalysisAgent.

No sys.modules stubs: the framework/shared packages come from the installed
`agenticstar-agentcore` wheel (wheel-era repo). Only a fake LLM is provided so
nodes are exercised without a network call or real credential.
"""

from __future__ import annotations

from typing import Iterator

import pytest

from shared.services.llm.base_llm import BaseLLM


class FakeLLM(BaseLLM):
    """A BaseLLM that returns pre-canned completions in order.

    Each call to complete() pops the next canned string and wraps it in the
    canonical completion shape. Useful for driving deterministic code-gen and
    the RETRY loop (queue a bad snippet then a good one).
    """

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[list] = []

    def complete(self, messages: list) -> dict:
        self.calls.append(messages)
        content = self._responses.pop(0) if self._responses else ""
        return {"content": content, "tool_calls": [], "model": "fake"}

    def stream(self, messages: list) -> Iterator[str]:
        yield self.complete(messages)["content"]

    def bind_tools(self, tools: list) -> "FakeLLM":
        return self


def fenced(code: str) -> str:
    """Wrap code in a ```python fence like a real LLM completion."""
    return f"Here is the analysis:\n```python\n{code}\n```\n"


@pytest.fixture
def sales_dataset() -> list[dict]:
    return [
        {"region": "east", "amount": 100},
        {"region": "west", "amount": 250},
        {"region": "east", "amount": 150},
        {"region": "west", "amount": 50},
    ]


@pytest.fixture
def agent_config() -> dict:
    """実 LLM 1 回転チェック用の Graph 構築 config。

    本 AG の現行 Graph は `config["llm"]` を読まず、統合テストは compile 後に
    `pre_process` node の `_llm` へ FakeLLM を直接差し込む。ここでは
    `tests/integration/test_end_to_end.py` と同じ構築前提に合わせ、追加 config は渡さない。
    """
    return {}


@pytest.fixture
def case_payload() -> str:
    """`tests/integration/test_end_to_end.py` の happy path と同じ質問文。"""
    return "total amount?"


@pytest.fixture
def live_input_context(sales_dataset) -> dict:
    """統合テストの `input_context` と同じ dataset seed。"""
    return {"dataset": sales_dataset}
