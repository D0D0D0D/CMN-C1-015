"""AgentCore Platform v1.0"""

# ─────────────────────────────────────────────────────────────────────────────
# Template Category (Cat) — choose ONE based on your Cat judgment:
#
# Cat 1 — Single technical capability (use-case-agnostic)
#   Purpose : Delivers one reusable, domain-independent capability.
#             The same template can be dropped into any project unchanged.
#   Examples: TextSummarizer, EmbeddingGenerator, LanguageDetector,
#             SentimentAnalyzer, KeywordExtractor
#   Parent  : AgentBaseGraph
#   Pipeline: START → initialize → pre_process → main → {route} → post_process → finalize → END
#                                             ↓ (RETRY, max 3)
#                                          pre_process
#   See src/examples/graph_cat1_sample.py for a full example.
#
# Cat 2 — Multi-step domain workflow (job-to-be-done)
#   Purpose : Orchestrates multiple steps to accomplish a specific business
#             outcome. The template name describes the outcome, not the
#             individual capabilities it uses.
#   Examples: InvoiceTriageAgent, ContractGapDetectionAgent,
#             ResumeScreeningAgent, SupportTicketResolutionAgent
#   Parent  : AgentBaseGraph (outer graph) + GraphNode in the `main` slot
#             wrapping an inner BaseGraph/AgentBaseGraph (domain workflow)
#   Pipeline: Same fixed 5-node backbone as Cat 1; domain complexity is
#             encapsulated inside DomainWorkflowGraphNode.get_subgraph().
#   Layout  : src/graph/graph.py                 ← outer graph (this file)
#             src/graph/domain_workflow_graph.py ← inner graph
#   See src/examples/graph_cat2_sample.py and src/examples/domain_workflow_graph_sample.py for examples.
#
# Cat 3 — Autonomous think→act→observe loop (self-directed)
#   Purpose : Runs an LLM-driven loop that decides its own next action,
#             executes tools, observes results, and terminates when the task
#             is complete or a budget/iteration ceiling is hit.
#   Examples: ResearchAgent, AutonomousCodeReviewAgent,
#             DataExplorationAgent, MultiStepPlannerAgent
#   Parent  : AutonomousBaseGraph
#   Pipeline: START → initialize → think ⇄ act → finalize → END
#   Config  : budget_usd and llm are required in config.yaml.
#   See src/examples/graph_cat3_sample.py for a full example.
#
# ── How to choose ─────────────────────────────────────────────────────────────
#
#   Ask: "Does this template solve a specific business problem end-to-end?"
#     No  → Cat 1 (generic capability)
#     Yes → "Does it need an autonomous reasoning loop to decide its steps?"
#       No  → Cat 2 (fixed multi-step workflow)
#       Yes → Cat 3 (LLM-driven loop)
#
# framework.* imports are unchanged; agent-local imports use the src. prefix.
# ─────────────────────────────────────────────────────────────────────────────

from framework.graph.agent_base_graph import AgentBaseGraph
from src.nodes.code_generation_node import CodeGenerationNode
from src.nodes.code_execution_node import CodeExecutionNode
from src.nodes.result_formatter_node import ResultFormatterNode
from src.schemas.state import State


class DataAnalysisAgent(AgentBaseGraph):
    """CMN-C1-015 DataAnalysisAgent — fixed 5-node backbone (Cat 1).

    Generic data-analysis capability: an LLM generates pandas/numpy code to
    answer a quantitative question about a caller-supplied tabular dataset; the
    code runs in a restricted sandbox; the result is verified and formatted.
    Execution failures drive the bounded RETRY -> pre_process backbone loop so
    the model can self-correct (max_retry, default 3).
    """

    @property
    def name(self) -> str:
        return "cmn_c1_015"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        # super() injects the "initialize" and "finalize" slots automatically;
        # this template uses the defaults (no custom InitializeNode/FinalizeNode).
        super().register_nodes()  # injects InitializeNode + FinalizeNode

        # Domain pipeline slots (required — fill all three):
        #   pre_process : CodeGenerationNode — LLM generates pandas/numpy code
        #   main        : CodeExecutionNode  — runs it in the restricted sandbox
        #   post_process: ResultFormatterNode — renders + S-3 PII mask
        self._nodes["pre_process"]  = CodeGenerationNode()
        self._nodes["main"]         = CodeExecutionNode()
        self._nodes["post_process"] = ResultFormatterNode()
