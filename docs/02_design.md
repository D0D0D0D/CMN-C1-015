# Template Design Specification — CMN-C1-015 DataAnalysisAgent

## Position in AgentCore Architecture

- **Agent Class**: DataAnalysisAgent
- **L1 Base**: **AgentBaseGraph**（固定 5 ノード backbone。autonomous な think⇄act ループではないため AutonomousBaseGraph は採用しない）
- **Three-Layer Separation**:
  - State: flat TypedDict composition（Pydantic 不使用 — msgpack 非互換のため）
  - Node: L1 継承（Template Method: `execute(self, state: dict) -> dict` のみ override）
  - Graph: composition（`register_nodes()` で 3 スロットを差し替え）

## Architecture Overview

本テンプレートは「呼び出し元が渡したデータセットに対する定量的質問への回答」という
**単一の汎用能力**を提供する Cat 1 エージェント。LLM がデータセットのスキーマを見て
pandas/numpy のコードを生成し（pre_process）、制限付きサンドボックスで実行し（main）、
結果を検証・整形する（post_process）。実行エラー時は backbone の `RETRY → pre_process`
ループ（最大 `max_retry` 回・既定 3）でエラー内容をフィードバックして再生成し自己修正する。
これは ReAct の Think→Act→Observe を固定 backbone 上に写したもので、自律的なツール選択は
行わない（あくまで「コード生成→実行→検証」の単機能ループ）。

### Node Configuration

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | スキーマ初期化・trust 保持 | — | schema_version, session_id | InitializeNode (default) |
| pre_process | 入力検証 + データセット取り込み + スキーマ要約 + LLM によるコード生成（retry 時は `last_error` を反映） | user_input, input_context, last_error | validated_input, dataset, dataset_summary, generated_code | **CodeGenerationNode** (FunctionNode) |
| main | 生成コードをサンドボックス実行。成功→SUCCESS / 実行失敗→retry 余地あれば RETRY(+retry_count) / 尽きたら ERROR | generated_code, dataset, retry_count | execution_result, status, retry_count, last_error | **CodeExecutionNode** (FunctionNode) |
| post_process | `output_format` に応じた整形 + S-3 機密/PII マスク | execution_result, input_context | formatted_output | **ResultFormatterNode** (FunctionNode) |
| finalize | メタデータ集計 | — | response_metadata | FinalizeNode (default) |

### Data Flow

```
START → initialize → pre_process(CodeGen) → main(CodeExec) → {route} → post_process(Formatter) → finalize → END
                              ↑                                   │
                              └──────────── RETRY (status=retry, retry_count<max) ──────────┘
```

route は `main` の後に `state["status"]` を読む（SUCCESS→post / RETRY→pre / それ以外→finalize）。
`add_edges()` / `route()` は override しない（backbone 既定を使う）。

### State Definition

`AgentState`（共有フィールド）を継承し、以下のエージェント固有フィールドのみ追加する。

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| dataset | list[dict] | 分析対象のレコード配列（`input_context["dataset"]` から取り込み） | Yes |
| dataset_summary | dict | LLM プロンプト用の列名・dtype・行数の要約 | Yes |
| generated_code | str | LLM が生成した pandas/numpy コード | Yes |
| execution_result | str | サンドボックス実行結果（`result` 変数の文字列化） | No |
| last_error | str | 直近の実行/検証エラー（retry 時にプロンプトへ注入） | No |
| output_format | str | `text` / `json` / `markdown`（既定 text） | No |

**State Constraints (mandatory):**
- Flat TypedDict only（primitives + JSON-serializable のみ）
- State に JWT / API キー / credential を入れない（checkpoint DB 漏洩防止。フィールド名にも `token`/`secret`/`key` 等を使わない）
- InvocationContext は `config["configurable"]` 経由のみ（State に入れない）
- Pydantic / dataclass / 任意 Python オブジェクトを入れない（msgpack 非互換）

## Framework Utilization

### Shared Components Used
- [x] InvocationContext（correlation_id, session_id, caller_trust_level）
- [x] S-1: 各ノード `required_trust_level = TrustLevel.VERIFIED_EXTERNAL`（`BaseNode.__call__` が execute 前に自動強制）
- [x] S-2: `_extra_security_gate_input()` — pre_process でデータセットサイズ上限・空入力チェック（デフォルト PII マスクの後に走る。`_security_gate_input()` は override しない）
- [x] S-3: `_extra_security_gate_output()` — post_process で出力文字列の PII を `detect_pii` で検出しマスク（デフォルト credential scan の後に走る。`_security_gate_output()` は override しない）
- [x] S-4: `emit_trace_event()` — 各 execute 内で最低 1 件のドメインイベント（例: `code_generated`, `code_executed`, `result_formatted`。`node_start/complete/error` は framework が自動発火するため重複させない）

> **S-2/S-3 gate behaviour（ADR-017）**: 本テンプレートの全ドメインノードは `FunctionNode` 継承。
> framework の `@final` ゲート（S-2 PII マスク / S-3 credential scan）が常に自動実行され、
> ドメイン拡張は `_extra_security_gate_input()` / `_extra_security_gate_output()` で行う。

### Composition Pattern

- **Pattern**: Standalone（単一 AgentBaseGraph。サブグラフ・リモート呼び出しなし）
- **Error propagation strategy**: main が上流の `status="error"` を素通し（pre→main は無条件辺のため main 冒頭で早期パススルー）。実行失敗は RETRY、リトライ枯渇で ERROR。

### サンドボックス設計（セキュリティの核）

LLM 生成コードを実行するため、`src/services/code_sandbox.py` で **二段の境界**を設ける。
1. **AST 静的検査**: `import`（許可モジュール以外）/ dunder 属性アクセス / `eval`・`exec`・`open`・
   `__import__`・`getattr`・`compile` 等の危険呼び出しを構文木で拒否。
2. **制限名前空間での実行**: `__builtins__` を安全サブセットに差し替え、`pd`/`np`/`df`（データセット）
   のみ注入。生成コードは最終回答を `result` 変数へ代入する規約。
- 許可ライブラリは `config.allowed_libs`（既定 pandas, numpy, math, statistics）。
- 既知の限界: CPU/メモリ/壁時計のハード隔離は本テンプレートのスコープ外（運用ガイドに明記。
  プロセス/コンテナ隔離は将来課題）。AST + builtins 制限が一次防御線。

## Import Isolation Confirmation
- [x] Level 0（agenticstar）を import しない
- [x] import 先は framework/ と shared/ のみ（agents/base/ 不要）

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | 固定 backbone + 有界 RETRY で十分。自律的ツール選択は不要（Cat 1） |
| Composition pattern | Standalone | GraphNode subgraph | **Standalone** | 単一能力のため内側グラフ不要 |
| コード実行ループ | main 内で複数回試行 | backbone RETRY→pre_process | **backbone RETRY** | framework が提供する自己修正ループを利用し、生成と実行の責務を分離 |
| サンドボックス | shared `code_executor`（placeholder） | テンプレ内 AST+制限 builtins | **テンプレ内自前実装** | 共有版は placeholder。Cat 1 のコア能力として自前で安全に実装 |
