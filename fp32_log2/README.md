# FP32 Log2

IEEE 754 binary32のbit patternを入力し、底2の対数`log2(x)`を返す、合成可能な
SystemVerilog組合せ回路です。精度とsubnormal対応が異なる二つの公開トップがあります。

- clockなしの32-bit入出力
- `FP32Log2`: 正のsubnormal入力に対応し、正の有限入力に対してfaithful rounding
- `FP32Log2Lite`: 入力subnormalをFTZとし、複合演算器向けの緩い誤差条件で小面積化
- どちらも正の入力領域で単調非減少

## インターフェース

```systemverilog
module FP32Log2 (
    input  wire [31:0] x,
    output wire [31:0] result
);

module FP32Log2Lite (
    input  wire [31:0] x,
    output wire [31:0] result
);
```

## 数値仕様

| 入力または条件 | `FP32Log2` | `FP32Log2Lite` |
|---|---|---|
| NaN | canonical quiet NaN `0x7fc00000` | 同左 |
| 負の非零値、`-Inf` | canonical quiet NaN `0x7fc00000` | 同左 |
| `+0`、`-0` | `-Inf` | `-Inf` |
| `+Inf` | `+Inf` | `+Inf` |
| 正のsubnormal | 数学的な`log2(x)`のfaithful値 | FTZとして`-Inf` |
| 正のnormal | `log2(x)`のfaithful値 | RNEから2 ULP以内、または絶対誤差`4*2^-23`以内 |
| 正の2の累乗 | 対応する整数を正確に返す | 同左 |

faithful roundingは、無限精度の結果を挟む直下・直上のbinary32値のどちらかを返すことを
意味します。correct roundingを要求する仕様ではありません。

Liteの誤差条件は、DesignWareの複合演算器`DW_lp_fp_multifunc`におけるlog2の
数値誤差条件を比較目標にしたものです。負入力などの特殊値規約までvendor IPと一致させる
仕様ではありません。

## `FP32Log2`のアルゴリズム

### 全体の構造

対数は1の近くで次のように展開できます。

```text
log2(1+r)
  = (r-r^2/2+r^3/3-r^4/4+...)/ln(2)
```

`|r|`が小さいほど、低い次数で打ち切ったときの誤差は小さくなります。一方、広い範囲を取る
binary32入力へ`r=x-1`をそのまま適用すると、短い多項式では十分な精度を得られません。
そこで、入力を整数項と1に近い仮数へ分解し、tableで多項式へ入る差分をさらに縮小します。

```text
1. xを2^q*mへ正規化する
2. mに最も近いtable中心cを選び、d=m-cを作る
3. q+log2(c)へ、dについての三次式を加える
4. 固定小数点の結果をbinary32へ丸める
```

### 指数と仮数への分解

正のnormal入力を`x=M*2^E`、`1 <= M < 2`とすると、次のように中心化します。

```text
M < sqrt(2) の場合:
    q = E
    m = M

M >= sqrt(2) の場合:
    q = E+1
    m = M/2
```

これにより、仮数の範囲は次の区間に限定されます。

```text
1/sqrt(2) <= m < sqrt(2)
```

正のsubnormal入力も先頭の1を検出し、同じ`2^q*m`形式へ正規化します。
`log2(2^q)=q`なので、`q`は近似せず、対数値の整数項として固定小数点加算します。

### tableによる範囲縮小

`m`に最も近い中心を91点のtableから選びます。

```text
c = 1+j/2^7,  -37 <= j <= 53
d = m-c
```

中心の間隔は`2^-7`なので、最近傍を選んだ後の`|d|`はおよそ`2^-8`以下になります。
この操作により、広い仮数区間の計算を、小さな差分`d`についての計算へ還元します。

```text
x = 2^q*(c+d)
log2(x) = q+log2(c)+log2(1+d/c)
```

### table中心まわりの三次近似

実装では`d/c`を個別に計算せず、`log2(c+d)`をtable中心`c`のまわりで直接展開します。

```text
log2(c+d)
  = log2(c)
  + d/(c*ln(2))
  - d^2/(2*c^2*ln(2))
  + d^3/(3*c^3*ln(2))
  + ...
```

中心ごとに次の係数をtableへ格納します。

```text
L[c] =  log2(c)
A[c] =  1/(c*ln(2))
B[c] = -1/(2*c^2*ln(2))
C[c] =  1/(3*c^3*ln(2))
```

多項式はHorner形式で評価します。

```text
log2(x) ~= q+L[c]+d*(A[c]+d*(B[c]+d*C[c]))
```

table選択後の`d`はsigned 18 bitまで小さくなるため、三つの乗算を狭い入力幅で実装できます。

### 固定小数点幅

ここでQnは、小数部をn bit持つ固定小数点表現を表します。

| 値 | 表現 | 幅 |
|---|---|---:|
| 正規化仮数`m` | Q24 | 25 bit |
| table差分`d` | signed Q24 | 18 bit |
| `L[c]` | signed Q34 | 35 bit |
| `A[c]` | signed Q27 | 30 bit |
| `B[c]` | signed Q17 | 19 bit |
| `C[c]` | signed Q8 | 10 bit |
| 一般経路の和 | signed Q34 | 43 bit |
| `c=1, q=0`の補正積 | signed Q51 | 48 bit |

Horner式の可変乗算は`d*C`、`d*(B+d*C)`、`d*(A+d*(B+d*C))`の3回です。
各段でround-to-nearestし、28 bit、37 bit、48 bitの積から次段に必要な部分を取り出します。
91行tableの1行は`L/A/B/C`を合わせて94 bitです。

### binary32への変換

一般経路では、`q`、`L[c]`、多項式の結果をQ34で加算してからbinary32へ丸めます。

`q=0`かつ`c=1`では`q+L[c]`がexact zeroとなり、出力自身が非常に小さくなります。この領域では
Q34へ早く丸めると相対精度を失うため、最後の補正積をQ51のままpackerへ渡します。packerは
一般経路のQ34値と1近傍のQ51値を直接受け、符号、指数、仮数を生成します。

特殊値は近似経路へ入る前に判定し、数値仕様の表に従って出力します。

## `FP32Log2Lite`のアルゴリズム

### 全体の構造

正のnormal入力を`x=2^E*M, 1 <= M < 2`へ分けると、実際に近似する必要があるのは
仮数部分だけです。

```text
log2(x) = E+log2(M)
```

`E`は整数のままQ22へ移し、`log2(M)`だけを64区間の二次式で求めます。

```text
1. 仮数上位6 bitをtable indexにする
2. 仮数下位17 bitを区間中心からのsigned残差rにする
3. log2(M) ~= C0[i]+r*(C1[i]+r*C2[i])
4. Eを加えたsigned Q22値をbinary32へround-to-nearest-evenでpackする
```

indexは仮数のbit sliceだけで作れるため、中心探索や境界比較器は不要です。三次式や
reciprocalによる範囲縮小も使わず、可変乗算を二つに抑えます。

### 区分二次近似

区間`i`の中心を`c=1+(i+0.5)/64`とし、区間内位置を
`t=r/2^17`とすると、`M=c+t/64`です。中心まわりの二次Taylor係数を出発点にし、
固定小数点での切り捨てを含む全`2^17`入力を区間ごとに検査して係数を数LSBだけ調整します。

```text
C0 ~= log2(c)
C1 ~= 1/(64*c*ln(2))
C2 ~= -1/(2*64^2*c^2*ln(2))
```

係数とHorner和はすべて`2^-22`単位です。`C0/C1/C2`の実格納幅は
22/18/11 bitで、64行tableは合計3,264 bitです。残差はsigned 17 bit、
二つの積は`17x11` bitと`17x18` bitです。

`M=1`では真値がzeroなので、table近似を通さず整数項を直接返します。これにより、
zero近傍の絶対誤差仕様とは別に、正の2の累乗をexactにします。Q22の絶対刻みは
`2^-22=2*2^-23`であり、Liteの絶対誤差上限へ合わせた幅です。

係数調整後は`x in [0.5,2)`の全16,777,216入力で誤差条件と単調性を検査します。
これは全`2^32` bit patternの列挙や形式証明ではありません。

## ファイル

| ファイル | 内容 |
|---|---|
| `fp32_log2.sv` | RTL、table、公開トップ`FP32Log2` |
| `fp32_log2_lite.sv` | 64区間二次RTL、公開トップ`FP32Log2Lite` |
| `tools/gen_constants.py` | tableと係数の生成・照合 |
| `tools/gen_lite_constants.py` | Lite係数の生成・照合 |
| `test/tb_fp32_log2*.sv` | directed、random、単調性試験 |
| `test/exhaustive*.cpp` | 各仕様で重要な入力領域の全数検査 |
| `test/reference.c` | binary128参照値、faithful境界、Lite絶対誤差 |

## 検証

```sh
make lint
make test
make exhaustive
make constants-check
```

`test`は特殊値、正規化境界、table境界、指数境界、固定seed乱数、単調性を検査します。
`exhaustive`は、`FP32Log2`について出力ULPが最も細かくなる`q=0`の中心区間と
正のsubnormal、`FP32Log2Lite`について`x in [0.5,2)`の全16,777,216入力を検査します。
個別には`make test-lite`、`make exhaustive-lite`も使用できます。
