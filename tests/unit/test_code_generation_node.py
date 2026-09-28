# CMN-C1-015 — Unit Tests: CodeGenerationNode (pre_process)

from framework.schemas.agent_status import AgentStatus
from src.nodes.code_generation_node import CodeGenerationNode
from tests.conftest import FakeLLM, fenced

TRUST = "VERIFIED_EXTERNAL"


def _state(question, dataset, **extra):
    base = {
        "user_input": question,
        "input_context": {"dataset": dataset} if dataset is not None else {},
        "caller_trust_level": TRUST,
        "status": "pending",
        "retry_count": 0,
        "node_history": [],
        "error_log": [],
        "execution_time": {},
    }
    base.update(extra)
    return base


class TestCodeGenerationNode:
    def test_signature_is_execute_state(self):
        import inspect

        params = list(inspect.signature(CodeGenerationNode.execute).parameters)
        assert params[:2] == ["self", "state"]
        assert "_invoke_impl" not in CodeGenerationNode.__dict__

    def test_generates_code_on_success(self, sales_dataset):
        node = CodeGenerationNode(llm=FakeLLM([fenced("result = int(df['amount'].sum())")]))
        out = node(_state("total amount?", sales_dataset))
        assert out["status"] == AgentStatus.SUCCESS
        assert out["generated_code"] == "result = int(df['amount'].sum())"
        assert out["dataset_summary"]["row_count"] == 4
        assert out["dataset_summary"]["columns"] == ["region", "amount"]

    def test_empty_question_rejected_by_s2(self, sales_dataset):
        node = CodeGenerationNode(llm=FakeLLM(["unused"]))
        out = node(_state("   ", sales_dataset))
        assert out["status"] == AgentStatus.ERROR.value
        assert any("empty" in e for e in out["error_log"])

    def test_missing_dataset_rejected(self):
        node = CodeGenerationNode(llm=FakeLLM(["unused"]))
        out = node(_state("q", None))
        assert out["status"] == AgentStatus.ERROR.value
        assert any("dataset" in e for e in out["error_log"])

    def test_oversize_dataset_rejected(self):
        from src.nodes.code_generation_node import MAX_ROWS

        big = [{"a": 1}] * (MAX_ROWS + 1)
        node = CodeGenerationNode(llm=FakeLLM(["unused"]))
        out = node(_state("q", big))
        assert out["status"] == AgentStatus.ERROR.value

    def test_retry_feeds_last_error_into_prompt(self, sales_dataset):
        llm = FakeLLM([fenced("result = int(df['amount'].sum())")])
        node = CodeGenerationNode(llm=llm)
        node.execute(_state("q", sales_dataset, last_error="execution_error: KeyError 'x'", retry_count=1))
        # The human message must carry the previous error so the model can fix it.
        human_msg = llm.calls[0][-1][1]
        assert "KeyError 'x'" in human_msg
