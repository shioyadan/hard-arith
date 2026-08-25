# Hard Arith

浮動小数点数の数学演算を行う、合成可能なSystemVerilog実装を収録するリポジトリです。

## 実装済みの演算

| ディレクトリ | 演算 | 形式 | 説明 |
|---|---|---|---|
| [`fp32_exp/`](fp32_exp/) | `exp(x)` | IEEE 754 binary32 | テーブルと二次近似を用いる組合せ回路 |

各演算ディレクトリは、直下に合成対象のRTL、`test/`に検証コード、
`tools/`に実装固有の生成スクリプトを持ちます。詳細仕様とアルゴリズムは各ディレクトリの
`README.md`を参照してください。

## 検証

全実装のlintとテストはリポジトリ直下から実行できます。

```sh
make lint
make test
make constants-check
```

特定の実装だけを検証する場合は、実装名を付けたtargetを使います。

```sh
make lint-fp32_exp
make test-fp32_exp
```

## ライセンス

Copyright 2026 Ryota Shioya

Apache License 2.0の下で公開します。詳細は[`LICENSE`](LICENSE)を参照してください。
