# FP32 Exp

IEEE 754 binary32のbit patternを入力し、自然指数関数`exp(x)=e^x`を返す、
合成可能なSystemVerilog組合せ回路です。`ln(2)/64` による引数還元、
64エントリの調整済みQ26テーブル、二次近似を使い、正の非正規化数を含む
全出力範囲でfaithful roundingを行います。また、非NaN入力に対して単調非減少です。

- トップモジュール: `FP32Exp`
- インターフェース: clockなしの32-bit入出力
- 非正規化数出力: 対応
- 精度: 厳密値を挟む二つのbinary32値のどちらか
- 単調性: 非NaN入力に対して単調非減少

## ファイル構成

```text
fp32_exp/
├── fp32_exp.sv
├── README.md
├── Makefile
├── test/
│   ├── exhaustive.cpp
│   ├── monotonic.cpp
│   ├── reference.c
│   └── tb_fp32_exp.sv
└── tools/
    └── gen_constants.py
```

`fp32_exp.sv`だけが合成対象です。`test/`はquick test、全bit pattern検査、単調性検査、
`tools/`は定数とテーブルの再生成・転記ミス検査に使います。

## インターフェース

```systemverilog
module FP32Exp (
    input  wire [31:0] x,
    output wire [31:0] result
);
```

`x`と`result`はIEEE 754 binary32のbit patternです。clock、reset、valid、ready、
例外flag、NaN payload保持、動的な丸めモード入力はありません。

```systemverilog
FP32Exp u_exp (
    .x(x),
    .result(result)
);
```

## 数値仕様

faithful roundingは、無限精度の `exp(x)` を挟む直下・直上のbinary32値の
どちらかを返すことを意味します。常にround-to-nearestの結果を返す
correct roundingではありません。

| 入力または条件 | 出力 |
|---|---|
| NaN | canonical quiet NaN `0x7fc00000` |
| `+Inf` | `+Inf` |
| `-Inf` | `+0` |
| `+0`、`-0`、非正規化数 | `1.0` |
| 絶対値が2^-25未満 | `1.0` |
| 結果が正のオーバーフロー | `+Inf` |
| 結果が漸近的アンダーフロー領域 | 非正規化数を返す |
| 結果が完全にアンダーフロー | `+0` |

正規化数を出力する経路では切り捨てていますが、四捨五入の +0.5 相当を
事前にテーブルに織り込んでいるためであり、切り捨て丸めではありません。
非正規化数を出力する回路も右シフト後に切り捨てていますが、全体として
faithful rounding になるようにテーブルと係数を調整しています。
ただし、非正規化数を出力する経路は下向きに丸まる誤差傾向があります。

非NaNのbinary32入力を数値順に並べた全4,278,190,081隣接組について、
出力が単調非減少になることを確認しています。比較列には`-0`と`+0`も含み、
NaNは単調性の定義域から除外します。

## 必要なツール

- Verilator 5.x
- C++20、OpenMP、libquadmathを扱えるGCCまたはClang
- MPFRとGMPのdevelopment library
- GNU Make
- Python 3と`mpmath`（定数照合時のみ）

Dev containerにはこれらを導入済みです。
Verilator 5.020、GCC 13.3.0で動作を確認しています。

## テスト

リポジトリ直下から次を実行します。

```sh
make lint-fp32_exp
make test-fp32_exp
make monotonic-fp32_exp
make exhaustive-active-fp32_exp
make exhaustive-fp32_exp
make constants-check
```

`fp32_exp/`内では、それぞれ`make lint`、`make test`、`make monotonic`、
`make exhaustive-active`、`make exhaustive`、`make constants-check`です。

`make test`は特殊値、overflow/underflow境界、引数還元境界、
固定seedの20万乱数入力をbinary128 `expq`参照で検査します。
また、近似範囲から等間隔に選んだ20万入力について、
隣り合う出力を比較して単調性を検査します。

```sh
make test-fp32_exp RANDOM_CYCLES=1000000 MONOTONIC_SAMPLES=1000000
```

`make exhaustive-active`は近似本体へ入る指数field 102～133の
536,870,912入力を、`make exhaustive`は全 `2^32`入力を列挙します。
全数検査はbinary64 `std::exp`を高速オラクルに使い、binary32格子点から
`2^-20 ULP`以内の非自明な候補をMPFRの下向き・上向き丸めで再確認します。
`+0`と`1.0`付近の大量の候補は、`exp`の正値性と単調性から隣接値を
解析的に確定します。

`make monotonic`は、NaNを除く全4,278,190,082入力を`-Inf`から`+Inf`まで
数値順に並べ、全4,278,190,081隣接組の出力を比較します。

スレッド数は次のように指定できます。

```sh
make exhaustive-fp32_exp EXHAUSTIVE_THREADS=32
make monotonic-fp32_exp MONOTONIC_THREADS=32
```

## 検証済み精度

全4,294,967,296入力に対し、次を確認しました。

| 指標 | 結果 |
|---|---:|
| faithful違反 | 0 |
| NaN・±Infの規定値不一致 | 0 |
| 負数または`-0`の出力 | 0 |
| RNE結果から2 step以上の差 | 0 |
| MPFR確認対象 | 1,050 |
| MPFR確認対象の違反 / 未確定 | 0 / 0 |
| `+0` 範囲解析対象 | 1,016,444,764 |
| `1.0` 範囲解析対象 | 1,400,913,921 |
| 範囲解析対象の違反 | 0 |
| 単調性検査対象の非NaN入力 | 4,278,190,082 |
| 単調性の隣接比較 | 4,278,190,081 |
| 単調性違反 | 0 |
| NaN出力を含む隣接組 | 0 |

観測した正規化数の最大絶対誤差は
`0.970926672220230103 ULP`（入力`0xc2ae8e06`）、
非正規化数の最大絶対誤差は
`0.999999239369640414 ULP`（入力`0xc2ce8ed0`）でした。

全数走査の通常オラクルは精度上の保証がない`std::exp`であり、
faithful境界に近い場合についてMPFR区間で再確認しているものの、
形式証明ではなく、精度保証付きの計算機援用証明でもありません。
単調性もVerilated RTLモデルによる全隣接組のシミュレーション結果であり、
形式証明ではありません。

## アルゴリズム

入力を `ln(2)/64` 単位で引数還元します。

```text
n ~= round(x*64/ln(2))
n = 64*q+j,  0 <= j < 64
x = (q+j/64)*ln(2)+r
exp(x) ~= 2^q * (Table[j]+Coeff[j]*(r+r^2/2))
```

回路を小さくするため、`n`、残差、二次項、テーブル、最終丸めの誤差を
独立には扱わず、全データパスで再配分しています。そのため、定数や信号の
一部だけを高精度値へ戻してもfaithful性が維持されるとは限りません。

### 1. 小さいrange-index乗算器

`64/ln(2)` は15-bit Q8定数 `0x5c55` として保持します。24-bitの
`x_sig`をそのまま掛けず、`A=x_sig[23:6]` として次の19-bit値を使います。

```text
index_operand = {A, 1'b1} = 2*A+1
```

積から取り出す位置を1 bit上げると、これは元の24 bit仮数部の各64値区間を
`{A,6'b100000}`で代表させることと等価です。単なる下位6-bit切り捨ての
下向きバイアスを避ける区間中央量子化です。乗算入力の可変部分は18 bitです。

乗算後にシフトして得られた結果のguard bitで`n_abs`を四捨五入し、
入力符号を反映して符号付き15 bitの`n`を作ります。

### 2. modulo残差

残差計算にはQ27定数 `ln(2)/64 = 0x162e43 * 2^-27` を使います。
Q35相当の定数精度を確保するため、基になるQ35定数を

```text
0x162e42ff = 0x162e4300-1
```

と分解し、負の積項の下位6 bitを計算しない近似乗算にしています。この省略は
単なる下位ビット切り捨てではありませんが、全数検査の結果faithful性には影響
しませんでした。さらに、引数項と定数積の上位ビットは必ず相殺するため、
差全体を保持せず`mod 2^22`で計算します。失われた符号はrange-indexのguard bit
と残差上位2 bitから復元します。

この段の出力`s`はsigned 22-bit Q28で、`r`は正入力なら`s`、
負入力なら`-s`に相当します。

### 3. 14-bit square

`exp(r)-1`を`r+r^2/2`で近似します。線形項は22 bitのまま保持しますが、
自乗へ入れるのは`s`の上位14 bitです。

```text
square_operand = abs_ones_complement(s[20:7])
square_product = square_operand^2
```

本来であれば二の補数化が絶対値と負側線形項の二か所に必要ですが、
安価な一の補数を用いています。この近似誤差も後段のテーブルや係数へ
織り込み済みです。

自乗入力を14 bitとすることで、同一`(q,j)`区間内の`polynomial`が入力`x`に
対して単調非減少になります。11 bitまで削減してもfaithful性は保たれますが、
全入力では2,492組の単調性違反が生じます。14 bit化後に残る`j=0→1`、`4→5`、
`12→13`の三つの区間境界は、次節のテーブルと係数の調整で解消します。

### 4. 調整済みQ26テーブルと係数

64要素の`exp2_table_q26[j]`は、単純な`round(2^(j/64)*2^26)`では
ありません。各行へ4～7程度の補正を加え、次をまとめて補償しています。

- 二次多項式の打切り誤差
- range-indexと残差乗算の近似誤差
- 各積の切り捨て誤差
- 正規化数を出力する経路の最終四捨五入相当量

個別にfaithful境界を救う行と、誤差を正負に再中心化する行があります。
`j=1`と`j=13`はテーブル境界の単調性を守るため、誤差バランスだけから
選んだ値より1 Q26 LSB大きくしています。補正量はそれぞれ`+4.38`から`+5.38`、
`+4.53`から`+5.53`へ変化します。
`j=63`だけは入力符号に応じてテーブル値を1 LSB下げます。

18-bit Q17の`Coeff[j]`はテーブル上位ビットと二つの64-bitシードから計算で生成
します。計算式は`floor(Table[j]/2^9)+eps[j]`です。`eps[j]`は通常1または2ですが、
`j=4`だけは通常候補の1から1 Q17 LSB下げ、隣接テーブル境界の単調性を守る0とします。
`eps[4]=1`でもfaithful性は保たれますが、単調性は満たしません。
64行分の係数を独立したROMへ置く必要はありません。

### 5. 正規化とpack

再構成した25-bit Q24仮数は高々1 bitだけ正規化します。結果が正規化数になる
場合、テーブルに織り込み済みの丸め相当分が加算されているので、
そのまま下位ビットを捨てます。独立した「丸め後の再正規化器」はありません。

結果が非正規化数になる場合は、23 bit仮数を最大58 bit右シフトし、
正の非正規化数または`+0`を生成します。オーバーフロー時は`+Inf`を生成します。

### 固定小数点形式

`Qn`は格納整数に`2^-n`を掛けた値を表す固定小数点表現という意味です。

| 信号・定数 | 幅 | 形式 | 近似対象 |
|---|---:|---|---|
| `inv_ln2_64_q8` | 15 | unsigned Q8 | `64/ln(2)` |
| `index_product` | 34 | unsigned Q26 | `x.mant * 64/ln(2)`、ここで`x.mant`は[1,2)の仮数部 |
| `n` / `n_abs` | 15 / 14 | signed / unsigned整数 | `round(x * 64/ln(2))` / その絶対値 |
| `ln2_by_64_q27` | 21 | unsigned Q27 | `ln(2)/64` |
| `s` | 22 | signed Q28 | 還元残差 |
| `square_operand` | 14 | unsigned Q21 | `abs(s)` |
| `square_product` | 28 | unsigned Q42 | `r^2 = abs(s)^2` |
| `polynomial` | 21 | signed Q27 | `r+r^2/2` |
| `exp2_table_q26[j]` | 27 | unsigned Q26 | 調整済みの定数項 |
| `coefficient` | 18 | unsigned Q17 | `r+r^2/2`の係数 |
| `correction_product` | 39 | signed Q44 | 定数項以外の部分 |
| `exp_mant` | 25 | unsigned Q24 | 再構成仮数 |
| `subnormal_mant` | 23 | unsigned Q149 | 非正規化数用可変シフト結果 |

### 主な演算資源

| ブロック | 主な幅 | 役割 |
|---|---:|---|
| range-index定数乗算 | 19×15 bitの上位15 bit | 区間中央量子化した仮数へ`64/ln(2)`を掛ける |
| range-indexシフト | 15 bit | 指数に応じて`n`とguard bitの位置を揃える |
| range-index四捨五入 | 14 bit | `x * 64/ln(2)`に近い整数を得る |
| 残差入力シフト | 36→22 bit | `abs(x)`をQ29へ揃え、残差計算に必要な下位22 bitを取り出す |
| 残差定数乗算 | 14×20 bitの下位20 bit | `n_abs*ln(2)/64`の下位積を作る |
| 残差加減算 | 22 bit | 上位が相殺する差を`mod 2^22`で求める |
| 自乗 | 14×14 bit | 残差上位部から`r^2/2`を作る |
| 主テーブル | 64×27 bit | 調整済みQ26の`2^(j/64)`を保持する |
| 係数生成 | 64×1 bit×2、`j=4`判定、5-bit加算 | 主テーブルの上位bitと二つのシードベクトルから18-bit係数を作る |
| 補正乗算 | unsigned 18×signed 21 bit | `Coeff[j]*(r+r^2/2)`を作る |
| 非正規化数シフト | 23 bit | 仮数を結果指数に応じて右シフトする |

faithfulが必要でも単調性は不要である場合、自乗は11×11 bitにすることが可能です。

## 定数とテーブルの照合

`tools/gen_constants.py`は100桁精度でQ8/Q27定数を再生成し、
Q26の基準RNE値へfaithful性と単調性のために探索した補正値を加えてRTLと照合します。
二つの係数調整計算シードと`j=4`の例外indexも照合します。

```sh
make constants-check
make constants
```

後者はRTLへ転記できる十六進値と、各テーブル行の`2^(j/64)*2^26`からの
実際の補正量を表示します。table delta、mask、例外index自体を再探索するツールではありません。

テーブル値、シード、近似定数、抽出位置、演算幅を変更した場合は、quick testだけでなく
全 `2^32` 入力の検査と単調性検査を再実行してください。正規化数側のfaithful余裕は約0.0291 ULP
しかありません。

## 合成時の注意

合成トップは`FP32Exp`です。全体はclockなしの組合せ回路で、パイプラインレジスタは
含みません。

64要素テーブルはSystemVerilogのunpacked定数配列で記述しています。合成器がこの構文を
直接扱えない場合は、同じ64値を`function`と`case`で表すROMへ変換する必要があります。
変換時はテーブル値と入出力がビット単位で一致することを確認してください。

## ライセンス

Copyright 2026 Ryota Shioya and Toru Koizumi

Apache License 2.0の下で公開します。詳細は[`../LICENSE`](../LICENSE)を参照してください。
