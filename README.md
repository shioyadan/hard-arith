# Hard Arith

浮動小数点数の数学演算を行う、合成可能なSystemVerilog実装を収録するリポジトリです。

- 各演算器に定めた数値仕様を満たしつつ、ASIC論理合成において同等用途の代表的な外部IPより
  コンパクトな回路面積を実現することを目標としています。
- ASICを主対象として設計・評価しており、FPGAにおける面積優位性は未評価です。

## 実装済みの演算

各公開トップは、clockなしのIEEE 754 binary32入出力を持つ組合せ回路です。

| ディレクトリ | 演算 | 精度保証 | subnormal | 単調性 |
|---|---|---|---|---|
| [`fp32_exp/`](fp32_exp/) | `exp(x)` | 全出力範囲でfaithful | gradual underflow出力に対応 | 非NaN領域で単調非減少 |
| [`fp32_exp2/`](fp32_exp2/) | `2^x` | 全出力範囲でfaithful | gradual underflow出力に対応 | 非NaN領域で単調非減少 |
| [`fp32_recip/`](fp32_recip/) | `1/x` | 結果がnormalとなる範囲でfaithful | 入出力ともFTZ | 負領域・正領域ごとに単調非増加 |
| [`fp32_log2/`](fp32_log2/) | `log2(x)` | 正の有限入力でfaithful | 正のsubnormal入力に対応 | 正の入力領域で単調非減少 |
| [`fp32_rsqrt/`](fp32_rsqrt/) | `1/sqrt(x)` | 正のnormal入力でfaithful | subnormal入力はFTZ | `+0`から`+Inf`まで単調非増加 |
| [`fp32_sqrt/`](fp32_sqrt/) | `sqrt(x)` | 正のnormal入力でfaithful | subnormal入力はFTZ | `+0`から`+Inf`まで単調非減少 |
| [`fp32_sincospi/`](fp32_sincospi/) | `sin(pi*x)` / `cos(pi*x)` | `FP32SinCosPi`はfaithful、`FP32SinCosPiLite`は絶対誤差`4*2^-23`以下 | faithful版は入出力とも対応、Lite版は絶対誤差のみを規定 | faithful版は各単調区間で保持、Lite版は仕様外 |
| [`fp32_elementary/`](fp32_elementary/) | `1/x`、`sqrt(x)`、`1/sqrt(x)`、`sin(pi*x)`、`cos(pi*x)`、`log2(x)`、`2^x`の選択出力 | 関数別のULP／絶対誤差条件 | 入出力ともFTZ | 非三角関数は各単調領域の標本検査で違反0 |

faithfulは、無限精度の値を挟む二つのbinary32値のどちらかを返すことを意味します。
単調非減少では入力を増やしたときに出力が減らず、単調非増加では出力が増えません。
丸めによって異なる入力が同じ出力になる場合があるため、等しい場合も許します。

各演算ディレクトリは、直下に合成対象のRTL、`test/`に検証コード、
`tools/`に実装固有の生成スクリプトを持ちます。NaN、Inf、符号付きzeroなどの特殊値、
丸めの適用範囲、アルゴリズムの詳細は各ディレクトリの`README.md`を参照してください。

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
make lint-fp32_exp2
make test-fp32_exp2
make exhaustive-active-fp32_exp2
make exhaustive-fp32_exp2
make monotonic-fp32_exp2
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
make lint-fp32_sqrt
make test-fp32_sqrt
make exhaustive-fp32_sqrt
make monotonic-fp32_sqrt
make lint-fp32_sincospi
make test-fp32_sincospi
make exhaustive-fp32_sincospi
make lint-fp32_elementary
make test-fp32_elementary
make constants-check-fp32_elementary
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
