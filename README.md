# AIRIS MCP Gateway

Context7を必要時だけ提供するlocal MCP endpoint。通常のfile、Git、GitHub、web検索、browser操作、external writeは
native toolまたは目的別skillが担当する。

## 起動

利用者はinstall script、開発者はsource checkoutを使う。

```bash
curl -fsSL https://raw.githubusercontent.com/agiletec-inc/airis-mcp-gateway/main/install.sh | bash
```

```bash
git clone https://github.com/agiletec-inc/airis-mcp-gateway.git
cd airis-mcp-gateway
devbox shell
task dev:up
curl -fsS http://localhost:9400/health
```

runtime registryはinstall時に`config/mcp-config.template.json`から作る。tracked `mcp-config.json.example`は空の
最小例であり、現在のserver一覧の正本ではない。local `mcp-config.json`はcommitしない。

## 利用境界

gatewayをglobal MCPとして常時登録しない。agentは`airis-mcp-gateway` skillから短命sessionを開き、exact current
library/framework documentationが必要な場合だけContext7を呼ぶ。provider credential directoryをcontainerへ
mountしない。

```text
通常作業 -> native tools / skills
公式library資料 -> airis-mcp-gateway skill -> Context7
```

設計境界は[`docs/architecture.md`](./docs/architecture.md)、運用は[`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md)、
障害切分けは[`docs/troubleshooting.md`](./docs/troubleshooting.md)を必要時に読む。version正本は`VERSION`。

## License

MIT
