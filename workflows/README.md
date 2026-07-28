# Workflow recipes

MCPツールの使い方をLLMへ渡すレシピ。実行契約は
`apps/api/src/app/core/workflow_loader.py` と `behavior_compiler.py`、回帰契約は
`apps/api/tests/unit/test_workflow_loader.py` と `test_airis_workflow.py` が所有する。

## 配信先

- `mcp_instructions`: Gateway起動時にMCP `initialize` の `instructions` へ常時注入する。
- `airis_workflow`: 常時注入せず、`airis-workflow`メタツールが`topic`指定で返す。

常時注入は全リクエストのコンテキストを消費する。安全上常時必要な短い指令だけに使い、手順は
`airis_workflow`へ置く。

## YAML契約

```yaml
name: implement-feature
compile_to: airis_workflow
priority: high
servers:
  - context7
topic: implementation
text: |
  必要時に返す指令本文
```

- `name`: 一意なkebab-case。
- `compile_to`: `mcp_instructions`または`airis_workflow`。
- `priority`: `high`、`medium`、`low`。出力順だけを決め、件数やtokenを制限しない。
- `text`: そのまま配信する本文。テンプレート展開はしない。
- `servers`: このレシピが所有するserver。重複するbehavior行を除外する。
- `topic`: `airis_workflow`で取得する場合のキー。

不正なYAMLはログを出して除外される。サイレントに有効化されたと仮定せず、追加・変更時は次を実行する。

```bash
cd apps/api
uv run pytest tests/unit/test_workflow_loader.py tests/unit/test_airis_workflow.py -q
```

挙動確認が必要ならAPIを再起動し、MCP `initialize`応答または`airis-workflow`の実レスポンスを確認する。
