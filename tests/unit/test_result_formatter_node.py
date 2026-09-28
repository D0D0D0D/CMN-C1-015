# CMN-C1-015 — Unit Tests: ResultFormatterNode (post_process)

import json

from framework.schemas.agent_status import AgentStatus
from src.nodes.result_formatter_node import ResultFormatterNode

TRUST = "VERIFIED_EXTERNAL"


def _state(result, fmt="text", **extra):
    base = {
        "execution_result": result,
        "validated_input": "what is the total?",
        "output_format": fmt,
        "caller_trust_level": TRUST,
        "status": "success",
        "retry_count": 0,
        "node_history": [],
        "error_log": [],
        "execution_time": {},
    }
    base.update(extra)
    return base


class TestResultFormatterNode:
    def test_text_format(self):
        out = ResultFormatterNode().execute(_state("550"))
        assert out["status"] == AgentStatus.SUCCESS
        assert out["formatted_output"] == "550"

    def test_json_format(self):
        out = ResultFormatterNode().execute(_state("550", fmt="json"))
        parsed = json.loads(out["formatted_output"])
        assert parsed["result"] == "550"
        assert parsed["question"] == "what is the total?"

    def test_markdown_format(self):
        out = ResultFormatterNode().execute(_state("550", fmt="markdown"))
        assert "**Result:**" in out["formatted_output"]
        assert "550" in out["formatted_output"]

    def test_unknown_format_falls_back_to_text(self):
        out = ResultFormatterNode().execute(_state("550", fmt="xml"))
        assert out["formatted_output"] == "550"

    def test_s3_masks_pii_in_output(self):
        # Goes through __call__ so the @final S-3 gate + _extra hook run.
        out = ResultFormatterNode()(_state("contact john@example.com for details"))
        assert "john@example.com" not in out["formatted_output"]
        assert "[MASKED]" in out["formatted_output"]
