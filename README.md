# Hard Arith

浮動小数点数の数学演算を行う、合成可能なSystemVerilog実装を収録するリポジトリです。

## 実装済みの演算

| ディレクトリ | 演算 | 形式 | 説明 |
|---|---|---|---|
| [`fp32_exp/`](fp32_exp/) | `exp(x)` | IEEE 754 binary32 | テーブルと二次近似を用いる組合せ回路 |
| [`fp32_recip/`](fp32_recip/) | `1/x` | IEEE 754 binary32 | 区分一次初期値とNewton反復を用いるFTZ組合せ回路 |
| [`fp32_log2/`](fp32_log2/) | `log2(x)` | IEEE 754 binary32 | mixed-precision三次近似を用いる組合せ回路 |
| [`fp32_rsqrt/`](fp32_rsqrt/) | `1/sqrt(x)` | IEEE 754 binary32 | 指数偶奇別の区分一次初期値とNewton反復を用いるFTZ組合せ回路 |

各演算ディレクトリは、直下に合成対象のRTL、`test/`に検証コード、
`tools/`に実装固有の生成スクリプトを持ちます。詳細仕様とアルゴリズムは各ディレクトリの
`README.md`を参照してください。

## 検証

全実装のlintとテストはリポジトリ直下から実行できます。

```sh
make lint
make test
make exhaustive
make constants-check
```

特定の実装だけを検証する場合は、実装名を付けたtargetを使います。

```sh
make lint-fp32_exp
make test-fp32_exp
make exhaustive-fp32_exp
make lint-fp32_recip
make test-fp32_recip
make exhaustive-fp32_recip
make monotonic-fp32_recip
make lint-fp32_log2
make test-fp32_log2
make exhaustive-fp32_log2
make lint-fp32_rsqrt
make test-fp32_rsqrt
make exhaustive-fp32_rsqrt
make monotonic-fp32_rsqrt
```

## Dev container

DockerとNode.js 20以上を用意し、[Dev Container CLI](https://github.com/devcontainers/cli)を
npmで導入します。

```sh
npm install -g @devcontainers/cli
```

リポジトリ直下で次を実行すると、Verilator 5.020の環境を起動して
テストします。

```sh
./launch.sh make test
```

引数なしの`./launch.sh`はコンテナ内のbashを開きます。
ホスト側で生成した`build/`が残っている場合は、初回だけテスト前に
`./launch.sh make clean`を実行してください。

## ライセンス

Copyright 2026 Ryota Shioya and Toru Koizumi

Apache License 2.0の下で公開します。詳細は[`LICENSE`](LICENSE)を参照してください。
