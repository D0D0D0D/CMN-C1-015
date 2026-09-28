# CMN-C1-015 — Integration: full 5-node backbone via DataAnalysisAgent.invoke()

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from src.graph.graph import DataAnalysisAgent
from tests.conftest import FakeLLM, fenced


def _agent_with_llm(responses):
    agent = DataAnalysisAgent()
    agent.compile()
    # The compiled graph references the same node instances held in _nodes,
    # so injecting the fake LLM here reaches the running pre_process node.
    agent._nodes["pre_process"]._llm = FakeLLM(responses)
    return agent


def _ctx():
    return InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)


class TestEndToEnd:
    def test_happy_path(self, sales_dataset):
        agent = _agent_with_llm([fenced("result = int(df['amount'].sum())")])
        out = agent.invoke("total amount?", ctx=_ctx(), input_context={"dataset": sales_dataset})
        assert out["status"] == AgentStatus.SUCCESS
        assert out["output"] == "550"
        assert out["node_history"] == [
            "InitializeNode", "CodeGenerationNode", "CodeExecutionNode",
            "ResultFormatterNode", "FinalizeNode",
        ]

    def test_retry_then_success(self, sales_dataset):
        agent = _agent_with_llm([
            fenced("result = df['MISSING'].sum()"),     # fails -> RETRY
            fenced("result = int(df['amount'].sum())"),  # fixed -> SUCCESS
        ])
        out = agent.invoke("total amount?", ctx=_ctx(), input_context={"dataset": sales_dataset})
        assert out["status"] == AgentStatus.SUCCESS
        assert out["output"] == "550"
        # pre_process ran twice (initial + one retry).
        assert out["node_history"].count("CodeGenerationNode") == 2

    def test_missing_dataset_finalizes_with_error(self, sales_dataset):
        agent = _agent_with_llm([fenced("result = 1")])
        out = agent.invoke("total?", ctx=_ctx(), input_context={})
        assert out["status"] == AgentStatus.ERROR.value

    def test_anonymous_caller_denied_by_s1(self, sales_dataset):
        agent = _agent_with_llm([fenced("result = int(df['amount'].sum())")])
        # Default ctx -> ANONYMOUS; nodes require VERIFIED_EXTERNAL.
        out = agent.invoke("total?", input_context={"dataset": sales_dataset})
        assert out["status"] == AgentStatus.ERROR.value
