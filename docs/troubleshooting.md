# Troubleshooting

1. `curl -fsS http://localhost:9400/health`でendpointを確認する。
2. `task docker:logs`でAPI/process起動errorを確認する。secret値を共有しない。
3. local `mcp-config.json`と`config/mcp-config.template.json`の責務を混同していないか確認する。
4. source変更後ならcontainerをrebuildする。
5. Context7 processのcommand、package取得、timeoutを個別に確認する。

Stream bridgeで`content already streamed`が出る場合、最初のSSE eventを`async for ... break`で読んでstreamを
closeしていないか確認する。同じiteratorを`__anext__()`からreader taskへ渡す。

circuit openは繰返しcrashの結果であり、thresholdを無効化しない。直前のprocess errorを修正してから再起動する。
