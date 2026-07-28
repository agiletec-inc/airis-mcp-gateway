# Local deployment

このserviceはlocal machineでだけ動かす。public internetへ公開しない。

## Preconditions

- Dockerまたは互換container runtime
- localhost port 9400
- `config/mcp-config.template.json`から作られたlocal registry

## Start

```bash
devbox shell
task dev:up
curl -fsS http://localhost:9400/health
```

利用者向けinstallはroot `install.sh`を使う。production reverse proxy、TLS、public hostnameは設けない。

## Verification

health、process server一覧、Context7の代表lookupを順に確認する。起動成功だけでtool call成功を主張しない。
logへcredential、request payloadの秘密値、provider sessionを出さない。

## Update and rollback

published imageの更新はreview済みreleaseを使う。local source変更は`task dev:up`でrebuildする。失敗時は以前の
image/versionへ戻し、local registryを削除して初期化し直す前に差分を保全する。
