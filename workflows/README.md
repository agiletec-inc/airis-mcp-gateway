# Workflow Recipes

LLM に MCP ツールの安全な使い方を指令するワークフローレシピ。`workflow_loader.py` が読み込み、`compile_to` で配信先が決まる:

- `compile_to: mcp_instructions` — `behavior_compiler.py` が MCP initialize response の instructions フィールドに注入(常時ロード)。
- `compile_to: airis_workflow` — initialize には dump されず、`airis-workflow` メタツールが `topic` 指定で on-demand に返す。

## ワークフロー追加手順

1. 既存の YAML をコピーしてテンプレートにする
2. 全フィールドを記入（スキーマは下記参照）
3. `docker compose restart api` でリスタート → ログにバリデーションエラーがないか確認
4. Claude Code で実際にタスクを投げて、ワークフローが発火するか確認
5. PR を作成

## YAML スキーマ

```yaml
name: kebab-case-name              # 一意な識別子
compile_to: mcp_instructions       # mcp_instructions（initialize に注入）| airis_workflow（airis-workflow ツールで on-demand 配信）
priority: high                     # high | medium | low
servers:                           # カバーするサーバー名リスト（behavior 重複排除用、任意）
  - server-name
topic: database                    # airis_workflow の場合のトピックキー（airis-workflow ツールの enum と一致）
text: |                            # 確定テキスト（verbatim 出力）
  ### Section Title
  WHEN condition:
  1. FIRST: Call tool:name
  2. THEN: Next step
  NEVER skip this.
```

## 指令文の書き方

- **MUST, FIRST, THEN, NEVER** を使う（提案ではなく指令）
- 理由を添える（例: `Your training data is outdated.`）
- `text` は英語で書く（LLM のシステムプロンプトに注入されるため）
- `text` はそのまま出力される（テンプレート処理なし）

## Priority

- `high`: 必ず instructions に含まれる
- `medium`: 通常含まれるが、将来のバジェット制御で除外される可能性
- `low`: 優先度が低い
