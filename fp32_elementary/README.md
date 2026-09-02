# FP32 Elementary

IEEE 754 binary32の`2^x`、`1/x`、`1/sqrt(x)`、`sqrt(x)`、`log2(x)`、
`sin(pi*x)`、`cos(pi*x)`をone-hotで選択し、一つの結果を返す、
合成可能なSystemVerilog組合せ回路です。関数ごとの引数還元と係数tableを、
二回の乗算で評価する二次Horner datapathとbinary32 packerへ接続し、
七機能で共有します。

- トップモジュール: `FP32Elementary`
- インターフェース: clockなしの32-bit入出力と7-bit one-hot `op`
- 近似datapath: 関数ごとの区分二次係数と二つの可変乗算器
- 非正規化数: 入出力ともflush-to-zero
- 丸め: 共通packerはround-to-nearest-even
- 精度: 関数ごとにULPまたは絶対誤差を規定する標本検証

## ファイル構成

```text
fp32_elementary/
├── fp32_elementary.sv
├── README.md
├── Makefile
├── test/
│   ├── reference.c
│   └── tb_fp32_elementary.sv
└── tools/
    └── gen_constants.py
```

`fp32_elementary.sv`だけが合成対象です。`test/`は関数ごとの数値精度と
単調性の標本検査、`tools/`は量子化済み係数tableの再生成と照合に使います。

## インターフェース

```systemverilog
module FP32Elementary(
    input  wire [31:0] x,
    input  wire [6:0]  op,
    output wire [31:0] result
);
```

`x`と`result`はIEEE 754 binary32のbit patternです。`op`はone-hotで、
次の順番は公開インターフェースの一部です。

| `op` | 演算 |
|---:|---|
| `7'b0000001` | `2^x` |
| `7'b0000010` | `1/x` |
| `7'b0000100` | `1/sqrt(x)` |
| `7'b0001000` | `sqrt(x)` |
| `7'b0010000` | `log2(x)` |
| `7'b0100000` | `sin(pi*x)` |
| `7'b1000000` | `cos(pi*x)` |

clock、reset、valid、ready、例外flag、NaN payload保持、動的な丸めモード入力は
ありません。未定義の`op`、または複数bitが立った`op`にはcanonical quiet NaNを
返します。

```systemverilog
FP32Elementary u_elementary (
    .x(x),
    .op(op),
    .result(result)
);
```

## 数値仕様

入力subnormalは符号付きzeroとして扱い、結果がsubnormalになる場合も
符号付きzeroへflushします。全演算でNaN入力はcanonical quiet NaN
`0x7fc00000`にします。

| 演算 | 有限値の精度条件 |
|---|---|
| `2^x` | RNE参照値から最大1 ULPを目標とする |
| `1/x` | RNE参照値から最大1 ULP |
| `1/sqrt(x)` | RNE参照値から最大1 ULP |
| `sqrt(x)` | RNE参照値から最大1 ULP |
| `log2(x)` | 最大2 ULP、または絶対誤差`4 * 2^-23`以下 |
| `sin(pi*x)` | 絶対誤差`4 * 2^-23`以下 |
| `cos(pi*x)` | 絶対誤差`4 * 2^-23`以下 |

`log2(x)`は`x=1`近傍で真値が0に近づくため、ULP誤差だけでは評価しません。
逆に絶対値の大きい出力ではbinary32の1 ULPが絶対誤差上限より大きくなるため、
二つの条件の和集合で判定します。`sin(pi*x)`と`cos(pi*x)`も零点近傍では
ULPが適切な指標にならないため、絶対誤差を使います。

特殊値と定義域外の主な出力は次のとおりです。

| 演算 | zeroまたは入力subnormal | `+Inf` | `-Inf`または負の定義域外 |
|---|---|---|---|
| `2^x` | `1.0` | `+Inf` | `-Inf`は`+0`、負の有限値は通常計算 |
| `1/x` | 符号付き`Inf` | `+0` | `-Inf`は`-0`、負の有限値は符号付き有限値 |
| `1/sqrt(x)` | 符号付き`Inf` | `+0` | `+Inf` |
| `sqrt(x)` | 符号付きzero | `+Inf` | `+Inf` |
| `log2(x)` | `-Inf` | `+Inf` | `+Inf` |
| `sin(pi*x)` | 符号付きzero | `+Inf` | `-Inf`は`+Inf`、負の有限値は周期関数として計算 |
| `cos(pi*x)` | `1.0` | `+Inf` | `-Inf`は`+Inf`、負の有限値は偶関数として計算 |

共通packerは近似後の固定小数点値をround-to-nearest-evenでbinary32へ
変換します。ただし、関数全体は有限語長の引数還元と二次近似を含むため、
常に真値のcorrect roundingを返す仕様ではありません。

## 必要なツール

- Verilator 5.x
- libquadmathを扱えるGCC
- GNU Make
- Python 3とNumPy（係数tableの生成・照合時のみ）

Dev containerにはこれらを導入済みです。

## テスト

hard-arithリポジトリ直下から次を実行します。

```sh
make lint-fp32_elementary
make test-fp32_elementary
make constants-check-fp32_elementary
```

`fp32_elementary/`内では、それぞれ`make lint`、`make test`、
`make constants-check`です。

`make test`は特殊値と境界値24入力、関数ごとの固定seed 200,000乱数入力を
binary128参照値で検査します。また、各関数が数学的に単調な区間を200,000点で
走査します。単調性は`2^x`、`1/x`、`1/sqrt(x)`、`sqrt(x)`、`log2(x)`の
合否条件に使い、絶対誤差だけを規定するsin/cosは観測値だけを記録します。

標本数は次のように変更できます。

```sh
make test-fp32_elementary RANDOM_CYCLES=1000000 MONOTONIC_SAMPLES=1000000
```

## 検証済み精度

特殊値と境界値を含む24入力に固定seed 200,000乱数入力を加えた、
各200,024入力の結果です。

| 演算 | RNE一致 | 観測最大 | 単調性標本違反 |
|---|---:|---:|---:|
| `2^x` | 166,954 | 1 ULP | 0 |
| `1/x` | 142,053 | 1 ULP | 0 |
| `1/sqrt(x)` | 141,980 | 1 ULP | 0 |
| `sqrt(x)` | 146,208 | 1 ULP | 0 |
| `log2(x)` | 195,882 | 363 ULP、絶対誤差条件との和集合に合格 | 0 |
| `sin(pi*x)` | 48,657 | `2.466577 * 2^-23` | 6（観測値） |
| `cos(pi*x)` | 91,322 | `2.460582 * 2^-23` | 6（観測値） |

`2^x`には、固定回帰標本とは別の入力`0x3f5a12b9`で、RNE参照値
`0x3fe70410`に対して`0x3fe70412`を返す2 ULPの既知点があります。
したがって、`2^x`の最大1 ULPは目標仕様であり、現在の実装で全入力に対して
成立するとは確認できていません。

現在の検証は標本検査であり、全`2^32` bit patternの列挙や形式証明ではありません。
単調性も、関数ごとに選んだ200,000標本のシミュレーション結果です。

## アルゴリズム

### 基本的な考え方

七つの関数を個別に実装すると、各回路がtable、乗算器、丸め回路を持つため、
機能数にほぼ比例して面積が増えます。一方、各関数の入力を小さな区間へ移し、
その区間の中心との差`d`を使えば、どの関数も次の同じ二次Horner形で
近似できます。

```text
P(d) = C0+d*(C1+d*C2)
```

入力が広いままでは高次項が必要ですが、`|d|`を半区間以下へ縮小すると、
`d^3`以降の影響が小さくなります。その残差は関数と区間ごとの係数へ織り込み、
共有する計算本体は二次に抑えます。

元の関数値を後で再構成できる形で、近似へ入る値を小さな範囲へ移す操作を
引数還元と呼びます。回路全体の流れは次のとおりです。

```text
x, op
  |
  +-- 特殊値と関数を分類
  |
  +-- 関数別の引数還元 --> table index, d, 指数scale, 符号
  |
  +-- 関数別係数table -------> C0, C1, C2
  |                                  |
  |                         P(d) = C0+d*(C1+d*C2)
  |                                  |
  +-- 厳密な格子点のbypassと関数別の再構成
                                     |
                              共通binary32 packer
                                     |
                                   result
```

関数ごとに必要なのは、引数還元、係数bank、最後の指数・符号の再構成です。
面積の大きい二つの乗算器とbinary32 packerは七機能で共有します。

### 実装

#### 1. 関数ごとの引数還元

normalなbinary32入力を次のように表します。

```text
x = (-1)^s*M*2^E,  1 <= M < 2
```

仮数を64または128区間に分ける場合、table indexは仮数fieldの上位6または
7 bitから直接取得できます。残りのbitを区間中央からのsigned Q23差分`d`にすると、
64分割で`|d| < 2^-7`、128分割で`|d| < 2^-8`になります。

| 演算 | 分解と近似範囲 | 係数table |
|---|---|---:|
| `2^x` | `n=round(64*x)`、`n=64*q+j`、`d=x-n/64`とし、`2^(j/64+d)`を近似する。`2^q`は出力指数で表す | 64行 |
| `1/x` | `1/x=(-1)^s*2^(-E)*(1/M)`とし、`1/M`を128区間で近似する | 128行 |
| `1/sqrt(x)` | `E`の偶奇により`1/sqrt(M)`または`1/sqrt(2*M)`を128区間で近似する | 2 x 128行 |
| `sqrt(x)` | `E`の偶奇により`sqrt(M)`または`sqrt(2*M)`を64区間で近似する | 2 x 64行 |
| `log2(x)` | `log2(x)=E+log2(M)`とし、`log2(M)`だけを64区間で近似する | 64行 |
| `sin(pi*x)` | 周期2の位相を`[0, 0.5]`へ折り返し、64区間で近似する | 64行 |
| `cos(pi*x)` | 位相へ0.5を加え、sinと同じ引数還元とtableを使う | sinと共有 |

`2^x`では`|d| <= 1/128`、sin/cosでは折り返し後の各区間で
`|d| < 1/256`です。sqrtと逆平方根は、指数の偶奇をtable addressの上位bitへ加え、
後で`2^E`由来のscaleを出力指数へ移します。

#### 2. 共通二次datapath

関数と区間から選んだ一組の係数を、次の順に評価します。

```text
inner = C1+round(d*C2)
value = C0+round(d*inner)
```

`d^2`を別途生成せずHorner形で計算するため、可変乗算は18 x 13 bitと
18 x 20 bitの二回です。`C1`は全関数でsigned Q17 20 bitです。
`C0`と`C2`は、精度に必要な`2^x`だけをsigned Q26 28 bitとsigned Q9 13 bit、
他の関数をsigned Q25 27 bitとsigned Q8 12 bitで格納し、計算前に共通Q26/Q9へ揃えます。

最後に関数ごとの指数scaleと符号を戻し、共通Q26 packerがleading bitの位置から
指数と仮数を作ります。`2^scale`の乗算は整数乗算器ではなく出力指数の加減算で実現し、
overflowは`Inf`、underflowはflush-to-zeroで処理します。

#### 3. 係数の生成と圧縮

各区間の三点Chebyshev補間を係数探索の初期値にします。その後、`C1`と`C2`を
量子化後の整数格子上で探索し、各組合せに対して最大正誤差と最大負誤差を
均衡させる`C0`を選びます。実数係数を個別に丸めるのではなく、量子化後の
Horner演算と中間丸めを含む最大誤差が小さくなるように調整します。

係数は合計704行です。各bank内で全行に共通する上位bitを個別の行へ格納せず、
一つのprefixと行ごとのsuffixに分けます。共通bitを含む係数量は41,664 bit、
RTLのtableへ実際に格納するsuffixは34,048 bitです。

二のべき格子点、sin/cosの零点と極値は、多項式近似をbypassして厳密値を返します。

#### 固定小数点形式

`Qn`は格納整数に`2^-n`を掛けた値を表す固定小数点表現という意味です。

| 信号・係数 | 幅 | 形式 | 役割 |
|---|---:|---|---|
| `polynomial_delta_q23` | 18 | signed Q23 | 区間中央からの差`d` |
| `coefficient_c0_q26` | 28 | signed Q26 | 共通形式へ揃えた定数項 |
| `coefficient_c1_q17` | 20 | signed Q17 | 一次係数 |
| `coefficient_c2_q9` | 13 | signed Q9 | 共通形式へ揃えた二次係数 |
| `inner_product_q32` | 31 | signed Q32 | `d*C2` |
| `inner_q17` | 20 | signed Q17 | `C1+round(d*C2)` |
| `outer_product_q40` | 38 | signed Q40 | `d*inner` |
| `polynomial_q26` | 28 | signed Q26 | 二次近似結果 |
| `value_q26` | 35 | signed Q26 | `log2`の整数部を含むpacker入力 |

全table行と各区間で表現可能な全`d`に対し、中間補正、乗算結果、最終値が
宣言幅から溢れないことを係数生成時に検査します。

#### 主な演算資源

| ブロック | 主な幅または規模 | 役割 |
|---|---:|---|
| 引数還元 | 仮数上位6/7 bit、指数偶奇、周期位相 | table index、`d`、scale、符号を作る |
| 係数table | 704行、suffix 34,048 bit | 関数と区間に対応する`C0/C1/C2`を保持する |
| 内側乗算 | signed 18 x 13 bit | `d*C2`を作る |
| 外側乗算 | signed 18 x 20 bit | `d*(C1+d*C2)`を作る |
| 厳密値bypass | 格子点判定と選択回路 | 二のべき、零点、極値を厳密に返す |
| 共通packer | 35-bit leading-bit検出とshift | 指数再構成、RNE、overflow、FTZ underflow |

## 定数とテーブルの照合

`tools/gen_constants.py`は、各関数の区分二次係数を再生成し、量子化済みHorner演算の
探索結果、prefix/suffix分割、中間値の範囲をRTLと照合します。

```sh
make constants-check
make constants
```

`make constants-check`はRTLを変更せず一致を検査します。`make constants`は
`BEGIN GENERATED ELEMENTARY TABLES`と`END GENERATED ELEMENTARY TABLES`の間を再生成値で
書き換えます。書き換え後は差分を確認し、定数照合と数値テストを再実行してください。

係数、区間数、固定小数点位置、中間丸め、演算幅は相互に依存します。
一部だけを変更した場合も、全関数の回帰テストを必要とします。

## 合成時の注意

合成トップは`FP32Elementary`です。全体はclockなしの組合せ回路で、
パイプラインレジスタは含みません。

係数tableはSystemVerilogのunpacked定数配列で記述しています。合成器がこの構文を
直接扱えない場合は、同じ値を`case`で表すROMへ機械的に変換する必要があります。
変換時は全table値と入出力がビット単位で一致することを確認してください。

## ライセンス

Copyright 2026 Ryota Shioya and Toru Koizumi

Apache License 2.0の下で公開します。詳細は[`../LICENSE`](../LICENSE)を参照してください。
