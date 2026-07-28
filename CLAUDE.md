# AIRIS MCP Gateway

必要時だけ起動するlocal MCP endpoint。現行の保持対象はContext7 process serverのみ。runtime registryは
install時のregistry templateは`config/mcp-config.template.json`、local runtimeは`mcp-config.json`。
`mcp-config.json.example`は空の最小例でserver一覧の正本ではない。通常のfile/Git/web/browser操作へ使わない。

## 推測できない境界

- global MCP serverとして常設登録しない。agentは`airis-mcp-gateway` skillから短命sessionを作る。
- native project fileは手書き正本であり、generated markerを追加しない。
- Streamable HTTP bridgeはSSE iteratorの最初のeventを`__anext__()`で読み、同じiteratorをreaderへ渡す。
  `async for ... break`はhttpx streamをcloseするため使わない。
- initialize instructionの正本は`workflows/*.yaml`。Pythonへ散文を複製しない。`compile_to`、`priority`、`text`
  の欠落はliteral値を配信する既知事故になる。
- `mcp-config.json`にないserverやSupabase等を勝手に有効化しない。browser、Git、file generationはhost側の
  native tool/skillを使う。
- source変更後はlocal processのrestartだけで済むと仮定せず、container imageをrebuildして反映を確認する。
- `VERSION`がrelease正本。manifest側のversionは`task version:sync`で同期する。

commandは`devbox shell`内の`task --list-all`を正本とし、対象unit/integration/e2eを実行する。
