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
- 精度: 関数ごとにULPまたは絶対誤差を規定

## ファイル構成

```text
fp32_elementary/
├── fp32_elementary.sv
├── README.md
├── Makefile
├── test/
│   ├── exhaustive.cpp
│   ├── function_enables.cpp
│   ├── reference.c
│   ├── tb_function_enables.sv
│   ├── tb_fp32_elementary.sv
│   └── test_constants.py
├── tools/
│   └── gen_constants.py
└── experiments/
    └── kernel_opt/
```

`fp32_elementary.sv`だけが合成対象です。`test/`は関数ごとの数値精度、単調性、
縮約した全数検査、`tools/`は量子化済み係数tableの再生成と照合に使います。

## インターフェース

```systemverilog
module FP32Elementary #(
    parameter bit ENABLE_EXP2   = 1'b1,
    parameter bit ENABLE_RECIP  = 1'b1,
    parameter bit ENABLE_RSQRT  = 1'b1,
    parameter bit ENABLE_SQRT   = 1'b1,
    parameter bit ENABLE_LOG2   = 1'b1,
    parameter bit ENABLE_SINCOS = 1'b1
)(
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
ありません。未定義の`op`、複数bitが立った`op`、または無効にした関数の`op`には
canonical quiet NaN `0x7fc00000`を返します。

```systemverilog
FP32Elementary u_elementary (
    .x(x),
    .op(op),
    .result(result)
);
```

### 合成時の機能選択

六つの`ENABLE_*`パラメータは合成時に固定する設定です。既定値はすべて1で、
七機能を使えます。0にした関数の専用table、引数還元、結果選択は不要となり、
合成時の定数伝播で除去できます。sinpiとcospiは同じtableと演算経路を使うため、
`ENABLE_SINCOS`で一括して有効・無効を指定します。

例えば、`2^x`、逆数、逆平方根だけを残す場合は次のようにします。

```systemverilog
FP32Elementary #(
    .ENABLE_SQRT(1'b0),
    .ENABLE_LOG2(1'b0),
    .ENABLE_SINCOS(1'b0)
) u_elementary (
    .x(x), .op(op), .result(result)
);
```

`op`の幅と符号化は変わりません。有効な関数の計算結果、FTZ・特殊値・丸め・
誤差条件も全機能構成と同じです。無効な関数のbitを含む複数bit指定も不正な`op`であり、
有効なbitだけを取り出して演算することはありません。全パラメータを0にした構成も
許可し、すべての入力にcanonical quiet NaNを返します。

共通datapathは残した関数間で共有するため、面積は機能数に比例して減るわけではありません。
この例の指数関数は自然指数`exp`ではなく`exp2`です。

## 数値仕様

入力subnormalは符号付きzeroとして扱い、結果がsubnormalになる場合も
符号付きzeroへflushします。全演算でNaN入力はcanonical quiet NaN
`0x7fc00000`にします。

| 演算 | 有限値の精度条件 |
|---|---|
| `2^x` | RNE参照値から最大1 ULP |
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

精度条件とは別に単調性も検査します。sqrt／rsqrtは正の定義域、sinpi／cospiは
増減方向が一定の区間で、隣接入力に対して出力が逆行しないことを合否に含めます。
周期関数を全実数上で単調とする意味ではありません。

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
make test-configs-fp32_elementary
make exhaustive-fp32_elementary EXHAUSTIVE_THREADS=22
make constants-check-fp32_elementary
```

`fp32_elementary/`内では、それぞれ`make lint`、`make test`、`make exhaustive`、
`make constants-check`です。

`make test`は短時間の回帰検査です。関数ごとに特殊値と境界値24入力、
固定seed 200,000乱数入力をbinary128参照値で検査し、単調区間も200,000点で走査します。

`make test-configs-fp32_elementary`（unit内では`make test-configs`）は六つの設定の
全64組合せを検査します。全無効・各機能単独・全機能を含め、有効な関数は既定構成と
bit一致、無効な関数と不正な`op`はcanonical quiet NaNになることを確認します。
入力は全128通りの`op`と特殊値、関数別の固定seed 20,000乱数、全指数・正負・
128区分の境界前後、exp2とsin/cosの還元境界で、1,625,816入力・op組を各設定へ与えます。
計104,052,224比較で不一致0を確認しました。設定は全数ですが、入力空間全体の
等価性証明ではありません。独立高精度参照による精度検査は`make test`と`make exhaustive`です。

標本数は次のように変更できます。

```sh
make test-fp32_elementary RANDOM_CYCLES=1000000 MONOTONIC_SAMPLES=1000000
```

`make exhaustive`は、引数還元で縮約できる全仮数または全位相と、全指数・table境界を
検査した後、exp2の全`2^32` bit patternを列挙します。途中で違反を検出しても
全走査を完了し、最後に失敗を返します。網羅範囲と参照値の作り方は次節に示します。

2026-09-18の18-bit残差・両段加算統合後の再検証では、各関数の精度違反・隣接単調性違反とも0で、縮約検査と
exp2全入力検査の両方が`pass=1`です。sinpi/cospiの単調性も合否に含めています。

短い確認には`make exhaustive-reduced`、exp2の近似本体だけの確認には
`make exhaustive-active`を使用できます。22 threadでの直近の確認では、exp2の全入力走査は
約45秒でした。buildと通常testを含めても約1分で完了します。

## 検証済み精度

縮約全数検査の結果は次のとおりです。reciprocal、sqrt、rsqrtの参照値は整数演算で
厳密に丸めを決定し、log2と全指数境界はbinary128、sinpiとcospiの還元位相は
binary32判定に対して十分広い`long double`で検査しました。exp2は高速な
binary64参照値を使い、境界、丸め中点付近の459,802入力をbinary128で再判定しました。

| 演算 | 網羅した主領域 | 精度違反 | 観測最大 | 隣接単調性違反 |
|---|---:|---:|---:|---:|
| `1/x` | 正負を含む16,777,216入力 | 0 | 1 ULP | 0 |
| `1/sqrt(x)` | 指数偶奇と全仮数16,777,216入力 | 0 | 1 ULP | 0 |
| `sqrt(x)` | 指数偶奇と全仮数16,777,216入力 | 0 | 1 ULP | 0 |
| `log2(x)` | `0.5 <= x < 2`の全16,777,216入力 | 0 | `1.823170 * 2^-23` | 0 |
| `sin(pi*x)` | 全4,194,305 Q23還元位相 | 0 | `3.242481 * 2^-23` | 0 |
| `cos(pi*x)` | 全4,194,305 Q23還元位相 | 0 | `3.242481 * 2^-23` | 0 |
| `2^x` | 全`2^32`入力 | 0 | 1 ULP | 0 |

全指数fieldとtable境界を組み合わせた各328,192入力では、七関数とも精度違反0でした。
また、不正な`op` 1,936組合せがすべてcanonical quiet NaNを返すことを確認しました。

`2^x`は有限4,278,190,080入力で最大1 ULP、精度違反0、隣接単調性違反0でした。
特殊値16,777,216入力の不一致も0でした。sinpiとcospiの還元位相検査では、
位相をQ23へ丸める前の半LSB範囲も含めて絶対誤差を評価しています。

以上はRTL入力または引数還元後の離散空間を列挙した検査であり、形式証明や
精度保証付きの計算機援用証明ではありません。exp2以外は全`2^32` bit patternを直接列挙せず、
近似本体を共有する指数を縮約し、全指数のtable境界検査を組み合わせています。

## アルゴリズム

### 基本的な考え方

七つの関数を個別に実装すると、各回路がtable、乗算器、丸め回路を持つため、
機能数にほぼ比例して面積が増えます。一方、各関数の入力を小さな区間へ移し、
その区間の基準点との差`d`を使えば、どの関数も次の同じ二次Horner形で
近似できます。

```text
P(d) = C0+d*(C1+d*C2)
```

入力が広いままでは高次項が必要ですが、`d`を十分狭い区間へ縮小すると、
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
| `sin(pi*x)` | 周期2の位相を`[0, 0.5]`へ折り返し、64区間の右端との差を使う | 64行 |
| `cos(pi*x)` | 位相へ0.5を加え、sinと同じ引数還元とtableを使う | sinと共有 |

`2^x`では還元直後に`|d| <= 1/128`です。Q24のままsigned 18 bitへ収めるため、
整数表現の正端点131,072だけを131,071へ制限します。小数部の精度を1 bit落とすのではなく、
正端点でのみ`2^-24`の差を許し、係数生成ではその端点の量子化cellも含めて誤差を調整します。
sin/cosでは折り返し後の各区間で
`-1/128 <= d < 0`です。他の関数は区間中央を基準にします。
sqrtと逆平方根は、指数の偶奇をtable addressの上位bitへ加え、
後で`2^E`由来のscaleを出力指数へ移します。

#### 2. 共通二次datapath

関数と区間から選んだ一組の係数を、次の順に評価します。

```text
inner = round_Q18(C1+d*C2)
value = round_Q27(C0+d*inner)  // exp2
value = round_Q25(C0+d*inner)  // その他。最後にQ27へ揃える
```

`d^2`を別途生成せずHorner形で計算するため、可変乗算は18 x 13 bitと
18 x 21 bitの二回です。係数は関数ごとに必要な精度だけを格納し、左shiftで
共通のQ27/Q17/Q9へ揃えてから共有datapathへ渡します。reciprocal、sqrt、rsqrtは
Q25/Q17/Q8、`log2`はQ25/Q16/Q7、`2^x`はQ27/Q17/Q9、sin/cosは
Q24/Q15/Q5の`C0/C1/C2`を使います。Horner中間値は全関数でQ18に保ちます。

各段では係数・積・丸めbiasを同じ小数点へ揃え、一つの積和式にまとめてから
必要なbitを切り出します。内側は36-bit Q33、外側は44-bit Q42で保持します。
途中丸めは半LSBの加算と算術右shiftで、tieは正方向です。これは最後のpackerのRNEとは別です。
`C1`はQ18格子、非exp2の`C0`はQ25格子に厳密に載るため、係数を丸め前に加えても
従来の`C+round(積)`と同じ結果です。二段の途中丸めを一回に減らす変更ではありません。

内側の積を粗く丸めると、連続多項式が単調でも段差による逆行が起こり得ます。
sqrt／rsqrtでは、既に`2^x`で使うQ18精度を共有し、全残差で最終出力の単調性を
確認します。中間丸めの関数別切り替えは不要となり、乗算器の幅も増やしません。

sin/cosは極値付近で傾きが0に近いため、Q18化だけでは足りません。そこで右端を
基準にし、`d <= 0`、`C1 >= 0`、`C2 <= 0`となる係数を選びます。
`t=-d`とすると、近似値は`C0-t*(C1+round(t*(-C2)))`です。非負の`t`を増やすと
引かれる積も増えるため、途中丸めを含めて区間内の増減方向がそろいます。
区間境界と零点・極値のbypassとの接続は、別途検査します。

最後に関数ごとの指数scaleと符号を戻し、共通Q27 packerがleading bitの位置から
指数と仮数を作ります。`2^scale`の乗算は整数乗算器ではなく出力指数の加減算で実現し、
overflowは`Inf`、underflowはflush-to-zeroで処理します。

#### 3. 係数の生成と圧縮

各区間の三点Chebyshev補間を係数探索の初期値にします。その後、`C1`と`C2`を
量子化後の整数格子上で探索し、各組合せに対して最大正誤差と最大負誤差を
均衡させる`C0`を選びます。実数係数を個別に丸めるのではなく、量子化後の
Horner演算と中間丸めを含む最大誤差が小さくなるように調整します。

`2^x`ではさらに、Q24残差の各量子化cellに対応する実引数区間を調べ、共通packerの
出力が区間全体でRNE参照値から1 ULP以内になるQ27の`C0`範囲を逆算します。その範囲内で
各区間内とtable境界の出力が単調になる`C0`列を選びます。まず対称なQ24格子で選別し、
次に正端点の制限を含めて、必要な行だけを最小変更量で再調整します。

sqrt／rsqrtも、Q18中間丸めと最終packerを含む全残差で精度・単調性を確認し、
隣接行が逆行しない`C0`列を動的計画法で選びます。sin/cosは右端基準へ係数を
変換してから再探索し、Q23位相cellの両端まで含めた絶対誤差を確認します。
極値に対応する最終行も`C0 < 1`に制限することで、tableの共通prefixを維持します。

係数は合計704行です。各bank内で全行に共通する上位bitを個別の行へ格納せず、
一つのprefixと行ごとのsuffixに分けます。共通bitを含む係数量は41,216 bit、
RTLのtableへ実際に格納するsuffixは33,600 bitです。

二のべき格子点、sin/cosの零点と極値は、多項式近似をbypassして厳密値を返します。

#### 固定小数点形式

`Qn`は格納整数に`2^-n`を掛けた値を表す固定小数点表現という意味です。

| 信号・係数 | 幅 | 形式 | 役割 |
|---|---:|---|---|
| `polynomial_delta_q24` | 18 | signed Q24 | 区間の基準点からの差`d` |
| `coefficient_c0_q27` | 29 | signed Q27 | 共通形式へ揃えた定数項 |
| `coefficient_c1_q17` | 20 | signed Q17 | 一次係数 |
| `coefficient_c2_q9` | 13 | signed Q9 | 共通形式へ揃えた二次係数 |
| `inner_accumulator_q33` | 36 | signed Q33 | `C1+d*C2`と丸めbias |
| `inner_q18` | 21 | signed Q18 | `C1+round(d*C2)` |
| `outer_accumulator_q42` | 44 | signed Q42 | `C0+d*inner`と丸めbias |
| `polynomial_q27` | 29 | signed Q27 | 二次近似結果 |
| `value_q27` | 36 | signed Q27 | `log2`の整数部を含むpacker入力 |

全table行と各区間で表現可能な全`d`に対し、中間補正、乗算結果、最終値が
宣言幅から溢れないことを係数生成時に検査します。

## 定数とテーブルの照合

`tools/gen_constants.py`は、各関数の区分二次係数を再生成し、量子化済みHorner演算の
探索結果、prefix/suffix分割、中間値の範囲をRTLと照合します。
`constants-check`では、境界候補の選択と極値での逆行防止に関する補助テストも実行します。

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

幅削減・積和統合の比較用生成器は[`experiments/kernel_opt/`](experiments/kernel_opt/README.md)に
分離しています。その`delta18-both`構成を公開トップへ採用していますが、通常の合成・定数生成・
test targetは実験directoryに依存しません。

## ライセンス

Copyright 2026 Ryota Shioya and Toru Koizumi

Apache License 2.0の下で公開します。詳細は[`../LICENSE`](../LICENSE)を参照してください。
