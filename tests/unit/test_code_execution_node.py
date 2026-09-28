# CMN-C1-015 — Unit Tests: CodeExecutionNode (main)

from framework.schemas.agent_status import AgentStatus
from src.nodes.code_execution_node import MAX_RETRIES, CodeExecutionNode

TRUST = "VERIFIED_EXTERNAL"


def _state(code, dataset, **extra):
    base = {
        "generated_code": code,
        "dataset": dataset,
        "caller_trust_level": TRUST,
        "status": "success",
        "retry_count": 0,
        "node_history": [],
        "error_log": [],
        "execution_time": {},
    }
    base.update(extra)
    return base


class TestCodeExecutionNode:
    def test_executes_and_returns_result(self, sales_dataset):
        node = CodeExecutionNode()
        out = node(_state("result = int(df['amount'].sum())", sales_dataset))
        assert out["status"] == AgentStatus.SUCCESS
        assert out["execution_result"] == "550"

    def test_runtime_error_triggers_retry(self, sales_dataset):
        node = CodeExecutionNode()
        out = node.execute(_state("result = df['missing'].sum()", sales_dataset, retry_count=0))
        assert out["status"] == AgentStatus.RETRY
        assert out["retry_count"] == 1
        assert "execution_error" in out["last_error"]

    def test_sandbox_violation_triggers_retry(self, sales_dataset):
        node = CodeExecutionNode()
        out = node.execute(_state("import os\nresult = 1", sales_dataset, retry_count=0))
        assert out["status"] == AgentStatus.RETRY
        assert "sandbox_violation" in out["last_error"]

    def test_retry_budget_exhausted_errors(self, sales_dataset):
        node = CodeExecutionNode()
        out = node.execute(_state("result = df['missing'].sum()", sales_dataset, retry_count=MAX_RETRIES))
        assert out["status"] == AgentStatus.ERROR
        assert out["error_log"]

    def test_upstream_error_passthrough(self, sales_dataset):
        node = CodeExecutionNode()
        # __call__ short-circuits an incoming error before execute(); verify the
        # node never overwrites it with SUCCESS.
        out = node(_state("result = 1", sales_dataset, status=AgentStatus.ERROR.value))
        assert out["status"] == AgentStatus.ERROR.value
        assert "execution_result" not in out
