# FP32 Exp2

IEEE 754 binary32のbit patternを入力し、底2指数関数`exp2(x)=2^x`を返す、
合成可能なSystemVerilog組合せ回路です。入力を1/64間隔へ引数還元し、
64エントリの調整済みQ26テーブルと二次近似を使います。
正の非正規化数を含む全出力範囲でfaithful roundingを行い、
非NaN入力に対して単調非減少となることを目標とします。

- トップモジュール: `FP32Exp2`
- インターフェース: clockなしの32-bit入出力
- 非正規化数出力: 対応
- 精度: 厳密値を挟む二つのbinary32値のどちらか
- 単調性: 非NaN入力に対して単調非減少

## ファイル構成

```text
fp32_exp2/
├── fp32_exp2.sv
├── README.md
├── Makefile
├── test/
│   ├── exhaustive.cpp
│   ├── monotonic.cpp
│   ├── reference.c
│   └── tb_fp32_exp2.sv
└── tools/
    └── gen_constants.py
```

`fp32_exp2.sv`だけが合成対象です。`test/`はquick test、全bit pattern検査、
単調性検査、`tools/`は定数とテーブルの再生成・転記ミス検査に使います。
全数検査と単調性検査の走査器は、`fp32_exp`側の共通実装を設定して利用します。

## インターフェース

```systemverilog
module FP32Exp2 (
    input  wire [31:0] x,
    output wire [31:0] result
);
```

`x`と`result`はIEEE 754 binary32のbit patternです。clock、reset、valid、ready、
例外flag、NaN payload保持、動的な丸めmode入力はありません。

```systemverilog
FP32Exp2 u_exp2 (
    .x(x),
    .result(result)
);
```

## 数値仕様

faithful roundingは、無限精度の`2^x`を挟む直下・直上のbinary32値の
どちらかを返すことを意味します。常にround-to-nearestの結果を返す
correct roundingではありません。厳密値がbinary32で表せる場合は、
直下と直上が同じになるため、その値を返します。

| 入力または条件 | 出力 |
|---|---|
| NaN | canonical quiet NaN `0x7fc00000` |
| `+Inf` | `+Inf` |
| `-Inf` | `+0` |
| `+0`、`-0` | `1.0` |
| 入力の絶対値が2^-25未満 | `1.0` |
| `x >= 128` | `+Inf` |
| `x = -126` | 最小正規化数 `2^-126` |
| `-149 <= x < -126`の整数 | 対応する2の累乗の非正規化数 |
| `x = -150` | `+0`（faithful候補の下側） |
| 十分に小さい負入力 | `+0` |

有限binary32入力では、128未満の最大値が`127.99999237060546875`、
次の値が128なので、overflow境界の間に入力はありません。同様に、
正規化数と非正規化数の境界は入力`-126`、最小非正規化数の厳密値は
入力`-149`です。`x<-149`の厳密値は`+0`と最小非正規化数の間にあるため、
どちらもfaithful候補ですが、この実装は単調な一つの境界で`+0`へ移ります。

正規化数経路では、最終丸め相当のbiasをテーブルへ織り込んでから
下位bitを捨てます。非正規化数経路は右shift後に下位bitを捨てますが、
データパス全体と調整済みテーブルを合わせてfaithful性を検証します。

## アルゴリズム

### 1. まず整数べきと仮数部分へ分ける

底が2なので、入力`x`の整数部分は出力の2の累乗へ直接移せます。
`x=q+f`と分けると、

```text
2^x = 2^q * 2^f
```

です。IEEE 754 binary32も`M*2^E`という形なので、`2^q`を乗算器で掛ける
必要はありません。最後の指数fieldへ`q`を反映すれば済みます。
実際に近似回路で求める必要があるのは、値域の小さい仮数側`2^f`だけです。

### 2. 仮数側を64分割する

`f`をそのまま多項式へ入れる代わりに、最も近い1/64格子へ分けます。

```text
n = round(64*x)
n = 64*q+j,  0 <= j < 64
r = x-n/64
```

この定義から、全体は次の三因子になります。

```text
2^x = 2^q * 2^(j/64) * 2^r
    = 2^q * 2^(j/64) * exp(ln(2)*r)
```

- `2^q`: 出力指数fieldで表す
- `2^(j/64)`: 64要素テーブルから読む
- `exp(ln(2)*r)`: 小さい残差だけ二次式で近似する

最近傍格子を選ぶので`|r|<=1/128`です。広い入力値域は指数fieldへ逃がし、
テーブルと多項式が扱う値域を常にほぼ`[1,2)`へ保てます。

### 3. 小さい残差だけを二次近似する

`z=ln(2)*r`と置くと、`|z|<=ln(2)/128`です。

```text
exp(z) = 1+z+z^2/2+z^3/6+...
```

ここでは`z+z^2/2`までを計算します。三次項はbinary32の仮数精度付近まで
小さく、残る打切り誤差、固定小数点量子化、積の切り捨ては、
テーブルと行別係数の微調整を含むデータパス全体で再中心化します。

最終的な近似式は次です。

```text
2^x ~= 2^q * (Table[j]+Coeff[j]*(z+z^2/2))
```

### 4. `exp(x)`より単純になる引数還元

自然指数関数では`round(64*x/ln(2))`と`n*ln(2)/64`が必要です。
一方、`2^x`では格子間隔`1/64`が2の累乗なので、binary32入力と正確に整合します。

回路は`|x|`を37-bit unsigned Q29へ一度shiftし、

- 上位15 bitから`n=round(64*|x|)`を得る
- 下位23 bitをsigned値として読み、`r=|x|-n/64`を得る

という二つの用途に使います。`n/64`のQ29表現は`2^23`の整数倍なので、
減算後の下位23 bitは`|x|`の下位23 bitと同じです。このため、
`fp32_exp`にあるrange-index定数乗算と残差用定数乗算は不要です。

負入力の引数還元tieでは`r=+1/128`がsigned Q28の正側上限を1だけ超えるため、
二の補数の符号反転ではなく一の補数を使い、表現可能な最大値へ寄せます。

### 固定小数点形式

`Qn`は、格納整数へ`2^-n`を掛けた値を表します。

| 信号・定数 | 幅 | 形式 | 役割 |
|---|---:|---|---|
| `x_q29` | 37 | unsigned Q29 | shift後の入力絶対値 |
| `n` / `n_abs` | 16 / 15 | signed / unsigned整数 | `round(64*x)`とその絶対値 |
| `r_mag_q28` / `r_q28` | 22 | signed Q28 | 1/64格子からの残差 |
| `ln2_q21` | 21 | unsigned Q21 | `ln(2)` |
| `z_product_q49` | 44 | signed Q49 | `ln(2)*r`の定数積 |
| `z_q28` | 22 | signed Q28 | 二次近似へ入れる残差 |
| `square_operand` | 14 | unsigned Q21 | 自乗用に縮めた`abs(z)` |
| `square_product` | 28 | unsigned Q42 | `z^2` |
| `polynomial` | 21 | signed Q27 | `z+z^2/2` |
| `exp2_table_q26[j]` | 27 | unsigned Q26 | 調整済み`2^(j/64)` |
| `coefficient` | 18 | unsigned Q17 | 一次項以降の係数 |
| `correction_product` | 39 | signed Q44 | table補正積 |
| `exp_mant` | 25 | unsigned Q24 | 再構成した仮数 |

主な乗算は、定数`ln(2)`を掛ける22×21 bit、自乗の14×14 bit、
補正の19×21 bitです。引数還元そのものには乗算器を使いません。

## テスト

リポジトリ直下から次を実行します。

```sh
make lint-fp32_exp2
make test-fp32_exp2
make exhaustive-active-fp32_exp2
make exhaustive-fp32_exp2
make monotonic-fp32_exp2
make constants-check-fp32_exp2
```

`fp32_exp2/`内では、それぞれ`make lint`、`make test`、
`make exhaustive-active`、`make exhaustive`、`make monotonic`、
`make constants-check`です。

`make test`は特殊値、overflow／underflow境界、全引数還元境界の近傍、
固定seedの乱数入力をbinary128 `exp2q`参照で検査します。また、近似範囲から
等間隔に選んだ入力で単調性を検査します。

`make exhaustive-active`は近似本体へ入る指数field 102～134の
553,648,128入力、`make exhaustive`は全`2^32` bit patternを列挙します。
高速oracleはbinary64 `std::exp2`を使います。MPFR headerが利用できる環境では
binary32格子点に近い候補を`mpfr_exp2`の上下方向丸めで再確認します。
`EXHAUSTIVE_USE_MPFR=0`で高速oracleだけ、`=1`でMPFR監査を明示できます。

`make monotonic`はNaNを除く全入力を`-Inf`から`+Inf`まで数値順に並べ、
全隣接組の出力が単調非減少であることを検査します。

```sh
make exhaustive-fp32_exp2 EXHAUSTIVE_THREADS=32
make monotonic-fp32_exp2 MONOTONIC_THREADS=32
```

## 検証済み精度

全`2^32`入力をVerilated RTLで走査し、binary64 `std::exp2`から得た
binary32上下値に対して次を確認しました。

| 指標 | 結果 |
|---|---:|
| 全入力 | 4,294,967,296 |
| faithful違反 | 0 |
| NaN・±Infの規定値不一致 | 0 |
| 負数または`-0`の出力 | 0 |
| RNE不一致 | 82,309,389 |
| RNEから2 step以上の差 | 0 |
| MPFR確認対象 | 1,583 |
| MPFR確認対象の違反 / 未確定 | 0 / 0 |
| `+0`／`1.0`近傍の解析対象 | 1,012,334,592 / 1,408,348,364 |
| 解析対象の違反 | 0 |
| 正規化数の最大絶対誤差 | 0.945101881399750710 ULP |
| 非正規化数の最大絶対誤差 | 0.999997611963177491 ULP |

最大誤差を観測した正規化数入力は`0x3dad1d2e`、非正規化数入力は
`0xc3114cb0`です。binary128 `exp2q`を使うquick testでは、特殊値、
全17,792引数還元境界の前後、固定seedの20万乱数入力を含む253,397入力に
対して最大1 ULP、faithful違反0でした。

単調性は、NaNを除く全4,278,190,082入力の全4,278,190,081隣接組で
違反0でした。`j=14`のtable値を基準値から1 Q26 LSB下げているのは、
`x=14.5/64`の引数還元境界にあった1 stepの低下を解消するためです。

全数走査はMPFR/GMPを含む開発containerで実行しました。通常の候補生成には
binary64 `std::exp2`を使い、binary32格子点から`2^-20 ULP`以内の非自明な候補を
MPFRの下向き・上向き丸めで再確認しました。`+0`と`1.0`近傍の大量の候補は、
`2^x`の正値性と単調性から隣接値を解析的に確定しました。MPFR確認は全候補が
256-bitで確定しています。

この全数走査、quick testのbinary128 oracle、単調性走査はいずれも形式証明ではなく、
精度保証付きの計算機援用証明でもありません。

## ライセンス

Copyright 2026 Ryota Shioya and Toru Koizumi

Apache License 2.0の下で公開します。詳細はリポジトリ直下の`LICENSE`を参照してください。
