# Directive Workflow Engine 設計仕様書

> **Status (2026-05-22):** この文書は現行実装に一致するよう全面更新済み (#76)。
> 当初は 7-field の `WorkflowConfig` + トークンバジェット制御を持つ設計だったが、
> YAGNI を適用して 5-field + バジェット制御なしに簡素化して実装された。
> 簡素化前のドラフト設計は末尾「History」を参照。

## コンテキスト

AIRIS MCP Gateway の Dynamic MCP はツールトークンを ~98% 削減済み（42k → ~600 tokens）。しかし LLM は接続された MCP ツールを自発的に使わない。`behavior_compiler.py` が「WHEN X → Use Y」という提案を生成するだけでは、LLM はこれを無視できる。

**問題**: ツールは接続されているのに使われない。LLM に「このタスクにはこのツールを使え」と強制する仕組みがない。

**特に深刻な例**: LLM は学習データが古いにもかかわらず、既知のライブラリ（Next.js, React 等）のドキュメントを確認せずにコードを書く。公式ドキュメントには最新のサンプルコードが用意されているのに、古い知識で実装してバグを生む。

**ゴール**: 特定のタスクパターンに対し、LLM がユーザーの指示なしに所定のワークフローを実行する状態にする。

**アプローチ**: A+C ハイブリッド — 高頻度ワークフローを Directive Instructions で強制 + それ以外は airis-find フォールバックでオンデマンド発見。

## アーキテクチャ

### コンパイルフロー

```
workflows/*.yaml
    │
    ▼ workflow_loader.load_workflows()
list[WorkflowConfig]  （バリデーション済み・priority 順）
    │
    ▼ behavior_compiler.compile_instructions(server_configs)
MCP initialize response の instructions フィールド
    │
    ▼
LLM が読んで従う（指令）
```

ワークフローはランタイムにマッチングされるのではなく、Gateway 起動時に `mcp-config.json` の server config と合わせて instructions 文字列へコンパイルされ、MCP `initialize` レスポンスに乗る。`behavior_compiler.py` / `workflow_loader.py` を変更した場合は Docker イメージの再ビルドが必要（`docs` フォルダ外の挙動なので CLAUDE.md の Debugging 節を参照）。

### ファイル構造

```
workflows/                          # ワークフローレシピ (YAML)
├── implement-feature.yaml          # high: ライブラリ/API 使用時
├── web-research.yaml               # high: 調査・検索時
├── data-query.yaml                 # high: DB 操作時
├── proactive-usage.yaml            # ツールの能動的利用を促す指令
├── tool-routing.yaml               # ツール選択のルーティング指針
└── README.md                       # ワークフロー追加ガイド

apps/api/src/app/core/
├── workflow_loader.py              # YAML 読み込み + バリデーション + ソート
├── behavior_compiler.py            # workflow texts + behavior + routing → instructions
└── routing_engine.py               # routing-table.json → Quick Routes セクション
```

## Workflow YAML スキーマ

実装は `apps/api/src/app/core/workflow_loader.py` の `WorkflowConfig` dataclass。

```yaml
# workflows/implement-feature.yaml
name: implement-feature
compile_to: mcp_instructions
priority: high
servers:
  - context7

text: |
  ## Required Workflows
  You MUST follow these workflows. They are directives, not suggestions.

  ### Implementing with Libraries/APIs
  WHEN writing code that uses ANY library, framework, or external API:
  1. FIRST: Call context7:resolve-library-id to identify the library
  2. THEN: Call context7:query-docs to read official documentation
  3. THEN: Write implementation following official examples and patterns
  NEVER skip this workflow. Your training data is outdated.
  Official documentation has current, working sample code — use it.
```

### フィールド定義

```python
@dataclass
class WorkflowConfig:
    name: str                 # kebab-case 識別子
    compile_to: str           # 注入先ターゲット種別 (例: "mcp_instructions")
    priority: str             # "high" | "medium" | "low"
    text: str                 # instructions に注入する確定テキスト
    servers: list[str] = []   # このワークフローがカバーするサーバー名
```

| フィールド | 必須 | 説明 |
|-----------|------|------|
| `name` | Yes | 一意な識別子（kebab-case）。`^[a-z][a-z0-9]*(-[a-z0-9]+)*$` |
| `compile_to` | Yes | 注入先ターゲット種別。`instructions` へ出力したいものは `mcp_instructions` を指定 |
| `priority` | Yes | `high` / `medium` / `low`。連結順の制御に使用 |
| `text` | Yes | instructions に注入する確定テキスト。テンプレート処理なし、verbatim 出力 |
| `servers` | No | このワークフローがカバーするサーバー名リスト。指定したサーバーは behavior 行から除外される。省略時は空リスト |

YAML パースに失敗したファイル、mapping でないファイルは warning ログを出してスキップされる。未指定フィールドは `name`/`compile_to`/`text` が空文字、`priority` が `"medium"`、`servers` が `[]` として扱われ、その後バリデーションで弾かれる。

### 意図的に実装していないフィールド（YAGNI）

| 当初ドラフトにあったもの | 不採用の理由 |
|--------------------------|--------------|
| `description` | 説明はファイル先頭コメントで賄う |
| `max_tokens` / トークン見積もり | バジェット制御機構ごと不採用（後述） |
| `trigger` | ランタイムのトリガーマッチングをしないため不要 |
| `steps`（airis-route 連携） | v2 で検討 |
| 動的テンプレート変数 | verbatim 出力で十分 |
| プロジェクトローカルオーバーライド | v2 で検討 |

## バリデーション

`workflow_loader._validate()` がチェックする。エラーがあるワークフローは `logger.error` でログ出力し、ロード対象から除外される（ビルド失敗にはしない）。

- `name` が非空、かつ kebab-case
- `priority` が `{high, medium, low}` のいずれか
- `compile_to` が非空
- `text` が非空（`strip()` 後も非空）

**トークン数のバリデーションは存在しない。** `max_tokens` 閾値チェック、`estimate_tokens()`、バジェット超過によるビルドエラーはいずれも未実装。instructions のサイズは workflow ファイルを書くときに手動で気をつける運用。

## Priority とソート

`load_workflows()` は読み込んだワークフローを `(priority_order, filename)` でソートする。

- `PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}`（未知の priority は `1` = medium 扱い）
- 同 priority 内はファイル名の昇順

**priority によるスキップ／トランケートは行わない。** 当初設計の「ワークフローセクション ~800 tokens のバジェットに収まる範囲で high → medium → low を採用」というバジェット制御は実装されていない。priority は連結順を決めるだけで、全ワークフローが instructions に出力される。

## instructions の構成

`behavior_compiler.compile_instructions(server_configs)` が以下のセクションを `\n\n` で連結する。

| 順序 | セクション | 由来 |
|------|-----------|------|
| 1 | base instructions | `_BASE_INSTRUCTIONS` 定数（airis-find / airis-schema の案内） |
| 2 | `## Additional Meta-Tools` | `_META_TOOLS_SECTION` 定数 |
| 3 | workflow texts | `_compile_workflow_texts(workflows)`。空なら `_TOOL_ROUTING_GUIDE` 定数にフォールバック |
| 4 | `## Proactive Tool Usage` | `_compile_behavior_lines()`。behavior 行が 1 件以上ある場合のみ |
| 5 | `## Quick Routes` | `routing_engine.format_routing_table_as_instructions()`。`routing-table.json` がある場合のみ |

### 3. workflow texts のコンパイル

`_compile_workflow_texts(workflows)` は `compile_to == "mcp_instructions"` かつ `text` が非空のワークフローを priority 順に `text` を `\n\n` で単純連結する。テンプレート展開・変数置換はない（verbatim）。

仕様で当初挙げていた `_compile_workflow_section` / `_compile_fallback_section` / `_compile_server_list` の 3 分割関数は実装されていない。フォールバック指令（airis-find への誘導）は `_BASE_INSTRUCTIONS` と `_TOOL_ROUTING_GUIDE` の固定文言に埋め込まれており、`mcp-config.json` からサーバー一覧を自動生成する機構（`_compile_server_list`）も廃止された。

### 4. behavior 行のコンパイル

`_compile_behavior_lines(server_configs, exclude)` は、各 server config の `behavior`（`triggers` と `instruction` の両方を持つもの）から `WHEN <triggers を " / " で連結> → <instruction> [server_name]` という行を生成し、priority 順にソートして返す。

`exclude` には全ワークフローの `servers` フィールドの和集合が渡され、ワークフローでカバー済みのサーバーは behavior 行から除外される（ワークフロー指令が優先）。

## 実装ファイル

- `apps/api/src/app/core/workflow_loader.py` — `WorkflowConfig`, `load_workflows()`, `_validate()`
- `apps/api/src/app/core/behavior_compiler.py` — `compile_instructions()`, `_compile_workflow_texts()`, `_compile_behavior_lines()`
- `apps/api/src/app/core/routing_engine.py` — `format_routing_table_as_instructions()`（Quick Routes セクション）
- `workflows/implement-feature.yaml`, `web-research.yaml`, `data-query.yaml`, `proactive-usage.yaml`, `tool-routing.yaml`, `README.md`

## テスト

- `apps/api/tests/unit/test_workflow_loader.py` — YAML パース、バリデーション（必須フィールド欠落、不正 priority、kebab-case 違反）、priority ソートを検証。

**`behavior_compiler.py` 専用のユニットテストは未実装。** 当初仕様で挙げていた `test_behavior_compiler.py`（ワークフローコンパイル、priority 順序、behavior 重複排除の検証）は存在しない。core モジュールのテストカバレッジ不足は #85 で追跡している。

### フォールバック発火テスト（手動）

実装後に Claude Code で以下を検証する想定。

| テストケース | 期待動作 |
|-------------|---------|
| 「Stripe で決済機能を実装して」 | airis-find が呼ばれる（Stripe はワークフロー外） |
| 「Next.js でページを作って」 | context7:resolve-library-id が呼ばれる（implement-feature 発火） |
| 「最新の React ベストプラクティスを調べて」 | tavily:tavily-search が呼ばれる（web-research 発火） |

## 既知の制約

1. **プロジェクトローカルオーバーライドなし**: 全ワークフローはグローバル。
2. **ランタイムトリガーマッチングなし**: ワークフローは起動時に全件コンパイルされる。発火判断は LLM に委ねる。
3. **トークンバジェット制御なし**: instructions のサイズ管理は手動運用。
4. **`behavior_compiler.py` のテストなし**: #85 で追跡。

## 将来 (v2 候補、スコープ外)

次のいずれかが必要になった時点で、対応する設計を別 issue で再検討する。

- workflow の自動トランケート / 優先度ベースのバジェット制御（instructions が実測で肥大化し始めた場合）
- `.airis/workflows/` プロジェクトローカルオーバーライド + マージ戦略（複数プロジェクトが同一 Gateway を共有する場合）
- `steps` フィールドで airis-route 連携
- ランタイムメトリクス: LLM がどのワークフローに従ったかを追跡

---

## History

この文書は当初、より複雑な設計のドラフトだった。実装時に YAGNI を適用して簡素化された主な差分は以下。

| 当初ドラフト | 現行実装 |
|--------------|----------|
| 7-field `WorkflowConfig`（`description`, `max_tokens`, `trigger` を含む） | 5-field（`name`, `compile_to`, `priority`, `text`, `servers`） |
| `compile_to` = 注入テキスト本体 | `compile_to` = ターゲット種別、本体は `text` フィールドに分離 |
| `estimate_tokens()` + `max_tokens` 超過でビルドエラー | トークン見積もり機構ごと廃止 |
| `~800 tokens` バジェット内で priority ベースに採用／スキップ | priority は連結順のみ、全件採用 |
| `_compile_workflow_section` / `_compile_fallback_section` / `_compile_server_list` の 3 分割 | `_compile_workflow_texts()` 1 関数で単純連結。フォールバックは固定文言 |
| `validate_workflow()`（公開関数） | `_validate()`（モジュール内部関数） |
| サーバー一覧を `mcp-config.json` から自動生成 | 廃止 |
