"""AgentCore Platform v1.0 — main: CodeExecutionNode."""

from __future__ import annotations

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services.code_sandbox import SandboxViolation, run_analysis

# Aligned with AgentBaseGraph.route()'s default max_retry (config.max_retry, 3).
# When the model cannot produce runnable code within this budget, fail closed.
MAX_RETRIES = 3


class CodeExecutionNode(FunctionNode):
    """Run the generated code in the restricted sandbox; drive the RETRY loop."""

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict) -> dict:
        # pre→main is an UNCONDITIONAL edge: if pre_process failed, route never
        # saw the status, so main must pass the error through untouched.
        if state.get("status") == AgentStatus.ERROR.value:
            return {"status": AgentStatus.ERROR.value}

        code = state.get("generated_code", "")
        dataset = state.get("dataset", [])
        retry_count = state.get("retry_count", 0)

        try:
            result = run_analysis(code, dataset)
        except Exception as e:  # noqa: BLE001 — sandbox/exec errors drive RETRY
            kind = "sandbox_violation" if isinstance(e, SandboxViolation) else "execution_error"
            message = f"{kind}: {e}"

            if retry_count < MAX_RETRIES:
                emit_trace_event(
                    "code_execution_failed",
                    {"kind": kind, "retry_count": retry_count, "next_attempt": retry_count + 1},
                    state,
                )
                return {
                    "status": AgentStatus.RETRY.value,
                    "retry_count": retry_count + 1,
                    "last_error": message,
                }

            emit_trace_event(
                "code_execution_exhausted",
                {"kind": kind, "retry_count": retry_count},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "last_error": message,
                "error_log": [f"CodeExecutionNode: giving up after {retry_count} retries — {message}"],
            }

        emit_trace_event("code_executed", {"retry_count": retry_count, "result_len": len(result)}, state)
        return {
            "execution_result": result,
            "status": AgentStatus.SUCCESS.value,
        }
