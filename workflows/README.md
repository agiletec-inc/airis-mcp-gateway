# Workflow Recipes

LLM に MCP ツールの自動使用を指令するワークフローレシピ。
`behavior_compiler.py` がビルド時に読み込み、MCP initialize response の instructions フィールドに注入する。

## ワークフロー追加手順

1. 既存の YAML をコピーしてテンプレートにする
2. 全フィールドを記入（スキーマは下記参照）
3. `docker compose restart api` でリスタート → ログにバリデーションエラーがないか確認
4. Claude Code で実際にタスクを投げて、ワークフローが発火するか確認
5. PR を作成

## YAML スキーマ

```yaml
name: kebab-case-name              # 一意な識別子
compile_to: mcp_instructions       # ターゲットタイプ（現在は mcp_instructions のみ）
priority: high                     # high | medium | low
servers:                           # カバーするサーバー名リスト（behavior 重複排除用）
  - server-name
text: |                            # instructions に注入する確定テキスト（verbatim 出力）
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
