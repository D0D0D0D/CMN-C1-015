"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects
# cause silent corruption.  Extend AgentState with agent-specific
# fields only.  Do NOT add credentials, secrets, or Pydantic models.

from __future__ import annotations

from typing import NotRequired

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """DataAnalysisAgent state.

    All shared fields (user_input, status, session_id, node_history,
    error_log, retry_count, hitl_*, etc.) are inherited from AgentState.
    Only msgpack-safe, JSON-serializable fields are added below — no
    DataFrame objects, no credentials.
    """

    # Tabular dataset taken from input_context["dataset"] (list of records).
    dataset: NotRequired[list[dict]]
    # Schema summary (columns, dtypes, row_count) used to prompt the LLM.
    dataset_summary: NotRequired[dict]
    # The pandas/numpy code the LLM generated for the current attempt.
    generated_code: NotRequired[str]
    # String form of the sandbox `result` variable on success.
    execution_result: NotRequired[str]
    # Last execution/validation error, injected into the prompt on RETRY.
    last_error: NotRequired[str]
    # Output rendering: "text" | "json" | "markdown" (default "text").
    output_format: NotRequired[str]
