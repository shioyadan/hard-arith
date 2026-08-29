# FP32 Reciprocal

IEEE 754 binary32のbit patternを入力し、逆数`recip(x)=1/x`を返す、
合成可能なSystemVerilog組合せ回路です。32区間の区分一次初期値と
Newton反復1回を使い、結果が正規化数となる範囲でfaithful roundingを行います。
第1段階の実装ではsubnormal入出力をFTZとして扱います。

- トップモジュール: `FP32Recip`
- インターフェース: clockなしの32-bit入出力
- subnormal入力: signed zeroとして扱う
- subnormal出力: signed zeroへflush
- 精度: normal結果では厳密値を挟む二つのbinary32値のどちらか
- 単調性: 正負それぞれの非NaN領域で単調非増加

## ファイル構成

```text
fp32_recip/
├── fp32_recip.sv
├── README.md
├── Makefile
├── test/
│   ├── exhaustive.cpp
│   ├── monotonic.cpp
│   ├── reference.c
│   └── tb_fp32_recip.sv
└── tools/
    └── gen_constants.py
```

`fp32_recip.sv`だけが合成対象です。`test/`はquick test、全仮数検査、単調性検査、
`tools/`は二つの係数表の再生成・転記ミス検査に使います。

## インターフェース

```systemverilog
module FP32Recip (
    input  wire [31:0] x,
    output wire [31:0] result
);
```

`x`と`result`はIEEE 754 binary32のbit patternです。clock、reset、valid、ready、
例外flag、NaN payload保持、動的な丸めモード入力はありません。

```systemverilog
FP32Recip u_recip (
    .x(x),
    .result(result)
);
```

## 数値仕様

normal結果でのfaithful roundingは、無限精度の`1/x`を挟む直下・直上の
binary32値のどちらかを返すことを意味します。常にround-to-nearest-evenの結果を返す
correct roundingではありません。

| 入力または条件 | 出力 |
|---|---|
| NaN | canonical quiet NaN `0x7fc00000` |
| `+Inf` / `-Inf` | `+0` / `-0` |
| `+0` / `-0` | `+Inf` / `-Inf` |
| 正負のsubnormal入力 | signed zeroとして扱い、`+Inf` / `-Inf` |
| normal入力かつ厳密な結果がnormal | faithful roundingしたnormal |
| normal入力かつ厳密な結果がsubnormal | `+0` / `-0`へflush |
| 2のべき乗のnormal入力 | 厳密な2のべき乗 |

このFTZ仕様では、全binary32入力に対する数学的なfaithful roundingを主張しません。
faithfulの適用範囲は厳密な結果がnormalになる入力です。subnormal入力とsubnormal結果は、
上表のFTZ参照値へ一致することを検査します。

非NaN入力を次の二領域へ分け、それぞれ入力が数値順に増えると出力が単調非増加となります。

- 負領域: `-Inf`から`-0`
- 正領域: `+0`から`+Inf`

零点には極があるため、負領域と正領域をまたぐ一つの単調関数とは定義しません。
NaN以外では`recip(-x)=-recip(x)`となり、zeroとInfの符号も保存します。

## 必要なツール

- Verilator 5.x
- C++20とOpenMPを扱えるGCCまたはClang
- GNU Make
- Python 3

Verilator 5.020、GCC 13.3.0で動作を確認しています。

## テスト

リポジトリ直下から次を実行します。

```sh
make lint-fp32_recip
make test-fp32_recip
make exhaustive-fp32_recip EXHAUSTIVE_THREADS=22
make monotonic-fp32_recip
make constants-check-fp32_recip
```

`fp32_recip/`内では、それぞれ`make lint`、`make test`、`make exhaustive`、
`make monotonic`、`make constants-check`です。

`make test`は特殊値、FTZ境界、32区間の左端・中央・右端、固定seedの20万乱数入力、
20万点の単調性標本、符号対称性を検査します。参照値とfaithful上下限は、
binary32仮数に対する`2^47/significand`の厳密整数除算から生成します。

`make exhaustive`は、近似本体へ入る全8,388,607個の非零仮数を正負のRTLへ与えます。
指数は近似本体の計算へ影響せず、出力指数へ定数減算されるだけなので、全仮数検査は
指数127を代表として行います。別に全256指数fieldと代表9仮数、正負の4,608入力を検査し、
特殊値、FTZ、指数再構成を確認します。これは全`2^32` bit patternの列挙ではありません。

`make monotonic`は正負それぞれについて全8,388,607隣接仮数を比較し、さらに
正負の全指数境界512組を比較します。近似本体が指数から独立していることを利用した
縮約検査であり、全4,278,190,081非NaN隣接組を個別にシミュレーションする検査ではありません。

## 検証済み精度

全非零仮数を使った独立整数モデルでは次を確認しています。Verilated RTLの全仮数検査でも
同じ値となることを照合します。

| 指標 | 結果 |
|---|---:|
| 検査した非零仮数 | 8,388,607 |
| 正負を含むRTL評価数 | 16,781,822 |
| RNE一致 | 6,917,923 |
| RNEとは異なるfaithful値 | 1,470,684 |
| faithful違反 | 0 |
| 符号対称性違反 | 0 |
| RNEからの最大step数 | 1 |
| 正負の隣接仮数比較 | 16,777,214 |
| 指数境界比較 | 512 |
| 単調性違反 | 0 |

厳密有理数に対する観測最大絶対誤差は`0.926011890637 ULP`です。
RNE一致率は約`82.468078%`でした。これらは全仮数の整数モデル検査値であり、
形式証明や全`2^32` bit patternの個別列挙ではありません。RTL検査では特殊値、FTZ、
指数再構成、符号対称性も別に照合します。

## アルゴリズム

### 基本的な考え方

normalなbinary32入力は、符号`s`、`[1,2)`の仮数`m`、非バイアス指数`E`を使って
次のように表せます。

```text
x   = (-1)^s * m * 2^E
1/x = (-1)^s * (1/m) * 2^(-E)
```

この式から、逆数計算を三つに分けられます。

- 符号`(-1)^s`は入力からそのまま引き継ぐ
- 2の累乗部分`2^E`は指数`E`の符号を反転して`2^(-E)`にする
- 残った仮数部分についてだけ`1/m`を計算する

つまり、大きさが広い範囲へ変化する`x`全体の逆数を近似する必要はありません。
指数の処理を先に分離すると、近似対象は常に`1 <= m < 2`の仮数だけになります。
この`1/m`が、回路で実際に逆数近似を行う部分です。

#### `1/m`の計算全体

`1/m`は一般の除算器でも計算できますが、そのまま組合せ回路へ展開すると大きな
仮数除算回路が必要になります。本実装では、次の順に近似します。

1. `m`が`[1,2)`のどの区間に入るかを上位5 bitで選び、範囲を32分割する。
2. 区間ごとの切片と傾きを使う一次補間から、初期値`y0 ~= 1/m`を作る。
3. Newton反復`y1 = y0*(2-m*y0)`を1回行い、初期誤差を二乗する。
4. `y1`をbinary32仮数`2/m`へ正規化し、反転した指数と組み合わせる。

以下では、この全体構造を構成する各段について、採用理由と実際の計算を順に説明します。

#### 区分線形初期値が有効な理由

逆数は基準値`c`の近くで次のように展開できます。

```text
z = c+r
1/z = 1/c-r/c^2+r^2/c^3-r^3/c^4+...
```

定数項と一次項だけを使うと、最初に省略される項は`r^2/c^3`です。`c`が`[1,2)`に
ある場合、一次近似の誤差は残差`r`の二乗、すなわち`O(r^2)`になります。

一つの基準値で`[1,2)`全体を扱うと`r`が大きいため、一次式だけでは十分な精度を
得られません。そこで`[1,2)`を幅`h=1/32`の区間へ分け、区間`i`の左端を`a_i`、
区間内の位置を`r_i`とします。

```text
i   = floor(32*(m-1))
a_i = 1+i/32
m   = a_i+r_i,  0 <= r_i < 1/32
```

各区間では`|r_i|<h`なので、一次近似の誤差は`O(h^2)`へ縮小します。これが区分線形
近似を使う理由です。ここでの級数展開はその理由を示すものであり、RTLがTaylorの接線を
そのまま計算するわけではありません。実際には区間両端を結ぶ弦を誤差中心化した直線を
使います。その相対誤差も`O(h^2)`となることを後段で具体的に導出します。

各直線は、区間左端の切片`A[i]`と、区間内で減少する量`Delta[i]`で表します。
仮数の上位5 bitがテーブルindex、続く10 bitが区間内位置となり、二つの小さな
テーブルと一つの補間乗算から初期値`y0 ~= 1/m`を作ります。

#### Newton反復で誤差を二乗する

一次近似を最終結果にせず、`F(y)=1/y-m=0`を解くNewton反復の初期値にします。

```text
F'(y) = -1/y^2

y_next = y-F(y)/F'(y)
       = y*(2-m*y)
```

初期相対誤差を

```text
e0 = m*y0-1
```

とすると、1回の反復と反復後の誤差は次のようになります。

```text
y1 = y0*(2-m*y0)
   = y0-y0*e0

m*y1-1 = -e0^2
y1     = (1-e0^2)/m
```

初期誤差`e0`が約`2^-k`なら、理想的な反復後の誤差は約`2^-2k`です。この誤差二乗により、
初期値自体をbinary32精度まで高精度化せず、32区間の小さな一次テーブルと1回の補正で
faithful roundingに必要な精度を得られます。

区分線形近似の初期誤差は`O(h^2)`なので、理想的なNewton反復後はその二乗の`O(h^4)`です。
区間分割とNewton反復は別の近似処理ですが、この`O(h^2) -> O(h^4)`の関係によって、
小さな一次テーブルを高精度な逆数へつなげています。

#### 零点付近のNewton残差

Newton残差`e0=m*y0-1`は、`y0=1/m`で零になります。零点付近では近い二数の上位bitが
相殺するため、差を作る前に積の下位bitを捨てると、残った丸め誤差が補正値へ直接入ります。

そこで、`m*y0`は積に必要な精度を保ったまま計算し、`1.0`との差をsigned modulo残差として
正確に取り出します。残差を得た後でのみ、Newton補正乗算に不要な下位bitを削ります。
これは、零点を持つ項の精度確保を残差生成の一箇所へ閉じ込めるための構成です。

#### 出力仮数と指数の正規化

RTLではhidden bitを含む24-bit整数`x_sig`から仮数`m`を得ます。

```text
m = x_sig * 2^-23,  1 <= m < 2
E = input_exponent-127
```

`m=1`、つまりfractionが零なら、入力は2のべき乗なので、仮数を近似せず指数だけを
反転して厳密な2のべき乗を返します。

`m>1`では`1/m`が`(0.5,1)`に入るため、binary32のnormal仮数`[1,2)`へ合わせるには
2倍して指数を1下げます。

```text
1/|x| = (2/m) * 2^(-E-1),  1 < 2/m < 2
```

入力のbiased exponentを`e_field`とすると、出力指数fieldは次の減算になります。

```text
fraction != 0 : output_exponent = 253-e_field
fraction == 0 : output_exponent = 254-e_field
```

実際の固定小数点回路では理想式をすべて全幅で保持せず、全8,388,607非零仮数を走査する
整数モデルで、テーブル量子化、補間精度、Newton補正幅、最終biasを同時に調整しています。
各信号のbit幅と小数点位置は後述の「固定小数点形式」、乗算器とテーブルの大きさは
「主な演算資源」にまとめます。

### 実装

#### 1. 32区間の誤差中心化一次初期値

仮数fractionの上位5 bitを区間番号`i`、続く上位10 bitを区間内残差`u10`とします。
区間内位置の下位8 bitは使いません。区間`i`の左端、右端、幅を

```text
a_i = 1 + i/32
b_i = a_i + 1/32
h   = 1/32
```

とします。`1/x`の両端を結ぶ弦`L_i(x)`と、その最大相対誤差`C_i`は次です。

```text
L_i(x) = (a_i + b_i - x) / (a_i*b_i)
x*L_i(x) - 1 = (x-a_i)*(b_i-x) / (a_i*b_i)
C_i = h^2 / (4*a_i*b_i)
```

弦は区間内で厳密値の上側だけに誤差を持ちます。`fp32_exp`のテーブル調整と同様に、
この一方向の誤差を残さず、弦を`2/(2+C_i)`倍して相対誤差を正負へ中心化します。

```text
E_i    = C_i / (2+C_i)
G_i(x) = (1-E_i)*L_i(x) = 2*L_i(x)/(2+C_i)
-E_i <= x*G_i(x)-1 <= E_i
```

連続minimax直線`G_i`を出発点として、切片を14-bit unsigned Q14へ量子化した後、
全仮数で初期誤差が小さくなる値を選びます。全切片と補間後の全seedでMSBは1なので、
RTLの切片表には下位13 bitだけを格納し、補間減算後にMSBを復元します。

`1/m`の傾きは`-1/m^2`なので、`m=1`側と`m=2`側では絶対値が約4倍変わります。
単一scaleでは傾きを7 bitへ収められないため、先頭13区間はunsigned Q12、残り19区間は
unsigned Q13として7-bit係数`Delta7`を使います。RTLの整数補間は次です。

```text
shift[i] = 8  (0 <= i <= 12)
           9  (13 <= i <= 31)
y0 = A[i] - floor(Delta7[i] * u10 / 2^shift[i])
```

前半のQ12係数と後半のQ13係数は、どちらもshift後にQ14の減算量になります。
論理的な格納量は32×13 bitの切片下位表と32×7 bitの傾き表の合計640 bitです。
合成器は二表とbank選択を一つのwide ROMや論理へまとめることができます。
上側だけに固定しない中心化初期値を使うため、後段の残差はsignedとして扱います。

#### 2. signed modulo残差

Newton残差は次の形で計算します。

```text
error = m*y0-1
```

`m*y0`は24×14 bitのunsigned Q37積です。中心化した初期値により`error`は正負を取り、
全非零仮数で`-25,149,443`から`+26,775,750`までのsigned 26 bitに収まります。
Q37の`1.0`は`2^37`であり、`2^37 mod 2^26 = 0`です。このため、38-bit積の下位26 bitを
二の補数のsigned値として解釈するだけで、`m*y0-1`を正確に得られます。

このmodulo計算は近い二数の差で消える上位bitを初めから作らない最適化です。差を取る前に
残差の下位bitを捨てる方式ではないため、零点付近の有効桁は失いません。

#### 3. 量子化したNewton補正と最終bias

Newton補正ではQ14 seedの下位1 bitを落とした13-bit Q13値を1 bit符号拡張し、
signed 14-bitの正値として使います。signed Q37 errorは下位11 bitを落とした
signed 15-bit Q26値とし、14×15 bitのsigned Q39積を作ります。積を12 bit右へ落とした
signed 16-bit Q27値が補正量です。

```text
y1_q27 = (y0_q14 << 13) - correction_q27 + bias
```

最終Q23仮数へ落とす際の`+0.5 ULP`に相当する`+4` Q27 LSBを加えます。
全非零仮数の整数解析で共通してfaithfulとなるbiasは`+4`だけです。

#### 4. 指数再構成とFTZ

fractionが非零なら結果のbiased exponentは`253-input_exponent`、fractionが零なら
`254-input_exponent`です。後者は`2/m=2`を指数側へ繰り上げるため1大きくなります。

normal入力からsubnormal結果が生じる範囲は次のとおりです。

- 入力指数fieldが254の全入力
- 入力指数fieldが253でfractionが非零の入力

これらは符号付きzeroへflushします。入力指数fieldが253でfractionが零の場合、
結果は最小normalなのでflushしません。

#### 幅の選定根拠

前節で導いたように、初期相対誤差`e=m*y0-1`は理想的なNewton反復後に`-e^2`となります。
したがって、区間`[a,b]`での理想的な最大相対誤差は`E^2`になります。
最も厳しい先頭区間について、これを正規化済みbinary32出力のULPへ換算すると次です。

| 区間数 | `h` | 理想Newton後の最大誤差 |
|---:|---:|---:|
| 16 | `1/16` | 約`3.54 ULP` |
| 32 | `1/32` | 約`0.235 ULP` |

16区間では、連続minimax初期値と厳密Newton演算を仮定しても、区間内の誤差幅が
faithfulで許される隣接2値間の1 ULPを超えます。最終biasや固定小数点量子化では救えないため、
16区間は採用できません。32区間では理想誤差が約0.235 ULPまで下がり、量子化、補間残差の
下位bit省略、Newton補正の幅削減を含めてもfaithfulへ収める余裕があります。

`fp32_exp`と同じく、各信号を独立に最大精度へせず、テーブル、補間、signed modulo残差、
Newton補正、最終biasを一つの整数モデルで同時に探索しました。採用した32区間Q14/Q27構成は、
全8,388,607非零仮数でfaithful違反0、単調性違反0、最大`0.926011890637 ULP`です。
最終biasは`+4`だけが安全です。64区間へ増やす代わりに誤差中心化と二bank scaleを用い、
切片・傾き表の実格納量を合計640 bitに抑えています。

#### 固定小数点形式

`Qn`は格納整数に`2^-n`を掛けた値を表す固定小数点表現という意味です。

| 信号・定数 | 幅 | 形式 | 役割 |
|---|---:|---|---|
| `x_sig` | 24 | unsigned Q23 | 入力normal仮数`m` |
| `A_low[i]` | 13 | unsigned Q14の下位bit | 共通MSBを省いた区間左端の切片 |
| `Delta7[i]` | 7 | unsigned Q12/Q13 | bankごとにscaleを変える区分一次補間の傾き |
| `residual` | 10 | unsigned整数 | 区間内位置の上位10 bit |
| `interpolation_product` | 17 | unsigned Q12/Q13 | `Delta7[i]*residual` |
| `interpolation` | 9 | unsigned Q14 | bankごとにshiftした切片減算量 |
| `reciprocal_seed` | 14 | unsigned Q14 | 区分一次初期値`y0` |
| `seed_product` | 38 | unsigned Q37 | `m*y0` |
| `error_excess` | 26 | signed Q37 | 積の下位26 bitで表す`m*y0-1` |
| `correction_seed` | 13 | unsigned Q13 | `y0`の下位1 bitを省いた補正乗算入力 |
| `correction_seed_signed` | 14 | signed Q13 | 正値の`correction_seed`を1 bit拡張した値 |
| `error_high` | 15 | signed Q26 | errorの下位11 bitを省いた補正乗算入力 |
| `correction_product` | 29 | signed Q39 | 量子化した`y0*(m*y0-1)` |
| `correction` | 16 | signed Q27 | Newton補正量 |
| `reciprocal_q27` | 28 | signed Q27 | Newton反復後の`1/m` |
| `reciprocal_sig` | 24 | unsigned Q23 | 正規化済み`2/m` |

#### 主な演算資源

| ブロック | 主な幅 | 役割 |
|---|---:|---|
| 切片表 | 32×13 bit | 共通MSBを省いた区間左端の`1/m` |
| 傾き表 | 32×7 bit＋1 bit bank選択 | Q12/Q13を切り替える区分一次補間の傾き |
| 補間乗算 | 7×10 bit | 区間内の一次補正 |
| seed積 | 24×14 bitの下位26 bit | signed modulo Newton残差の生成 |
| Newton補正乗算 | signed 14×15 bit | 量子化した`y0*(m*y0-1)` |
| Newton再構成 | signed 28 bit加減算 | Q14 seed、Q27補正、最終biasの合成 |
| 指数減算 | 8 bit×1 | 仮数zeroをcarry-inとして共有する指数再構成 |

## 定数と係数表の照合

`tools/gen_constants.py`はPythonの厳密整数演算で32区間のminimax基準値を作り、
11-bit bucketで係数を局所調整してから、RTLに格納した32個のQ14切片下位13 bit、
Q12/Q13二bankの7-bit傾き、Newton後のbiasと照合します。実際の補間と`--analyze`は
RTLと同じ10-bit residualを使います。

```sh
make constants-check
make constants
python3 tools/gen_constants.py --check fp32_recip.sv --analyze
```

`--analyze`は全8,388,607非零仮数を固定小数点整数モデルで検査し、faithful違反、
単調性違反、RNE一致数、Newton残差の最大値を表示します。

係数、区間数、固定小数点幅、積のbit抽出位置、Newton biasを変更した場合は、
quick testだけでなく`make exhaustive`と`make monotonic`を再実行してください。

## subnormal対応を追加する場合

現在の近似本体はnormal仮数だけを受け取ります。gradual underflowへ拡張する場合は、
近似表とNewton反復を再利用しつつ、少なくとも次を追加する必要があります。

- subnormal入力のleading-zero countと左正規化
- 正規化後の拡張指数
- subnormal出力用の右shift、guard、sticky、丸め
- normal/subnormal境界を含むfaithful性と単調性の再検証

subnormal出力packを追加すると最終丸めの誤差配分が変わるため、現在の係数とbiasを
無検証で流用して全binary32 faithfulを主張することはできません。

## 合成時の注意

合成トップは`FP32Recip`です。全体はclockなしの組合せ回路で、パイプラインレジスタは
含みません。

二つの32要素テーブルはSystemVerilogのunpacked定数配列で記述しています。合成器がこの構文を
直接扱えない場合は、同じ値を`function`と`case`で表すROMへ変換する必要があります。
変換時は定数照合とゲートテストで入出力がビット単位に一致することを確認してください。

## ライセンス

Copyright 2026 Ryota Shioya and Toru Koizumi

Apache License 2.0の下で公開します。詳細は[`../LICENSE`](../LICENSE)を参照してください。
