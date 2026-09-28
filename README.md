# CMN-C1-015 — DataAnalysisAgent

> **Category**: Cat 1 (single technical capability)
> **Industry**: CMN

## Overview

DataAnalysisAgent answers a quantitative question about a caller-supplied tabular dataset by
having a language model write pandas / NumPy code, then running that code in a restricted
namespace and rendering the result. The dataset is passed in as a list of JSON records; the
question is plain text. Nothing is read from disk, fetched over the network, or persisted.

It suits work where the data is already in hand and the question changes every time: an
application that answers ad-hoc aggregation questions over a result set it already holds, an
analyst tool that turns "what is the total by region?" into a computed answer, or a service that
needs a numeric answer plus the code that produced it.

The template is deliberately narrow about what it trusts:

- **Generated code is statically validated before it runs.** An AST pass rejects `import`
  statements, any identifier containing `__`, a fixed set of builtins (`eval`, `exec`, `open`,
  `getattr`, `globals`, …), and a fixed set of attribute names covering pandas and NumPy I/O
  (`read_csv`, `to_sql`, `load`, `tofile`, …), OS and subprocess entry points, and the
  submodules that re-expose them (`io`, `ctypeslib`, `lib`). Class definitions, `with`
  statements, `async` constructs and `global` / `nonlocal` are rejected outright.
- **pandas and NumPy are never handed to the generated code directly.** They are exposed as
  proxy objects carrying only an allow-listed set of attributes, so an attribute chain that the
  AST denylist did not anticipate has nothing to traverse to — it fails with `AttributeError`
  rather than reaching a file handle or a C library.
- **A failed execution is fed back, not hidden.** The error message is put into the next
  prompt and the model gets another attempt, up to three; after that the run ends as
  `status: error` rather than returning a guess.
- **The final answer must be explicit.** Generated code has to assign to a variable named
  `result`; code that runs cleanly but assigns nothing is an execution error.

What this is *not* is an isolation boundary. The sandbox is static analysis plus a restricted
namespace — there is no CPU, memory or wall-clock limit and no process or container boundary, so
a generated infinite loop still occupies the worker. Treat it as defence in depth for code the
agent itself produced, not as a jail for untrusted code.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Integration

Provide:

- an AgentCore runtime;
- an `ANTHROPIC_API_KEY` in the secret provider the runtime binds. The graph builds
  `CodeGenerationNode()` with no client, so the production path calls `default_llm()`, which
  constructs the framework's `AnthropicClient` (model `claude-sonnet-4-5`, temperature 0) from
  `current_secrets().require("ANTHROPIC_API_KEY")`. The key is never read from the process
  environment and never enters state. `config/agent.yaml` declares it under `requires.secrets`,
  alongside the `anthropic` extra under `requires.extras`;
- caller authentication in front of the entry adapter.

`CodeGenerationNode` takes an optional `BaseLLM` as its constructor argument, which is how the
test suite substitutes a fake. To run against a different provider, construct the node with your
own `BaseLLM` implementation in `DataAnalysisAgent.register_nodes()` — this template has no
`config["llm"]` seam.

`config/config.yaml` holds the runtime parameters, but note what actually consumes them: the
standalone server constructs `DataAnalysisAgent()` with no configuration, so the file applies
only when a caller loads it and passes it as `Graph(config=...)`.

| Key | Read by |
|---|---|
| `max_retry` (`3`) | The framework's router, when a configuration is supplied. The node's own retry ceiling is a module constant of the same value, so the effective limit is 3 either way |
| `output_format` (`text`) | Not read from this file. The renderer takes the format from state or `input_context["output_format"]`, accepting `text`, `json` or `markdown` and falling back to `text` for anything else |
| `allowed_libs`, `sandbox_mode`, `timeout_seconds` | Not read by any code path in this template. `run_analysis()` accepts an `allowed_libs` argument, but the execution node does not pass one, so both pandas and NumPy proxies are always exposed |

The template does not fetch, upload or parse files, does not connect to a database, does not
maintain a knowledge base, and does not persist anything between invocations.

## Input

`POST /invoke` takes a JSON body with `input` (the question) and an optional `session_id`. The
dataset is read from `input_context["dataset"]`, which the standalone adapter's request model
does **not** accept — so the full analysis path is reached by calling
`agent.invoke(question, ctx=..., input_context={"dataset": [...]})` in process, or through a
platform entry point that forwards `input_context`. An authenticated `/invoke` against the bare
standalone server therefore always comes back `status: error` with `output: null`, because the
dataset is missing.

Callers must be authenticated. The entry adapter resolves trust from verified middleware state
when present; otherwise, if `INVOKE_AUTH_TOKEN` is set on the server environment, a matching
`Authorization: Bearer` header promotes the caller to `VERIFIED_EXTERNAL`. A caller that is
neither middleware-verified nor token-authenticated is rejected with **401**, and a supplied
token that does not match is **401** as well. All three nodes require `VERIFIED_EXTERNAL`, so
there is no anonymous path into the graph.

```bash
curl -X POST http://127.0.0.1:8000/invoke \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${INVOKE_AUTH_TOKEN}" \
  -d '{"input": "total amount?", "session_id": "example-session"}'
```

The in-process call that carries data:

```python
result = agent.invoke(
    "total amount?",
    ctx=ctx,
    input_context={
        "dataset": [
            {"region": "east", "amount": 100},
            {"region": "west", "amount": 250},
            {"region": "east", "amount": 150},
        ]
    },
)
```

Input is rejected before any node body runs when the question is blank, `dataset` is absent, is
not a non-empty list, holds anything other than objects, or exceeds **10,000 rows**. Each case
ends as `status: error` with the reason recorded in the error log.

## Output

The standard AgentCore envelope is returned: `output`, `status`, `trace_id`, `correlation_id`
and `node_history`. `output` carries the rendered answer — the string form of the generated
code's `result` variable, wrapped according to the requested format:

```json
{
  "output": "550",
  "status": "success",
  "trace_id": "…",
  "correlation_id": "…",
  "node_history": ["InitializeNode", "CodeGenerationNode", "CodeExecutionNode",
                   "ResultFormatterNode", "FinalizeNode"]
}
```

`json` format renders `{"question": …, "result": …}`; `markdown` renders the question and a
fenced result block. Values above are illustrative; real output depends on the dataset and
question supplied.

## Security and Limitations

Every node declares `VERIFIED_EXTERNAL` trust, so the framework's trust gate stops an
insufficiently trusted caller before `execute()` runs — the entry adapter's 401 is the first of
two independent checks, not the only one. Input passes the framework's PII scan on the way in;
on the way out the credential scan runs first, and this template adds a PII mask over every
non-empty string in the result, replacing each finding with `[MASKED]`.

The sandbox limits are the honest boundary of this template:

- there is **no CPU, memory or wall-clock limit** and **no process or container boundary** — a
  generated infinite loop hangs the worker;
- the AST denylist enumerates names; a pandas or NumPy escape route that is not on the list is
  caught only by the allow-listed proxies, which is why the proxies, not the denylist, are the
  load-bearing control;
- the question and the dataset both reach the model in the prompt, so a dataset is only as
  private as the model endpoint it is sent to.

Output is machine-generated and assistive. A computed figure is only as good as the code the
model wrote for it, and neither the agent nor the retry loop verifies that the code answers the
question that was asked. It does not substitute for expert review, and any decision that matters
should be checked against the source data by a person.

## Release

- Version: 1.0.0
- Category: single technical capability (Cat 1), fixed five-node backbone
- Generation mode: `llm`
- HITL: not enabled
- Persistence: none — no checkpointer is configured
- Required trust level: `VERIFIED_EXTERNAL`

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent is built to run on the platform, which supplies the secret provider and the entry authentication in front of it. Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Supplied by the platform's own package registry at build time. It is not published on public PyPI, so `pip install -e .` alone does not fetch it. |
| pandas, NumPy | Declared as exact pins in `pyproject.toml`; installed by `pip install -e .` |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run on AGENTIC STAR, and the agent does not fall back to a degraded
mode when the platform is absent. It does not, however, refuse to start: the standalone server in
`src/api/server.py` compiles the graph and provisions its secret provider at import, `/health`
returns `{"status": "ok"}`, and `/invoke` answers. What it cannot do is produce a result. Without
`INVOKE_AUTH_TOKEN` set, every `/invoke` is **401**; with it set and a valid bearer token, the
request reaches the graph but the standalone request model carries no dataset, so the run ends
`status: error` with `output: null`. The test suite runs without a platform connection, using a
fake language model.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## Documentation

`docs/02_design.md` carries the node flow, the state schema and the sandbox design.
`docs/03_test_spec.md` records the test specification and the verification results.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and test specifications
```

See `docs/02_design.md` for the design and `docs/03_test_spec.md` for the test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.
