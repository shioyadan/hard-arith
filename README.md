# Hard Arith

浮動小数点数の数学演算を行う、合成可能なSystemVerilog実装を収録するリポジトリです。

- 各演算器に定めた数値仕様を満たしつつ、ASIC論理合成でコンパクトな回路を実現することを
  目標としています。
- ASICを主対象として設計・評価しており、FPGAにおける面積優位性は未評価です。

## 実装済みの演算

各公開トップはclockなしの組合せ回路です。入出力形式はFP32（IEEE 754 binary32）、
またはFP16（binary16）／BF16です。

| ディレクトリ | 演算 | 精度保証 | subnormal | 単調性 |
|---|---|---|---|---|
| [`fp32_exp/`](fp32_exp/) | `exp(x)` | 全出力範囲でfaithful | gradual underflow出力に対応 | 非NaN領域で単調非減少 |
| [`fp32_exp2/`](fp32_exp2/) | `2^x` | 全出力範囲でfaithful | gradual underflow出力に対応 | 非NaN領域で単調非減少 |
| [`fp32_recip/`](fp32_recip/) | `1/x` | 結果がnormalとなる範囲でfaithful | 入出力ともFTZ | 負領域・正領域ごとに単調非増加 |
| [`fp32_rsqrt/`](fp32_rsqrt/) | `1/sqrt(x)` | 正のnormal入力でfaithful | subnormal入力はFTZ | `+0`から`+Inf`まで単調非増加 |
| [`fp32_elementary/`](fp32_elementary/) | `1/x`、`sqrt(x)`、`1/sqrt(x)`、`sin(pi*x)`、`cos(pi*x)`、`log2(x)`、`2^x`の選択出力 | 関数別のULP／絶対誤差条件 | 入出力ともFTZ | exp2全入力と他関数の縮約全数で逆行0。sin/cosは増減方向が一定の区間で検査 |
| [`fp32_exp_recip_rsqrt/`](fp32_exp_recip_rsqrt/) | `exp(x)`、`1/x`、`1/sqrt(x)`の選択出力 | normal結果でRNE参照値から最大1 ULP | 入出力ともFTZ | 各演算の定義域で保持 |
| [`fp16_bf16_exp_recip_rsqrt/`](fp16_bf16_exp_recip_rsqrt/) | FP16／BF16の`exp(x)`、`1/x`、`1/sqrt(x)`の選択出力 | 有限非zero結果でRNE参照値から最大1 step | 入出力とも対応。parameterでFTZも選択可能 | 各演算の定義域で保持 |

faithfulは、無限精度の値を挟む二つのbinary32値のどちらかを返すことを意味します。
単調非減少では入力を増やしたときに出力が減らず、単調非増加では出力が増えません。
丸めによって異なる入力が同じ出力になる場合があるため、等しい場合も許します。

FP16／BF16版は形式の実行時切替に加えて、parameterによるFP16専用・BF16専用設定に対応します。
最大1 stepは、対象形式へ正しく丸めた参照値との表現可能な値の間隔であり、faithfulの保証ではありません。

FP32の各演算ディレクトリは、直下に合成対象のRTL、`test/`に検証コード、
`tools/`に実装固有の生成スクリプトを持ちます。FP16／BF16版は`rtl/`にRTL、
直下に検証コードと生成スクリプトを置きます。NaN、Inf、符号付きzeroなどの特殊値、
丸めの適用範囲、アルゴリズムの詳細は各ディレクトリの`README.md`を参照してください。

## 検証

全実装のlintとテストはリポジトリ直下から実行できます。

```sh
make lint
make test
make exhaustive
make constants-check
```

`FP32Elementary`は六つの`ENABLE_*`パラメータで合成時に必要な関数を選べます。
sinpi／cospiは一括制御し、既定値は全機能有効です。設定の全64組合せは
`make test-configs-fp32_elementary`で検査します。詳細は[unit README](fp32_elementary/README.md)を参照してください。
2026-09-17の`FP32Elementary`全数検査では、従来のsqrt／rsqrt／sin/cosの逆行を解消し、
精度・単調性とも合格しました。全入力走査と縮約検査の範囲はunit READMEを参照してください。

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
make lint-fp32_rsqrt
make test-fp32_rsqrt
make exhaustive-fp32_rsqrt
make monotonic-fp32_rsqrt
make lint-fp32_elementary
make test-fp32_elementary
make exhaustive-fp32_elementary EXHAUSTIVE_THREADS=22
make constants-check-fp32_elementary
make lint-fp32_exp_recip_rsqrt
make test-fp32_exp_recip_rsqrt
make exhaustive-active-fp32_exp_recip_rsqrt
make exhaustive-fp32_exp_recip_rsqrt
make monotonic-fp32_exp_recip_rsqrt
make constants-check-fp32_exp_recip_rsqrt
make lint-fp16_bf16_exp_recip_rsqrt
make test-fp16_bf16_exp_recip_rsqrt
make exhaustive-fp16_bf16_exp_recip_rsqrt
make monotonic-fp16_bf16_exp_recip_rsqrt
make constants-check-fp16_bf16_exp_recip_rsqrt
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
