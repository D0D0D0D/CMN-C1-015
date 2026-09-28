# Test Specification

## Test Strategy
- Coverage target: ___%
- Test types: Unit / Integration / E2E

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | Type check pass, no Pydantic/dataclass | |
| TC-02 | SecurityViolationError fires on invalid input | Error raised | |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations (S-5 enforcement moved to CI by (internal issue reference removed)) | |
| TC-04 | InvocationContext via configurable only | Direct access raises error | |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` absent from `execute()` body | 0 duplicates |
| TC-06 | S-2: `_security_gate_input()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-07 | S-3: `_security_gate_output()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-08 | `required_trust_level` declared and enforced — dedicated S-1 boundary coverage MUST call `node(state)` (via `__call__`) for every privileged node, or use equivalent parameterized coverage | Insufficient trust level → execution refused *before* `execute()`; test must prove `execute()` was not called. Direct `node.execute(state)` is permitted only for isolated business-logic unit tests: it does not satisfy TC-08, but is not a finding when TC-08 and PB-6 coverage pass. | |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial when domain checks needed | Domain-specific input checks execute correctly (e.g. PII scan on additional fields, consent validation, business rules) | Hook body non-trivial |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial when domain checks needed | Domain-specific output checks execute correctly (e.g. nested credential scan, PII re-check, content filtering, preservation verification) | Hook body non-trivial |
| TC-11 | S-4: at least one domain `emit_trace_event()` inside each `execute()` | Domain event emitted on every invocation path | ≥1 per node |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures | |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass | |
| PB-3 | Level 2 → External service | Real external service connection | Data retrieved | |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations | |
| PB-5 | Checkpoint safety | No JWT/Pydantic in checkpoint | Inspection pass | |
| PB-6 | Invoke execution order | `__call__()`: S-1 trust gate → S-4 `node_start` → S-2 `_security_gate_input` → `execute()` → S-3 `_security_gate_output` → S-4 `node_complete` | Order verified | |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | | | | |
| BL-02 | | | | |

## Test Execution Summary
- Execution date: 
- Total tests: 
- Pass: / Fail: / Skip: 
- Coverage: ___%

---

## CMN-C1-015 DataAnalysisAgent — Test Implementation

- **Coverage target**: 全ノード（CodeGenerationNode / CodeExecutionNode / ResultFormatterNode）+ サンドボックス境界 + エンドツーエンド backbone。
- **Test types**: Unit（`tests/unit/`）/ Integration（`tests/integration/`）/ Proof-of-Boundary（`tests/proof_of_boundary/`）。
- **実行**: `python -m pytest tests/`（ローカル venv で 59 件 PASS、CI run-tests で再検証）。

### Unit（`tests/unit/`）

| File | カバー対象 | 主なケース |
|------|-----------|-----------|
| `test_code_generation_node.py` | pre_process | execute シグネチャ契約 / コード生成成功 / 空質問・dataset 欠落・サイズ超過の S-2 拒否 / retry 時の last_error 注入 |
| `test_code_execution_node.py` | main | 実行成功 / 実行エラー→RETRY(+retry_count) / SandboxViolation→RETRY / リトライ枯渇→ERROR / 上流エラーのパススルー |
| `test_result_formatter_node.py` | post_process | text/json/markdown 整形 / 不明フォーマットの text fallback / S-3 PII マスク |

### Integration（`tests/integration/test_end_to_end.py`）

| TC | シナリオ | 期待 |
|----|---------|------|
| happy_path | 質問→コード生成→実行→整形 | status SUCCESS, output=合計値, node_history 5 ノード |
| retry_then_success | 1 回失敗→RETRY→再生成で成功 | SUCCESS, CodeGenerationNode が 2 回出現 |
| missing_dataset | dataset 無し | status error（finalize で終端） |
| anonymous_caller | trust=ANONYMOUS | S-1 で拒否（status error） |

### Proof-of-Boundary（`tests/proof_of_boundary/`）

| PB | 境界 | 内容 |
|----|------|------|
| test_code_sandbox.py | **サンドボックス脱出耐性** | import / `__import__` / open / eval / exec / dunder チェーン（`__subclasses__`）/ getattr / pandas I/O（to_csv・read_csv）/ `df.eval`・`query` / globals / type+dunder / class/with をすべて SandboxViolation で拒否。正当な集計・groupby・numpy は実行可。`result` 未定義は ValueError。 |
| test_import_isolation.py | PB-4 Import 分離 | src/ に Level 0 import 無し |
| test_state_safety.py | PB-2/5 State 安全性 | credential フィールド名・Pydantic/InvocationContext 型を含まない |

### Framework Compliance（上表 TC-01〜11 への対応）
- TC-05/06/07/09/10/11: 3 ノードとも `FunctionNode` 継承で `_security_gate_*` を override せず `_extra_*` のみ実装、`execute` 内で `emit_trace_event` を最低 1 件発火（`test_*_node.py` と実装で担保）。
- TC-08: `required_trust_level=VERIFIED_EXTERNAL`、`test_end_to_end.py::test_anonymous_caller_denied_by_s1` で検証。

## 実 LLM 1 回転検証

モックだけで固めた実装は実 LLM を繋いだ瞬間に動かないことがあるため、注入シームへ実 LLM クライアントを刺して 1 回 invoke し、**中身のある出力が出ること**を確認している（`gitproject-dev-flow.md` §14-1-bis）。

| 項目 | 内容 |
|---|---|
| 実施日 | 2026-08-18 |
| 使用 LLM | ローカル CLI（Azure OpenAI `gpt-5.5`）を `BaseLLM` 実装として注入 |
| 注入シーム | `factory:src.nodes.code_generation_node.default_llm,src.services.llm_client.default_llm` |
| 実 LLM 呼び出し | 1 回 |
| 出力 | ['<text output: 3字>'] が非空。縮退理由なし |

本番の LLM は `AnthropicClient` 等で、これは検証用シーム。テンプレの `src/` は変更していない（一時テストを生成→実行→削除する方式）。CI には入れていない（ローカル CLI と鍵が要るため）。
