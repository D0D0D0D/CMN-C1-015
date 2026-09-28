"""AgentCore Platform v1.0 — post_process: ResultFormatterNode."""

from __future__ import annotations

import json

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.security.pii_detector import detect_pii
from shared.utils.audit_logger import emit_trace_event

_VALID_FORMATS = ("text", "json", "markdown")


class ResultFormatterNode(FunctionNode):
    """Render the execution result and apply the domain S-3 PII mask."""

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict) -> dict:
        # post_process is only routed to on SUCCESS, but stay defensive.
        if state.get("status") == AgentStatus.ERROR.value:
            return {"status": AgentStatus.ERROR.value}

        result = state.get("execution_result", "")
        question = state.get("validated_input", state.get("user_input", ""))
        fmt = (state.get("output_format") or (state.get("input_context") or {}).get("output_format") or "text")
        if fmt not in _VALID_FORMATS:
            fmt = "text"

        if fmt == "json":
            formatted = json.dumps({"question": question, "result": result}, ensure_ascii=False)
        elif fmt == "markdown":
            formatted = f"**Question:** {question}\n\n**Result:**\n\n```\n{result}\n```"
        else:
            formatted = result

        emit_trace_event("result_formatted", {"format": fmt, "length": len(formatted)}, state)
        return {
            "formatted_output": formatted,
            "status": AgentStatus.SUCCESS.value,
        }

    # ── S-3 output gate extension (runs after the default credential scan) ──
    def _extra_security_gate_output(self, result: dict) -> dict:
        """Mask any PII (emails, phone numbers, etc.) in string outputs."""
        for key, value in result.items():
            if not isinstance(value, str) or not value:
                continue
            findings = detect_pii(value)
            if not findings:
                continue
            masked = value
            for f in reversed(findings):  # reverse to keep offsets valid
                masked = masked[: f["start"]] + "[MASKED]" + masked[f["end"]:]
            result[key] = masked
        return result
