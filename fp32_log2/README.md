# FP32 Log2

IEEE 754 binary32のbit patternを入力し、底2の対数`log2(x)`を返す、合成可能な
SystemVerilog組合せ回路です。公開トップモジュールは`FP32Log2`です。

- clockなしの32-bit入出力
- 正のsubnormal入力に対応
- 正の有限入力に対してfaithful rounding
- 正の入力領域で単調非減少

## インターフェース

```systemverilog
module FP32Log2 (
    input  wire [31:0] x,
    output wire [31:0] result
);
```

## 数値仕様

| 入力または条件 | 出力 |
|---|---|
| NaN | canonical quiet NaN `0x7fc00000` |
| 負の非零値、`-Inf` | canonical quiet NaN `0x7fc00000` |
| `+0`、`-0` | `-Inf` |
| `+Inf` | `+Inf` |
| 正の有限値 | `log2(x)`のfaithful値 |
| 正の2の累乗 | 対応する整数を正確に返す |

faithful roundingは、無限精度の結果を挟む直下・直上のbinary32値のどちらかを返すことを
意味します。correct roundingを要求する仕様ではありません。

## アルゴリズム

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

## ファイル

| ファイル | 内容 |
|---|---|
| `fp32_log2.sv` | RTL、table、公開トップ`FP32Log2` |
| `tools/gen_constants.py` | tableと係数の生成・照合 |
| `test/tb_fp32_log2.sv` | directed、random、単調性試験 |
| `test/exhaustive.cpp` | 中心区間と正のsubnormalの全数検査 |
| `test/reference.c` | binary128参照値とfaithful境界 |

## 検証

```sh
make lint
make test
make exhaustive
make constants-check
```

`test`は特殊値、正規化境界、table境界、指数境界、固定seed乱数、単調性を検査します。
`exhaustive`は、出力ULPが最も細かくなる`q=0`の中心区間8,388,608入力と、正の
subnormal全8,388,607入力を検査します。これは全`2^32` bit patternの列挙や形式証明ではありません。
