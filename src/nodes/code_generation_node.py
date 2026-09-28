"""AgentCore Platform v1.0 — pre_process: CodeGenerationNode."""

# Node contract (agents_layer_design.md §1):
#  - Extend FunctionNode; implement execute(state) -> dict
#  - Return ONLY the fields this node changes (never full state)
#  - Domain S-2 checks go in _extra_security_gate_input (NOT _security_gate_input)
#  - S-4: emit at least one domain trace event inside execute()

from __future__ import annotations

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.services.llm.base_llm import BaseLLM
from shared.utils.audit_logger import emit_trace_event

from src.services.llm_client import default_llm, extract_code

# Defensive ceiling on caller-supplied data (rows) — keeps an oversized dataset
# from ballooning the prompt / sandbox. Tune via review if needed.
MAX_ROWS = 10_000


class CodeGenerationNode(FunctionNode):
    """Validate input and ask the LLM for pandas/numpy code answering the question."""

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: BaseLLM | None = None) -> None:
        # Injection seam: tests pass a fake BaseLLM; production falls back to
        # the Anthropic client built from the bound secret provider.
        self._llm = llm

    # ── S-2 input gate extension (runs after the default PII scan) ──────────
    def _extra_security_gate_input(self, state: AgentState) -> AgentState:
        state = dict(state)  # type: ignore[assignment]
        question = state.get("user_input", "") or ""
        dataset = (state.get("input_context") or {}).get("dataset")

        reason: str | None = None
        if not question.strip():
            reason = "user_input (question) is empty"
        elif dataset is None:
            reason = "input_context['dataset'] is missing"
        elif not isinstance(dataset, list) or not dataset:
            reason = "input_context['dataset'] must be a non-empty list of records"
        elif not all(isinstance(r, dict) for r in dataset):
            reason = "input_context['dataset'] records must be objects (dicts)"
        elif len(dataset) > MAX_ROWS:
            reason = f"dataset too large: {len(dataset)} rows (max {MAX_ROWS})"

        if reason:
            state["status"] = AgentStatus.ERROR.value
            # error_log uses an operator.add reducer — return only the new entry.
            state["error_log"] = [f"CodeGenerationNode: {reason}"]
        return state  # type: ignore[return-value]

    def execute(self, state: dict) -> dict:
        # pre→main is unconditional, but pre is reached either from initialize
        # or via RETRY (status=retry); a rejected input is short-circuited by
        # __call__ before execute(), so no ERROR passthrough is needed here.
        question = state.get("user_input", "")
        dataset = state["input_context"]["dataset"]
        last_error = state.get("last_error") or ""

        summary = _summarize(dataset)
        messages = _build_messages(question, summary, last_error)

        llm = self._llm or default_llm()
        completion = llm.complete(messages)
        code = extract_code(completion.get("content", ""))

        emit_trace_event(
            "code_generated",
            {"retry_count": state.get("retry_count", 0), "code_len": len(code), "retry": bool(last_error)},
            state,
        )

        return {
            "validated_input": question,
            "dataset": dataset,
            "dataset_summary": summary,
            "generated_code": code,
            "last_error": "",  # clear stale error so it is not reused
            "status": AgentStatus.SUCCESS.value,
        }


def _summarize(dataset: list[dict]) -> dict:
    """Build a compact schema summary (no pandas needed) for the prompt."""
    columns = list(dataset[0].keys())
    dtypes: dict[str, str] = {}
    for col in columns:
        dtype = "unknown"
        for row in dataset:
            v = row.get(col)
            if v is not None:
                dtype = type(v).__name__
                break
        dtypes[col] = dtype
    return {
        "columns": columns,
        "dtypes": dtypes,
        "row_count": len(dataset),
        "sample_rows": dataset[:3],
    }


def _build_messages(question: str, summary: dict, last_error: str) -> list:
    system = (
        "You are a data analyst. Write Python code using pandas (as pd) and "
        "numpy (as np) to answer the user's question about a DataFrame named "
        "`df`. Rules: assign the final answer to a variable named `result`. "
        "Do NOT import anything, read/write files, or access dunder attributes "
        "— `df`, `pd`, `np`, `math`, `statistics` are already available. "
        "Return ONLY a Python code block."
    )
    user = (
        f"Question: {question}\n\n"
        f"DataFrame schema:\n"
        f"- columns: {summary['columns']}\n"
        f"- dtypes: {summary['dtypes']}\n"
        f"- row_count: {summary['row_count']}\n"
        f"- sample_rows: {summary['sample_rows']}\n"
    )
    if last_error:
        user += (
            f"\nYour previous code failed with this error — fix it:\n{last_error}\n"
        )
    return [("system", system), ("human", user)]
