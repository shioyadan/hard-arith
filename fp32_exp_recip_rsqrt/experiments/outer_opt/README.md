# 第2積と末段の構造比較

公開`FP32ExpRecipRsqrt`の係数・前処理・出力処理を固定し、第2積と末段だけを変更する実験です。
公開トップを置き換えません。数値契約は入出力FTZ、normal結果で最大1 RNE step、各定義域で単調です。
NaN、Inf、符号付きzero、負のrsqrt入力、overflow／underflow、無効opは公開版と同じです。
近似の許容誤差だけでなく、基準とのbit一致を要求します。

| variant | 差分 |
|---|---|
| baseline | 公開RTLとbyte一致 |
| centered | expのQ18中間値から1を外へ出し、第2積を18×19 bit＋線形項にする |
| rounding | 第2積の中間丸めを低位判定と最終加算へ移す |
| combined | 上記二案の組み合わせ |

`generate.py`は基準source hashを確認し、`build/outer-opt/`へ候補を生成します。
定数tableと変更区間外のbyte一致を検査し、再生成結果を`--check`でも照合できます。
`kernel-check`は同じ候補から係数選択～最終仮数のRTLを抽出し、全係数・残差格子を比較します。
expは64行×210,529残差、根系は3 bank×128行×65,536残差、計38,639,680組です。
expの組合せは実到達域の上位集合であり、形式証明ではありません。

```sh
make generate
make constants-check
make test VARIANT=centered
make test VARIANT=rounding
make test VARIANT=combined
make kernel-check THREADS=8
make equivalence THREADS=8
make equivalence-full THREADS=8
```

`equivalence`はfull topの基準と三候補を比較します。expのactive 536,870,912入力、
根系の代表指数・符号の全仮数、全指数の仮数端点、特殊値・無効op・固定seed乱数を対象とします。
候補の独立高精度通常testと、基準とのbit一致検査を区別します。
`equivalence-full`ではexpを全`2^32`入力へ拡張し、全体で4,346,923,520入力を比較します。

Copyright 2026 Ryota Shioya and Toru Koizumi

SPDX-License-Identifier: Apache-2.0
