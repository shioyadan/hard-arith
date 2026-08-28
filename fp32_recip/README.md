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

## 検証期待値

全非零仮数を使った独立整数モデルでは次を確認しています。Verilated RTLの全仮数検査でも
同じ値となることを照合します。

| 指標 | 結果 |
|---|---:|
| 検査した非零仮数 | 8,388,607 |
| 正負を含むRTL評価数 | 16,781,822 |
| RNE一致 | 6,890,240 |
| RNEとは異なるfaithful値 | 1,498,367 |
| faithful違反 | 0 |
| 符号対称性違反 | 0 |
| RNEからの最大step数 | 1 |
| 正負の隣接仮数比較 | 16,777,214 |
| 指数境界比較 | 512 |
| 単調性違反 | 0 |

厳密有理数に対する観測最大絶対誤差は`0.881071431403 ULP`です。
RNE一致率は約`82.138071%`でした。これらは全仮数の整数モデル検査値であり、
形式証明や全`2^32` bit patternの個別列挙ではありません。RTL検査では特殊値、FTZ、
指数再構成、符号対称性も別に照合します。

## アルゴリズム

normal入力の絶対値を次のように分解します。

```text
|x| = m * 2^e
m = significand * 2^-23,  1 <= m < 2
```

`m=1`は2のべき乗なので指数だけを反転して厳密に処理します。`m>1`では、

```text
1/|x| = (2/m) * 2^(-e-1),  1 < 2/m < 2
```

となるため、近似本体では`1/m`を求め、最終bit抽出時に2倍した仮数へ変換します。

### 1. 32区間の誤差中心化一次初期値

仮数fractionの上位5 bitを区間番号`i`、続く上位11 bitを区間内残差`u11`とします。
区間内位置の下位7 bitは使いません。区間`i`の左端、右端、幅を

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
全仮数で初期誤差が小さくなる値を選びます。区間内のQ14切片差は下位1 bitを省いた
8-bit unsigned Q13の`Delta`として保持します。RTLの補間は次です。

```text
y0 = A[i] - floor(Delta[i] * u11 / 2^10)
```

`Q13 * 11-bit / 2^10`はQ14の減算量です。論理的には32×14 bitの切片表と
32×8 bitの傾き表ですが、合成器は一つのwide ROMや論理へまとめることができます。
上側だけに固定しない中心化初期値を使うため、後段の残差はsignedとして扱います。

### 2. signed modulo残差とNewton反復

Newton反復は次の形で計算します。

```text
error = m*y0 - 1
y1    = y0 - y0*error
```

`m*y0`は24×14 bitのunsigned Q37積です。中心化した初期値により`error`は正負を取り、
全非零仮数で`-25,149,443`から`+24,791,758`までのsigned 26 bitに収まります。
Q37の`1.0`は`2^37`であり、`2^37 mod 2^26 = 0`です。このため、38-bit積の下位26 bitを
二の補数のsigned値として解釈するだけで、`m*y0-1`を正確に得られます。

このmodulo計算は近い二数の差で消える上位bitを初めから作らない最適化です。差を取る前に
残差の下位bitを捨てる方式ではないため、零点付近の有効桁は失いません。

Newton補正ではQ14 seedの下位1 bitを落とした13-bit Q13値を1 bit符号拡張し、
signed 14-bitの正値として使います。signed Q37 errorは下位11 bitを落とした
signed 15-bit Q26値とし、14×15 bitのsigned Q39積を作ります。積を12 bit右へ落とした
signed 16-bit Q27値が補正量です。

```text
y1_q27 = (y0_q14 << 13) - correction_q27 + bias
```

最終Q23仮数へ落とす際の`+0.5 ULP`に相当する`+4` Q27 LSBを加えます。
全非零仮数の整数解析では`+3`と`+4`の両方がfaithfulであり、RNE一致数の多い`+4`を
採用しています。

### 3. 指数再構成とFTZ

fractionが非零なら結果のbiased exponentは`253-input_exponent`、fractionが零なら
`254-input_exponent`です。後者は`2/m=2`を指数側へ繰り上げるため1大きくなります。

normal入力からsubnormal結果が生じる範囲は次のとおりです。

- 入力指数fieldが254の全入力
- 入力指数fieldが253でfractionが非零の入力

これらは符号付きzeroへflushします。入力指数fieldが253でfractionが零の場合、
結果は最小normalなのでflushしません。

### 幅の選定根拠

連続minimax初期値の相対誤差を`e=m*y0-1`とすると、理想的なNewton反復後の値は

```text
y1 = (1-e^2)/m
```

です。したがって、区間`[a,b]`での理想的な最大相対誤差は`E^2`になります。
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
全8,388,607非零仮数でfaithful違反0、単調性違反0、最大`0.881071431403 ULP`です。
最終biasは`+3..+4`の範囲で安全です。64区間へ増やす代わりに誤差中心化を用いることで、
切片・傾き表を合計704 bitに抑えています。

### 固定小数点形式

`Qn`は格納整数に`2^-n`を掛けた値を表す固定小数点表現という意味です。

| 信号・定数 | 幅 | 形式 | 役割 |
|---|---:|---|---|
| `x_sig` | 24 | unsigned Q23 | 入力normal仮数`m` |
| `A[i]` | 14 | unsigned Q14 | 相対誤差を中心化した区間左端の切片 |
| `Delta[i]` | 8 | unsigned Q13 | Q14区間内切片差の下位1 bitを省いた値 |
| `residual` | 11 | unsigned整数 | 区間内位置の上位11 bit |
| `interpolation_product` | 19 | unsigned Q13 | `Delta[i]*residual` |
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

### 主な演算資源

| ブロック | 主な幅 | 役割 |
|---|---:|---|
| 切片表 | 32×14 bit | 誤差中心化した区間左端の`1/m` |
| 差分表 | 32×8 bit | 下位1 bitを省いた区分一次補間の傾き |
| 補間乗算 | 8×11 bit | 区間内の一次補正 |
| seed積 | 24×14 bitの下位26 bit | signed modulo Newton残差の生成 |
| Newton補正乗算 | signed 14×15 bit | 量子化した`y0*(m*y0-1)` |
| Newton再構成 | signed 28 bit加減算 | Q14 seed、Q27補正、最終biasの合成 |
| 指数減算 | 8 bit | 逆数の指数再構成 |

## 定数と係数表の照合

`tools/gen_constants.py`はPythonの厳密整数演算で32区間のminimax基準値を作り、
RTLに格納した32個のQ14切片、32個のQ13差分、Newton後のbiasと照合します。

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

Copyright 2026 Ryota Shioya

Apache License 2.0の下で公開します。詳細は[`../LICENSE`](../LICENSE)を参照してください。
