# Architecture

## 責務

AIRIS MCP Gatewayはlocal Streamable HTTP/SSE endpointと、Context7 subprocessのlifecycleを所有する。
clientはglobal登録せず、skillから短命sessionを作る。

```text
agent skill -> localhost:9400/mcp -> transport bridge -> Context7 process
```

provider-native agent、credential store、browser、Git、filesystem、memory、一般web検索はgatewayの外側に置く。
gateway containerへ`~/.codex`、`~/.claude`等をmountしない。

## 正本

- install時のregistry template: `config/mcp-config.template.json`
- local runtime state: `mcp-config.json`。commitしない
- tracked最小例: `mcp-config.json.example`。server inventoryではない
- transport/API: `apps/api/src/app/api/endpoints/`
- process lifecycle: `apps/api/src/app/core/`
- version: `VERSION`

schema shaping、dynamic routing等のlegacy codeは現行consumerを確認してから削除する。存在するcodeを現行製品機能と
文書で主張しない。新しいserverを追加する場合は、Context7専用境界を変更するarchitecture decisionが必要。

## 不変条件

- exact library/framework documentation以外へgatewayをroutingしない。
- disabled/missing serverへsilent fallbackしない。
- transport bridgeはSSE iteratorを途中closeしない。
- external write capabilityやprovider credentialをgatewayへ集約しない。
- metrics/statusをenforcementそのものとして扱わない。
