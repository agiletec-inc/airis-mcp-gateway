# Contribution guide

このrepoはlocal MCP transport、Context7 process lifecycle、認証、rate limit、observabilityを所有する。
memory、browser、Git、file操作、agent orchestrationを追加しない。

```bash
devbox shell
task --list-all
task dev:up
task test:api
task test:e2e
```

`docker:up`はpublished image、`dev:up`はlocal sourceをbuildする。同じport 9400を使うため同時起動しない。
`apps/api/src/`変更後はimageをrebuildし、process restartだけで反映されたと仮定しない。

新しいserver追加はこのrepoの既定方針ではない。必要性、credential境界、常時context cost、native toolとの差を
設計reviewし、Context7専用という現行責務を変更する明示的な決定がある場合だけ行う。

PR前に対象testとfull CI相当を実行する。version変更はroot `VERSION`を先に更新し、`task version:sync`でpackage
manifestへ反映する。generated fileや文書へversion一覧を複製しない。
