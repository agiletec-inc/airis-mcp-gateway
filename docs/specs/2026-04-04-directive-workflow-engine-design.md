# Directive Workflow Engine 設計仕様書

> **Status (2026-04-13):** この文書は設計段階のドラフトを保存した履歴で、実装は意図的に簡素化されました。実装と一致する部分だけを参照し、詳細は末尾の **Implementation delta** セクションを優先してください (#76)。

## コンテキスト

AIRIS MCP Gateway の Dynamic MCP はツールトークンを ~98% 削減済み（42k → ~600 tokens）。しかし LLM は接続された MCP ツールを自発的に使わない。現在の `behavior_compiler.py` は「WHEN X → Use Y」という提案を生成するだけで、LLM はこれを無視できる。

**問題**: ツールは接続されているのに使われない。LLM に「このタスクにはこのツールを使え」と強制する仕組みがない。

**特に深刻な例**: LLM は学習データが古いにもかかわらず、既知のライブラリ（Next.js, React 等）のドキュメントを確認せずにコードを書く。公式ドキュメントには最新のサンプルコードが丁寧に用意されているのに、古い知識で実装してバグを生む。

**ゴール**: 特定のタスクパターンを検出したら、LLM がユーザーの指示なしに所定のワークフローを自動的に実行する状態にする。

**アプローチ**: A+C ハイブリッド — 高頻度ワークフローは Directive Instructions で強制 + それ以外は airis-find フォールバックでオンデマンド発見。

## アーキテクチャ

### コンパイルフロー

```
workflows/*.yaml + mcp-config.json
    │
    ▼ (ビルド時)
behavior_compiler.py
    │
    ▼
MCP initialize response の instructions フィールド (~1500 tokens 上限)
    │
    ▼
LLM が読んで従う（指令）
```

### ファイル構造

```
workflows/                          # ワークフローレシピ (YAML)
├── implement-feature.yaml          # 高頻度: ライブラリ/API 使用時
├── web-research.yaml               # 高頻度: 調査・検索時
├── data-query.yaml                 # 高頻度: DB 操作時
└── README.md                       # ワークフロー追加ガイド

apps/api/src/app/core/
├── behavior_compiler.py            # 改修: workflow YAML → instructions にコンパイル
├── workflow_loader.py              # 新規: YAML 読み込み + バリデーション
└── dynamic_mcp.py                  # 変更なし（fallback は instructions で対応）
```

## Workflow YAML スキーマ (v1)

```yaml
# workflows/implement-feature.yaml
name: implement-feature
description: "ライブラリ/API 実装時に公式ドキュメントを必ず参照するワークフロー"
priority: high          # high | medium | low
max_tokens: 200         # バリデーション閾値（超過でビルドエラー）
servers:                # このワークフローがカバーするサーバー名
  - context7

trigger: "implementing with any library, framework, or external API"

compile_to: |
  ### Implementing with Libraries/APIs
  WHEN writing code that uses ANY library, framework, or external API:
  1. FIRST: Call context7:resolve-library-id to identify the library
  2. THEN: Call context7:query-docs to read official documentation
  3. THEN: Write implementation following official examples and patterns
  NEVER skip this workflow. Your training data is outdated.
  Official documentation has current, working sample code — use it.
```

### フィールド定義

| フィールド | 必須 | 説明 |
|-----------|------|------|
| `name` | Yes | 一意な識別子（kebab-case） |
| `description` | Yes | 人間向けの説明（LLM には送信しない） |
| `priority` | Yes | `high` / `medium` / `low` — トークンバジェット内での優先度 |
| `max_tokens` | Yes | バリデーション閾値。`compile_to` がこれを超えたらビルドエラー |
| `servers` | Yes | このワークフローがカバーするサーバー名リスト。behavior 重複排除に使用 |
| `trigger` | Yes | 人間向けのトリガー説明（ドキュメント用、ランタイムマッチングなし） |
| `compile_to` | Yes | instructions に注入する確定テキスト。テンプレート処理なし |

### 意図的に除外（YAGNI）

- `steps` フィールド（airis-route 連携は v2 で検討）
- 動的テンプレート変数
- プロジェクトローカルオーバーライド（`.airis/workflows/` マージは v2）

## トークン見積もりとバリデーション

### 見積もりロジック

```python
def estimate_tokens(text: str) -> int:
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii_chars = len(text) - ascii_chars
    # ASCII: ~4文字/token、非ASCII（日本語等）: ~2文字/token
    return (ascii_chars // 4) + (non_ascii_chars // 2)
```

`compile_to` に日本語が混じると 1文字 ≒ 1-2 トークンになるため、ASCII 前提の `chars/4` は使わない。非 ASCII 文字は `chars/2` で見積もる。

### バリデーション

- `compile_to` のトークン見積もりが `max_tokens` を超えた場合 → **ビルドエラー**（動的トランケートはしない）
- エラーメッセージ例: `Workflow 'implement-feature' exceeds max_tokens: estimated 250 > limit 200`

## Priority 制御ロジック

1. `workflows/*.yaml` を全読み込み
2. priority でソート（high > medium > low）、同 priority 内はファイル名順
3. 全 `high` の `compile_to` を結合 → トークン数計算
4. ワークフローセクションのバジェット（~800 tokens）に余裕があれば `medium` を追加
5. 余裕がなければスキップ → ビルド時に warning ログ出力（スキップされたワークフロー名を表示）
6. `low` は大幅に余裕がある場合のみ

### トークンバジェット内訳

| セクション | バジェット |
|-----------|-----------|
| ヘッダー + 指令前文 | ~100 tokens |
| ワークフロー指令（3-5個） | ~800 tokens |
| フォールバック指令 | ~200 tokens |
| サーバー一覧（自動生成） | ~150 tokens |
| **合計** | **~1250 tokens** |

## コンパイル結果（instructions 出力）

```
This is AIRIS MCP Gateway with Dynamic MCP.
All 60+ tools are accessed through airis-exec.

## Required Workflows
You MUST follow these workflows. They are directives, not suggestions.

### Implementing with Libraries/APIs
WHEN writing code that uses ANY library, framework, or external API:
1. FIRST: Call context7:resolve-library-id to identify the library
2. THEN: Call context7:query-docs to read official documentation
3. THEN: Write implementation following official examples and patterns
NEVER skip this workflow. Your training data is outdated.
Official documentation has current, working sample code — use it.

### Web Research
WHEN you need current information, external data, or best practices:
1. Call tavily:tavily-search with a focused search query
2. Synthesize results before proceeding with implementation

### Database Operations
WHEN querying, modifying, or analyzing database data:
1. Call supabase:query with the appropriate SQL statement

## Tool Discovery Fallback
If your task requires capabilities NOT covered by the Required Workflows above,
you MUST call airis-find with keywords describing what you need before attempting the task.
Do NOT proceed without checking available tools first.

## Available Servers
context7, tavily, supabase, stripe, cloudflare, figma, memory, github, ...
```

**Available Servers は `mcp-config.json` から自動生成。** 全サーバー名（disabled 含む）を列挙。手動メンテ不要。

## 実装変更

### 1. `workflow_loader.py`（新規 — ~80行）

```python
@dataclass
class WorkflowConfig:
    name: str
    description: str
    priority: str       # "high" | "medium" | "low"
    max_tokens: int
    servers: list[str]  # カバーするサーバー名
    trigger: str
    compile_to: str

def load_workflows(workflows_dir: Path) -> list[WorkflowConfig]:
    """全ワークフロー YAML を読み込み、バリデーション、ソートして返す。"""
    # - workflows_dir/*.yaml を glob
    # - 各 YAML をパース
    # - 必須フィールドのバリデーション
    # - compile_to トークン数 <= max_tokens のバリデーション（超過でエラー）
    # - priority → ファイル名でソート

def validate_workflow(config: WorkflowConfig) -> list[str]:
    """バリデーションエラーのリストを返す。"""
    # - name が kebab-case
    # - priority が {high, medium, low}
    # - compile_to が非空
    # - compile_to トークン見積もり <= max_tokens
    # - servers が非空リスト
```

### 2. `behavior_compiler.py`（改修）

主な変更点:
- `load_workflows()` を呼び出してワークフローを読み込み
- ワークフローの `compile_to` を priority 順に結合
- ワークフローの `servers` でカバー済みのサーバーを除外して、残りの behavior を "Additional Tool Hints" として出力
- サーバー一覧を `server_configs` から自動生成

```python
def compile_instructions(server_configs: dict[str, McpServerConfig]) -> str:
    sections = [
        _BASE_INSTRUCTIONS,
        _compile_workflow_section(),        # NEW: ワークフロー指令
        _compile_fallback_section(),        # NEW: airis-find フォールバック
        _compile_server_list(server_configs),  # NEW: 自動生成サーバー一覧
    ]

    # ワークフローでカバー済みのサーバーを抽出
    workflow_servers = set()
    for wf in workflows:
        workflow_servers.update(wf.servers)

    # カバーされていないサーバーの behavior を追加
    remaining = _compile_behavior_lines(server_configs, exclude=workflow_servers)
    if remaining:
        sections.append("## Additional Tool Hints\n" + "\n".join(remaining))

    return "\n\n".join(sections)
```

### 3. 初期ワークフローファイル（3個）

| ファイル | priority | servers | 要点 |
|---------|----------|---------|------|
| `implement-feature.yaml` | high | context7 | 全ライブラリ/API で公式ドキュメント必須 |
| `web-research.yaml` | high | tavily | 最新情報・調査は web 検索必須 |
| `data-query.yaml` | high | supabase | DB 操作は supabase:query |

3つとも high。DB 操作も agiletec プロジェクト群では高頻度であり、3つ合計でも ~800 tokens のバジェット内に収まるため。

### 4. `workflows/README.md`

```markdown
# Workflow Recipes

LLM に MCP ツールの自動使用を指令するワークフローレシピ。

## ワークフロー追加手順

1. 既存の YAML をコピーしてテンプレートにする
2. 全フィールドを記入（特に compile_to は英語で、強い指令語を使う）
3. `task docker:restart` でビルド → バリデーションエラーがないか確認
4. Claude Code で実際にタスクを投げて、ワークフローが発火するか確認
5. PR を作成

## 指令文の書き方

- MUST, FIRST, THEN, NEVER を使う（提案ではなく指令）
- 「Your training data is outdated」のような理由を添える
- 1ワークフロー ~150-200 tokens 以内
- compile_to は英語で書く（instructions はLLMのシステムプロンプトに注入されるため）
```

## 既存 behavior config との共存

現在の `mcp-config.json` の behavior 設定は **そのまま動作する**。

- ワークフロー YAML の `servers` フィールドでカバー済みのサーバー → behavior は instructions から除外（ワークフローが優先）
- カバーされていないサーバー → 従来通り "Additional Tool Hints" セクションで出力
- 破壊的変更なし

## テスト

### ユニットテスト
- `test_workflow_loader.py`: YAML パース、バリデーション（必須フィールド欠落、トークン超過、不正 priority、非 ASCII トークン見積もり）
- `test_behavior_compiler.py`: ワークフローコンパイル、priority 順序、トークンバジェット制御、サーバー一覧自動生成、behavior 重複排除

### 統合テスト
- Gateway 起動 → MCP initialize レスポンスの instructions フィールドにワークフロー指令が含まれることを確認

### フォールバック発火テスト（手動）

実装後に Claude Code で以下を検証:

| テストケース | 期待動作 |
|-------------|---------|
| 「Stripe で決済機能を実装して」 | airis-find が呼ばれる（Stripe はワークフロー外） |
| 「Next.js でページを作って」 | context7:resolve-library-id が呼ばれる（implement-feature 発火） |
| 「Hono でミドルウェアを作って」 | context7:resolve-library-id が呼ばれる（馴染みの薄いライブラリでも確実に発火するか確認） |
| 「最新の React ベストプラクティスを調べて」 | tavily:tavily-search が呼ばれる（web-research 発火） |

airis-find が呼ばれない場合はフォールバック指令の文言を強化:
```
WARNING: Attempting any task involving external services without calling airis-find first
will result in incorrect implementations based on outdated knowledge.
```

## 既知の制約 (v1)

1. **プロジェクトローカルオーバーライドなし**: 全ワークフローはグローバル。v2 で `.airis/workflows/` マージ追加
2. **ランタイムトリガーマッチングなし**: trigger フィールドはドキュメント用。LLM の判断に委ねる
3. **ワークフロー間の重複**: 複合タスクで複数ワークフローが該当する場合、LLM が判断（v1 は許容）
4. **トークン見積もりは近似**: 実際のトークン数と ~10% の誤差あり

## 将来 (v2 候補、スコープ外)

- `.airis/workflows/` プロジェクトローカルオーバーライド + マージ戦略
- `steps` フィールドで airis-route 連携
- ランタイムメトリクス: LLM がどのワークフローに従ったかを追跡
- ワークフロー有効性スコアリング（ツール呼び出しパターンから算出）

---

## Implementation delta (2026-04-13)

上記の仕様は YAGNI を適用した簡素化版として実装されました。実装とのズレを以下に記録します (#76)。この節と実装の内容が一致していれば、上の仕様本文は「当初の意図」として読み、実際の挙動を確認するときはこの節を最優先してください。

### WorkflowConfig (5 フィールドに簡素化)

`apps/api/src/app/core/workflow_loader.py` で実装されている dataclass は次のとおり。

```python
@dataclass
class WorkflowConfig:
    name: str               # kebab-case 識別子
    compile_to: str         # 注入先を識別するターゲット種別 (e.g. "mcp_instructions")
    priority: str           # "high" | "medium" | "low"
    text: str               # instructions に注入する確定テキスト
    servers: list[str] = field(default_factory=list)
```

仕様本文との差分:

| 仕様 (当初)                           | 実装                     | 備考 |
|---------------------------------------|---------------------------|------|
| `description`                         | 削除                      | 説明はファイルコメントで賄う |
| `max_tokens`                          | 削除                      | トークン見積もり機構ごと廃止 |
| `trigger`                             | 削除                      | ランタイムマッチングをしないので不要 |
| `compile_to` = 注入テキスト本体       | `compile_to` = ターゲット種別 | 注入テキスト本体は `text` フィールドに分離 |
| (新設) `text`                         | `text` が本文             | `compile_to: "mcp_instructions"` と組で使う |

### バリデーション

`validate_workflow()` は廃止され、モジュール内部の `_validate()` が同等のチェックを行います。対象:

- `name` が非空かつ kebab-case
- `priority` が {high, medium, low} のいずれか
- `compile_to` が非空
- `text` が非空

**トークン数のバリデーションと `max_tokens` 閾値チェックは実装されていません**。関連して `estimate_tokens()` / トークンバジェット制御 (`~800 tokens` の上限、`medium`/`low` のスキップ) も存在しません。現状は workflow ファイルを書くときに手動でサイズに気をつける運用です。

### コンパイルフロー

`apps/api/src/app/core/behavior_compiler.py` にある関数は次の 1 つだけです。

```python
def _compile_workflow_texts(workflows: list[WorkflowConfig]) -> str:
    ...
```

仕様で挙げていた `_compile_workflow_section` / `_compile_fallback_section` / `_compile_server_list` の 3 分割は実装されず、`_compile_workflow_texts()` が workflows を単純連結して返します。フォールバック指令 (airis-find 誘導) は `_BASE_INSTRUCTIONS` 側の固定文言として埋め込まれており、実行時に `mcp-config.json` から自動生成するサーバー一覧 (`_compile_server_list`) も廃止されています。

### 実装済みファイル

- `apps/api/src/app/core/workflow_loader.py` (loader + validator)
- `apps/api/src/app/core/behavior_compiler.py` (`_compile_workflow_texts`)
- `workflows/implement-feature.yaml`, `workflows/web-research.yaml`, `workflows/data-query.yaml`, `workflows/proactive-usage.yaml`, `workflows/tool-routing.yaml`
- `apps/api/tests/unit/test_workflow_loader.py`, `test_behavior_compiler.py`

### 将来スペック復活のトリガー

次のいずれかが必要になった時点で、本仕様書の対応セクションを復活させるか別 issue で再設計します。

- workflow の自動トランケート / 優先度ベースのバジェット制御が実運用で必要になった
- 複数プロジェクトが同じ Gateway を共有して project-local override が必要になった
- instructions のサイズが実測で肥大化し始めた (`~1500 tokens` 近辺)
